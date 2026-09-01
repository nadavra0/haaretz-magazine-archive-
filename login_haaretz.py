#!/usr/bin/env python3
"""Fully automated Haaretz login — no human click required, and no new
"device" registered on every run.

Haaretz's subscription caps concurrent logged-in devices (confirmed
2026-09-01: "ניצלת את מכסת המכשירים למינוי" — device quota exhausted — after
a handful of fresh `browser.new_context()` login attempts while testing).
A stateless "log in with a brand-new browser identity every run" design
would just keep tripping that same wall. So this uses a Playwright
*persistent* browser profile (a fixed on-disk directory, PROFILE_DIR) that's
reused across every run — same browser fingerprint/local storage every
time, so Haaretz sees ONE consistent device, not a new one per run.

Login only actually happens (email+password submitted) the first time, or
whenever that profile's own session has gone stale — most runs just reuse
the still-valid session silently. Called from weekly_update.py at the start
of every run, local or GitHub Actions alike.

Credentials (only used on the rare real-login path) are never hardcoded
here or in the repo (this repo is public):
  - GitHub Actions: HAARETZ_EMAIL / HAARETZ_PASSWORD repo secrets, injected
    as env vars by the workflow. PROFILE_DIR there is restored/saved via
    actions/cache so the "device" persists across scheduled runs too.
  - Local runs: macOS Keychain, service "haaretz-magazine-archive-login",
    account = email, password = the keychain item's password. Store it with:
      read -s -p "Haaretz password: " HZPW; echo
      security add-generic-password -a "<email>" -s "haaretz-magazine-archive-login" -w "$HZPW" -U
      unset HZPW

Never raises on failure — a login miss should fall back to whatever cookies
already exist (from a prior run or the HAARETZ_COOKIES secret), not wipe
anything. Success is defined strictly as ending up with a real sso_token
cookie, not just "the form submitted without an error".
"""
import json, os, subprocess, sys

ARCHIVE_DIR = os.path.dirname(os.path.abspath(__file__))
COOKIES_FILE = os.path.join(ARCHIVE_DIR, "haaretz_cookies.json")
FAILURE_SHOT = os.path.join(ARCHIVE_DIR, "login_failure.png")
PROFILE_DIR = os.path.join(ARCHIVE_DIR, "haaretz_browser_profile")
KEYCHAIN_SERVICE = "haaretz-magazine-archive-login"
GH_REPO = "nadavra0/haaretz-magazine-archive-"
GH_ACCOUNT = "nadavra0"


def get_credentials():
    email = os.environ.get("HAARETZ_EMAIL")
    password = os.environ.get("HAARETZ_PASSWORD")
    if email and password:
        return email, password

    # Local fallback: macOS Keychain (never available/attempted in GitHub Actions)
    try:
        acct_probe = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-g"],
            capture_output=True, text=True,
        )
        for line in acct_probe.stdout.splitlines():
            if line.strip().startswith('"acct"'):
                email = line.split("=", 1)[1].strip().strip('"')
        pw = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True, text=True, check=True,
        )
        password = pw.stdout.strip()
    except subprocess.CalledProcessError:
        pass
    return email, password


def _has_sso(cookies):
    return "sso_token" in {c["name"] for c in cookies if "haaretz" in c.get("domain", "")}


def login_and_save_cookies():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE_DIR, headless=True, viewport={"width": 1280, "height": 900}
        )
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()

            # 1. Check whether this persistent profile is already authenticated
            # (the common case) — if so, don't touch the login form at all.
            page.goto("https://www.haaretz.co.il/", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2000)
            cookies = ctx.cookies()
            if _has_sso(cookies):
                json.dump(cookies, open(COOKIES_FILE, "w"), ensure_ascii=False, indent=2)
                print(f"✓ Persistent profile already authenticated — no login needed "
                      f"({len(cookies)} cookies).")
                sync_to_github_secret()
                return True

            # 2. Not authenticated (first run, or this profile's session died) —
            # do a real email+password login, once, inside this SAME profile.
            email, password = get_credentials()
            if not email or not password:
                print("✗ No Haaretz credentials found (HAARETZ_EMAIL/HAARETZ_PASSWORD env, "
                      f"or macOS Keychain item '{KEYCHAIN_SERVICE}'). Skipping automated login.")
                return False

            page.goto("https://login.haaretz.co.il/", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2000)

            email_input = page.query_selector("input[type=email]")
            if not email_input:
                print("✗ Email field not found — login page layout may have changed.")
                page.screenshot(path=FAILURE_SHOT)
                return False
            email_input.fill(email)
            page.click('button:has-text("המשך")')
            page.wait_for_timeout(3000)

            pw_input = page.query_selector("input[type=password]")
            if not pw_input:
                print("✗ Password field never appeared — wrong email, layout change, or CAPTCHA.")
                page.screenshot(path=FAILURE_SHOT)
                return False
            pw_input.fill(password)
            # "התחברות" (log in) vs the decoy "התחברות ללא סיסמה" (log in without
            # a password) button — match the exact label, not a substring.
            # (CSS :text-is() doesn't reliably match here — surrounding
            # whitespace in the button's text node trips exact matching —
            # so filter by stripped innerText in Python instead.)
            login_btn = next(
                b for b in page.query_selector_all("button")
                if b.inner_text().strip() == "התחברות"
            )
            login_btn.click()
            page.wait_for_timeout(4000)

            cookies = ctx.cookies()
            if not _has_sso(cookies):
                names = {c["name"] for c in cookies if "haaretz" in c.get("domain", "")}
                print(f"✗ Login did not produce sso_token — got: {sorted(names)}. "
                      f"Wrong password, CAPTCHA, device quota, or layout change.")
                page.screenshot(path=FAILURE_SHOT)
                return False

            json.dump(cookies, open(COOKIES_FILE, "w"), ensure_ascii=False, indent=2)
            print(f"✓ Logged in as {email} (new profile session), saved {len(cookies)} cookies.")
        finally:
            ctx.close()

    sync_to_github_secret()
    return True


def sync_to_github_secret():
    """Best-effort: keep the GitHub Actions HAARETZ_COOKIES secret as a
    fallback for the rare case a future run's own login attempt fails there.
    Only meaningful when run locally — gh CLI switching accounts has no
    effect (and isn't needed) inside GitHub Actions itself."""
    if os.environ.get("GITHUB_ACTIONS"):
        return
    try:
        all_cookies = json.load(open(COOKIES_FILE, encoding="utf-8"))
        haaretz_cookies = [c for c in all_cookies if "haaretz.co.il" in c.get("domain", "")]
        body = json.dumps(haaretz_cookies)
        if len(body.encode("utf-8")) > 48 * 1024:
            print(f"⚠ {len(haaretz_cookies)} haaretz.co.il cookies exceed the 48KB "
                  f"GitHub secret limit — sync skipped")
            return
        subprocess.run(["gh", "auth", "switch", "--user", GH_ACCOUNT],
                        check=True, capture_output=True, text=True)
        subprocess.run(
            ["gh", "secret", "set", "HAARETZ_COOKIES", "--repo", GH_REPO, "--body", body],
            check=True, capture_output=True, text=True,
        )
        print(f"✓ Synced {len(haaretz_cookies)} cookies to the {GH_REPO} HAARETZ_COOKIES secret")
    except Exception as e:
        print(f"⚠ Could not sync cookies to GitHub secret ({e})")


if __name__ == "__main__":
    ok = login_and_save_cookies()
    sys.exit(0 if ok else 1)

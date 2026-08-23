#!/usr/bin/env python3
"""Open a headed browser so you can log in to Haaretz, then saves cookies after 3 minutes.

Loads the EXISTING cookies as a starting point (not a blank session) — this can be
launched unattended (e.g. by weekly_update.py's cookie-health nudge) without risk:
if nobody logs in during the wait, the saved cookies are just the same session
that was already there (refreshed, not wiped), never worse than before.

After saving, best-effort syncs the new cookies to the GitHub Actions
HAARETZ_COOKIES secret too, so a single local login fixes both the local cron
and the GitHub Actions workflow — otherwise refreshing locally silently leaves
the GH Actions copy stale.
"""
import json, os, time, sys, subprocess
from playwright.sync_api import sync_playwright

COOKIES_FILE = os.path.join(os.path.dirname(__file__), "haaretz_cookies.json")
WAIT_SECONDS = 180  # 3 minutes
GH_REPO = "nadavra0/haaretz-magazine-archive-"
GH_ACCOUNT = "nadavra0"

def main():
    existing_cookies = []
    if os.path.exists(COOKIES_FILE):
        try:
            existing_cookies = json.load(open(COOKIES_FILE, encoding="utf-8"))
        except Exception:
            pass

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=50)
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        if existing_cookies:
            ctx.add_cookies(existing_cookies)
        page = ctx.new_page()

        page.goto("https://www.haaretz.co.il/login", wait_until="domcontentloaded")

        print()
        print("=" * 60)
        print("  Browser is open — please log in to Haaretz.")
        print(f"  Will auto-save cookies in {WAIT_SECONDS} seconds.")
        print("=" * 60)

        # Countdown — browser stays open the whole time
        for remaining in range(WAIT_SECONDS, 0, -5):
            sys.stdout.write(f"\r  {remaining}s remaining...  ")
            sys.stdout.flush()
            time.sleep(5)

        print("\r  Time's up — saving cookies...          ")

        cookies = ctx.cookies()
        json.dump(cookies, open(COOKIES_FILE, "w"), ensure_ascii=False, indent=2)
        print(f"✓ Saved {len(cookies)} cookies to {COOKIES_FILE}")

        now = time.time()
        print("\nKey haaretz.co.il cookies:")
        for c in cookies:
            if 'haaretz' in c.get('domain', '') and c['name'] in (
                'sso_token', 'acl', 'productsStatus', 'userProducts', 'user_details'
            ):
                exp = c.get('expires', -1)
                if exp > 0:
                    exp_str = time.strftime('%Y-%m-%d', time.localtime(exp))
                    status = 'EXPIRED' if exp < now else f'valid until {exp_str}'
                else:
                    status = 'session'
                print(f"  {c['name']}: {status}")

        browser.close()

        sync_to_github_secret()
        print("\nDone.")


def sync_to_github_secret():
    """Best-effort: push the freshly-saved cookies to the GitHub Actions
    HAARETZ_COOKIES secret so the weekly workflow doesn't keep running on a
    stale copy after a local refresh. Never raises — this repo's `gh` CLI
    defaults to a different (Forter) account with no access here, so this
    switches accounts first and just prints a warning if anything fails."""
    try:
        subprocess.run(["gh", "auth", "switch", "--user", GH_ACCOUNT],
                        check=True, capture_output=True, text=True)
        subprocess.run(
            ["gh", "secret", "set", "HAARETZ_COOKIES", "--repo", GH_REPO,
             "--body", open(COOKIES_FILE, encoding="utf-8").read()],
            check=True, capture_output=True, text=True,
        )
        print(f"✓ Synced fresh cookies to the {GH_REPO} HAARETZ_COOKIES secret")
    except Exception as e:
        print(f"⚠ Could not sync cookies to GitHub secret ({e}) — "
              f"GitHub Actions will keep using its stale copy until this is "
              f"done manually: gh secret set HAARETZ_COOKIES --repo {GH_REPO} "
              f"--body \"$(cat {COOKIES_FILE})\"")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Weekly magazine updater — runs every Sunday at 10:00.
Scrapes last Friday's magazine, finds its cover, updates docs/, commits and pushes.

How article fetching works:
  - scraper.py fetches sitemap-YYYYMM.xml from Haaretz to discover all magazine articles
  - Each article URL is fetched (with Playwright + saved cookies for paywall bypass)
  - Metadata: title, og:image, section are extracted from HTML
  - Articles grouped by section, saved to issues/YYYY-MM-DD.json

How cover detection works (tightened 2026-08-17, then again 2026-08-23):
  - Priority 1 (scraper.py, static HTML): <img alt="שער מוסף..."> anywhere, OR any
    img whose filename alone is an unambiguous cover asset (shaar*, mu\d+, frontpage*).
    Generic "-web."/"-animation." filenames are NOT accepted here on their own —
    that's Haaretz's normal same-day image-optimization suffix, not cover-exclusive,
    and combined with a bare "שער" substring in an unrelated caption it previously
    let a comic-strip illustration get picked up as the cover (2026-08-14).
  - Priority 2: og:image whose filename matches the date pattern (date-validated,
    guards against cross-issue sidebar bleed-in from a different week's cover).
  - No more blind fallback to "first article's og:image" — if nothing matches a
    real cover marker, cover_image is left unset and a "NO COVER FOUND — needs
    manual review" warning is printed instead of silently shipping a guess.
  - find_cover.py (Playwright, run when Priority 1/2 found nothing usable) applies
    the same tightened rule: explicit "שער מוסף", or a strict cover filename alone,
    or an *exact* bare "שער" label (not a substring) paired with a date-matched
    filename.
  - Existing cover is NEVER overwritten unless a Priority-1 shaar_image is found
    AND it passes is_portrait_cover_crop() below.
  - 2026-08-21 incident: Priority 2's date-pattern filename match put an unrelated
    column's photo (og:image happened to be named '21-8-26-web.jpg') into the cover
    slot. The real cover DOES exist and IS embedded on the flagship article's page
    as a "שער מוסף" widget (confirmed directly by Nadav — shaar.jpg, masthead+date
    visible) — but this repo's own scraper session (Playwright + haaretz_cookies.json,
    headless) could not see it there: a full HTML dump of that exact page found zero
    "שער"/"shaar" occurrences. Root cause of that gap is UNCONFIRMED (stale/degraded
    session auth vs. headless/bot detection vs. something else — see CLAUDE.md). Do
    NOT assume the widget itself is gone from Haaretz's site; only that Priority 1
    couldn't see it in this run. Fix: scraper.is_portrait_cover_crop() gates every
    candidate (both priorities, plus find_cover.py and the "already has a cover"
    skip-check just above) on the image's width/height query params — real covers
    are always requested at the portrait full-page-scan crop (width=1500,
    height~1959-1981, ratio ~0.756-0.766); ordinary og:image thumbnails are
    landscape (1200x630, ratio 1.9) and structurally cannot contain the masthead.
    This closes the specific false-positive that caused this incident regardless of
    why Priority 1 didn't fire. An archive-wide audit on 2026-08-23 found 3 more
    older issues with the same wrong crop shape (2024-08-23, 2024-09-13,
    2025-06-13) — left alone per Nadav's call, only 2026-08-21 was corrected (to
    the real shaar.jpg Nadav found). If Priority 1 keeps missing the widget on
    future runs, issues will land on "NO COVER FOUND" (safe) rather than a wrong
    guess — but that should be investigated (try refresh_cookies.py first), not
    assumed permanent.
  - Whatever find_cover.py/scraper.py produce should still be visually sanity-checked
    before it ships — see CLAUDE.md for the manual-fix checklist.
"""
import subprocess, shutil, os, sys, json, re, time
from datetime import datetime, timedelta
from scraper import is_portrait_cover_crop

ARCHIVE_DIR   = os.path.dirname(os.path.abspath(__file__))
DOCS_DIR      = os.path.join(ARCHIVE_DIR, "docs")
ISSUES_DIR    = os.path.join(ARCHIVE_DIR, "issues")
INDEX_PATH    = os.path.join(ARCHIVE_DIR, "index.json")
LOG_PATH      = os.path.join(ARCHIVE_DIR, "weekly_update.log")
COOKIES_PATH  = os.path.join(ARCHIVE_DIR, "haaretz_cookies.json")
PYTHON        = sys.executable
COOKIE_MAX_AGE_DAYS = 14  # the 2026-08-21 incident's cookies were 41 days old
NTFY_TOPIC = "haaretz-archive-b0a8f6d2a6a8"  # subscribe in the ntfy app to get alerts


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")


def notify_phone(message):
    """Push a real phone alert via ntfy.sh (free, no account, plain HTTPS POST) —
    works the same from a local run and from GitHub Actions, unlike the macOS
    osascript banner (local-only, easy to miss) or a log line nobody reads
    proactively. Never raises — a failed notification shouldn't fail the run."""
    try:
        import urllib.request
        req = urllib.request.Request(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=message.encode("utf-8"),
            headers={"Title": "Haaretz archive"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
        log(f"  → pushed phone notification: {message}")
    except Exception as e:
        log(f"  (couldn't push phone notification: {e})")


def check_cookie_health(probe_url=None):
    """Run on EVERY invocation (local cron and GitHub Actions alike) — always
    check, even though we can't always fix it unattended.

    Two independent checks, because either can be stale/wrong on its own:
      1. File age — the 2026-08-21 incident's haaretz_cookies.json (and the
         GH Actions HAARETZ_COOKIES secret, which is only ever set manually
         from this same file) were both 41 days old, well past when several
         session cookies had already expired.
      2. A live functional probe — fetch a real article page (needs an actual
         article URL, not a section landing page: those don't have a comments
         section so the marker below never appears there — pass one of this
         week's just-scraped article URLs) and look for the "Subscribe to
         join the conversation" paywall marker that indicates we're NOT
         authenticated as a full subscriber. This is what actually determines
         whether Priority 1's שער-widget scan can see anything; file age
         alone doesn't prove the session still works (or doesn't). If no
         probe_url is available yet, this check is skipped (age-only).

    Can't force an unattended interactive login here (refresh_cookies.py
    needs a human to actually type credentials in a headed browser — but as
    of 2026-08-23 it loads the existing cookies first, so launching it
    unattended is safe: worst case if nobody logs in is the same session
    saved back unchanged, never wiped to anonymous).
    So: log loudly always, and on a local machine (never in GitHub Actions,
    which has no display and no human) fire a macOS notification and launch
    refresh_cookies.py detached so it's sitting ready whenever Nadav is next
    at the keyboard.
    """
    if not os.path.exists(COOKIES_PATH):
        log("⚠️  COOKIE HEALTH: haaretz_cookies.json missing entirely.")
        _nudge_refresh("cookies file is missing")
        return

    age_days = (time.time() - os.path.getmtime(COOKIES_PATH)) / 86400
    stale_by_age = age_days > COOKIE_MAX_AGE_DAYS
    log(f"Cookie file age: {age_days:.1f} days "
        f"({'STALE' if stale_by_age else 'fresh enough'}, threshold {COOKIE_MAX_AGE_DAYS}d)")

    degraded = _probe_session_degraded(probe_url) if probe_url else None
    if degraded is None:
        log("Cookie live probe: skipped or failed to run — relying on age check only")
    else:
        log(f"Cookie live probe: {'DEGRADED (paywall marker seen)' if degraded else 'looks OK'}")

    if stale_by_age or degraded:
        reason = []
        if stale_by_age:
            reason.append(f"{age_days:.0f} days old")
        if degraded:
            reason.append("live probe shows paywall/anonymous markers")
        log(f"⚠️  COOKIE HEALTH: refresh recommended ({', '.join(reason)})")
        _nudge_refresh(", ".join(reason))


def _probe_session_degraded(probe_url):
    """Fetch a real article page and check for the paywall/subscribe marker
    seen in the 2026-08-21 investigation ('Subscribe to join the
    conversation' — the comments-paywall boilerplate shown to non-subscriber
    sessions). Returns True/False, or None if the probe itself failed."""
    try:
        from playwright.sync_api import sync_playwright
        cookies = json.load(open(COOKIES_PATH, encoding="utf-8"))
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context()
            ctx.add_cookies(cookies)
            page = ctx.new_page()
            page.goto(probe_url, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(2000)
            html = page.content()
            browser.close()
            return "Subscribe to join the conversation" in html
    except Exception as e:
        log(f"WARN cookie probe failed to run: {e}")
        return None


def _nudge_refresh(reason):
    """Purely informational now — login_haaretz.py (run at the top of main(),
    inside the persistent browser profile) is the real fix path and runs
    automatically every time, so there's nothing left to "nudge". This used
    to also auto-launch refresh_cookies.py in the background as a fallback,
    but that opens a brand-new, non-persistent browser identity — exactly
    the "new device every run" pattern that caused the 2026-09-01 device-
    quota lockout. Only log + notify now; if the persistent profile's own
    login is failing, that needs a look (see login_failure.png), not another
    ad-hoc login attempt."""
    notify_phone(f"Haaretz cookie probe degraded ({reason}) — check login_failure.png if logins keep failing.")
    if os.environ.get("GITHUB_ACTIONS"):
        log("  (running in GitHub Actions — informational only, no interactive fallback here)")
        return
    try:
        subprocess.run([
            "osascript", "-e",
            f'display notification "Reason: {reason}." '
            f'with title "Haaretz cookie probe degraded"'
        ], check=False)
    except Exception as e:
        log(f"  (couldn't send macOS notification: {e})")


def main():
    # Last Friday = most recent Friday before today
    today = datetime.now().date()
    days_since_friday = (today.weekday() - 4) % 7 or 7   # weekday(): Mon=0 … Sun=6
    last_friday = today - timedelta(days=days_since_friday)
    mag_date = last_friday.strftime("%Y-%m-%d")
    yyyymm   = last_friday.strftime("%Y%m")

    log(f"=== Weekly update starting — target date: {mag_date} ===")

    # 0. Log in fresh every run (local Keychain or GH Actions secrets) — no
    # human click needed. Falls back to whatever cookies already exist if
    # this fails, so it's never worse than before.
    try:
        from login_haaretz import login_and_save_cookies
        if not login_and_save_cookies():
            log("WARN: automated login failed — continuing with existing cookies")
            notify_phone("Haaretz automated login failed this run — check login_failure.png")
    except Exception as e:
        log(f"WARN: automated login step crashed: {e}")

    # 1. Scrape the month (discovers new issue, preserves existing ones)
    log(f"Scraping {yyyymm}...")
    r = subprocess.run(
        [PYTHON, "scraper.py", yyyymm, "--fetch-titles"],
        cwd=ARCHIVE_DIR, capture_output=True, text=True
    )
    log(r.stdout.strip() or "(no output)")
    if r.returncode != 0:
        log(f"ERROR in scraper: {r.stderr.strip()}")

    # 1b. Cookie health check — now that we (hopefully) have this week's
    # articles, probe with a real one instead of a section landing page.
    issue_path = os.path.join(ISSUES_DIR, f"{mag_date}.json")
    probe_url = None
    if os.path.exists(issue_path):
        try:
            _issue = json.load(open(issue_path, encoding="utf-8"))
            _main_articles = _issue.get("sections", {}).get("magazine", {}).get("articles", [])
            if _main_articles:
                probe_url = _main_articles[0]["url"]
        except Exception:
            pass
    check_cookie_health(probe_url)

    # 2. Find/update cover for the new issue — skip if already has a shaar/frontpage cover
    if os.path.exists(issue_path):
        existing_cover = json.load(open(issue_path)).get("cover_image") or ""
        fname = existing_cover.split('/')[-1].split('?')[0].lower()
        # Filename alone is NOT enough (see 2026-08-21 incident: a wrong
        # og:image cover kept its date-pattern filename but was a landscape
        # article thumbnail, not the cover). Require the portrait crop shape too.
        has_good_cover = bool(existing_cover) and is_portrait_cover_crop(existing_cover)
        if has_good_cover:
            log(f"Cover already set ({fname}) — skipping find_cover.py")
        else:
            log(f"Finding cover for {mag_date}...")
            r = subprocess.run(
                [PYTHON, "find_cover.py", mag_date],
                cwd=ARCHIVE_DIR, capture_output=True, text=True
            )
            log(r.stdout.strip() or "(no output)")
            if r.returncode != 0:
                log(f"WARN cover finder: {r.stderr.strip()}")
            final_cover = json.load(open(issue_path)).get("cover_image") or ""
            if not final_cover:
                notify_phone(
                    f"{mag_date} magazine cover still missing — site is showing the "
                    f"generic placeholder. Needs a manual fix (see CLAUDE.md)."
                )
    else:
        log(f"WARN: {mag_date}.json not found — magazine may not exist yet")

    # 3. Sync data into docs/ for GitHub Pages
    log("Syncing docs/...")
    shutil.copy2(INDEX_PATH, os.path.join(DOCS_DIR, "index.json"))
    shutil.copytree(ISSUES_DIR, os.path.join(DOCS_DIR, "issues"), dirs_exist_ok=True)

    # 4. Commit and push
    log("Committing and pushing...")
    subprocess.run(["git", "add", "docs/", "issues/", "index.json"],
                   cwd=ARCHIVE_DIR, check=True)
    result = subprocess.run(
        ["git", "commit", "-m", f"Add magazine {mag_date}"],
        cwd=ARCHIVE_DIR, capture_output=True, text=True
    )
    if result.returncode == 0:
        push_with_retry(mag_date)
    else:
        log("Nothing new to commit (already up to date)")

    log("=== Done ===\n")


def push_with_retry(mag_date):
    """git push, and if it's rejected (remote has commits we don't — e.g. the
    2026-08-21 incident, where the local launchd cron and the GitHub Actions
    workflow both run this exact script at ~10:00 and can race each other),
    fetch + merge once and retry instead of crashing.

    Previously this was a bare `subprocess.run(["git","push"], check=True)`,
    which raised an uncaught CalledProcessError on a rejected push — silently
    killing the whole run with no further log line (confirmed in
    weekly_update.log: both the 2026-08-16 and 2026-08-23 runs stop dead
    right after 'Committing and pushing...', no 'Pushed' or '=== Done ==='
    line after it — that's this bug, not a coincidence)."""
    push = subprocess.run(["git", "push"], cwd=ARCHIVE_DIR, capture_output=True, text=True)
    if push.returncode == 0:
        log(f"Pushed: {mag_date}")
        return

    log(f"Push rejected ({push.stderr.strip()[:200]}) — fetching + merging once and retrying")
    subprocess.run(["git", "fetch", "origin"], cwd=ARCHIVE_DIR, capture_output=True, text=True)
    merge = subprocess.run(
        ["git", "merge", "origin/main", "-m", f"Merge origin/main into weekly update ({mag_date})"],
        cwd=ARCHIVE_DIR, capture_output=True, text=True
    )
    if merge.returncode != 0:
        log(f"⚠️  MERGE CONFLICT while retrying push for {mag_date} — needs manual "
            f"resolution (git status / git diff in {ARCHIVE_DIR}). Not retrying further.")
        return

    retry = subprocess.run(["git", "push"], cwd=ARCHIVE_DIR, capture_output=True, text=True)
    if retry.returncode == 0:
        log(f"Pushed: {mag_date} (after merge retry)")
    else:
        log(f"⚠️  Push still failing after merge retry: {retry.stderr.strip()[:200]}")


if __name__ == "__main__":
    main()

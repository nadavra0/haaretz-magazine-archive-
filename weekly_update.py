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
import subprocess, shutil, os, sys, json, re
from datetime import datetime, timedelta
from scraper import is_portrait_cover_crop

ARCHIVE_DIR = os.path.dirname(os.path.abspath(__file__))
DOCS_DIR    = os.path.join(ARCHIVE_DIR, "docs")
ISSUES_DIR  = os.path.join(ARCHIVE_DIR, "issues")
INDEX_PATH  = os.path.join(ARCHIVE_DIR, "index.json")
LOG_PATH    = os.path.join(ARCHIVE_DIR, "weekly_update.log")
PYTHON      = sys.executable


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")


def main():
    # Last Friday = most recent Friday before today
    today = datetime.now().date()
    days_since_friday = (today.weekday() - 4) % 7 or 7   # weekday(): Mon=0 … Sun=6
    last_friday = today - timedelta(days=days_since_friday)
    mag_date = last_friday.strftime("%Y-%m-%d")
    yyyymm   = last_friday.strftime("%Y%m")

    log(f"=== Weekly update starting — target date: {mag_date} ===")

    # 1. Scrape the month (discovers new issue, preserves existing ones)
    log(f"Scraping {yyyymm}...")
    r = subprocess.run(
        [PYTHON, "scraper.py", yyyymm, "--fetch-titles"],
        cwd=ARCHIVE_DIR, capture_output=True, text=True
    )
    log(r.stdout.strip() or "(no output)")
    if r.returncode != 0:
        log(f"ERROR in scraper: {r.stderr.strip()}")

    # 2. Find/update cover for the new issue — skip if already has a shaar/frontpage cover
    issue_path = os.path.join(ISSUES_DIR, f"{mag_date}.json")
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
        subprocess.run(["git", "push"], cwd=ARCHIVE_DIR, check=True)
        log(f"Pushed: {mag_date}")
    else:
        log("Nothing new to commit (already up to date)")

    log("=== Done ===\n")


if __name__ == "__main__":
    main()

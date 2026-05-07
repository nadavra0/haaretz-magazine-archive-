#!/usr/bin/env python3
"""
Weekly magazine updater — runs every Sunday at 10:00.
Scrapes last Friday's magazine, finds its cover, updates docs/, commits and pushes.

How article fetching works:
  - scraper.py fetches sitemap-YYYYMM.xml from Haaretz to discover all magazine articles
  - Each article URL is fetched (with Playwright + saved cookies for paywall bypass)
  - Metadata: title, og:image, section are extracted from HTML
  - Articles grouped by section, saved to issues/YYYY-MM-DD.json

How cover detection works:
  - Priority 1 (Playwright): looks for <img alt="שר מוסף..."> or <img alt="שר"> with
    a cover filename (shaar*, mu\d+, frontpage*), or any img whose filename matches
    the date pattern DD-M-YY-web / DD-M-YY-animation — date-validated to avoid
    sidebar false-positives from other issues' covers bleeding in.
  - Priority 2: og:image whose filename matches the date pattern
  - Existing cover is NEVER overwritten unless a Priority-1 shaar_image is found
"""
import subprocess, shutil, os, sys
from datetime import datetime, timedelta

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

    # 2. Find/update cover for the new issue
    issue_path = os.path.join(ISSUES_DIR, f"{mag_date}.json")
    if os.path.exists(issue_path):
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

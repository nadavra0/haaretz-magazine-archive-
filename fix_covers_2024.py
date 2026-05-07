#!/usr/bin/env python3
"""Fix covers for all 2023-2024 issues using Playwright."""
import json, os, re
from playwright.sync_api import sync_playwright

ARCHIVE_DIR = os.path.dirname(os.path.abspath(__file__))
ISSUES_DIR = os.path.join(ARCHIVE_DIR, "issues")
INDEX_PATH = os.path.join(ARCHIVE_DIR, "index.json")
COOKIES_FILE = os.path.join(ARCHIVE_DIR, "haaretz_cookies.json")


def is_cover_filename(url):
    fname = url.split('/')[-1].split('?')[0].lower()
    return ('shaar' in fname or bool(re.match(r'mu\d+', fname))
            or '-web.' in fname or '-animation.' in fname)


def find_cover(page, url):
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=25000)
        page.wait_for_timeout(3000)
        for img in page.query_selector_all("img"):
            alt = img.get_attribute("alt") or ""
            src = img.get_attribute("src") or ""
            if "שער" in alt and ("שער מוסף" in alt or is_cover_filename(src)):
                srcset = img.get_attribute("srcset") or ""
                best = src
                if srcset:
                    entries = re.findall(r"(https?://\S+?)\s+(\d+)w", srcset)
                    if entries:
                        entries.sort(key=lambda x: int(x[1]), reverse=True)
                        best = entries[0][0].rstrip(",")
                if best:
                    return best
    except Exception as e:
        print(f"    error: {e}")
    return None


def main():
    cookies = json.load(open(COOKIES_FILE))
    dates = sorted([f[:-5] for f in os.listdir(ISSUES_DIR)
                    if f.endswith('.json') and f[:4] in ('2023', '2024')])
    print(f"Processing {len(dates)} issues...")

    with open(INDEX_PATH) as f:
        idx = json.load(f)
    idx_by_date = {e["magazine_date"]: e for e in idx["issues"]}

    found_count = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        ctx.add_cookies(cookies)

        for mag_date in dates:
            issue_path = os.path.join(ISSUES_DIR, f"{mag_date}.json")
            issue = json.load(open(issue_path))
            secs = issue.get("sections", {})

            # Check main section first, then others
            main_arts = secs.get("magazine", {}).get("articles", [])
            other_arts = [a for k, v in secs.items() if k != "magazine"
                          for a in v.get("articles", [])]
            all_arts = main_arts + other_arts

            cover_url = None
            cover_article = None
            for art in all_arts:
                page = ctx.new_page()
                result = find_cover(page, art["url"])
                page.close()
                if result:
                    cover_url = result
                    cover_article = art["url"]
                    break

            if cover_url:
                issue["cover_image"] = cover_url
                issue["cover_article_url"] = cover_article
                with open(issue_path, "w") as f:
                    json.dump(issue, f, ensure_ascii=False, indent=2)
                if mag_date in idx_by_date:
                    idx_by_date[mag_date]["cover_image"] = cover_url
                print(f"  ✓ {mag_date}: {cover_url.split('/')[-1].split('?')[0]}")
                found_count += 1
            else:
                print(f"  – {mag_date}: no cover found")

        browser.close()

    # Save updated index
    with open(INDEX_PATH, "w") as f:
        json.dump(idx, f, ensure_ascii=False, indent=2)
    print(f"\nDone: {found_count}/{len(dates)} covers found.")


if __name__ == "__main__":
    main()

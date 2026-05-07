#!/usr/bin/env python3
"""Find and patch cover for one magazine date. Usage: python find_cover.py 2024-01-05"""
import sys, json, re, os
from datetime import datetime
from playwright.sync_api import sync_playwright

ISSUES_DIR = os.path.join(os.path.dirname(__file__), "issues")
INDEX_PATH = os.path.join(os.path.dirname(__file__), "index.json")
COOKIES_FILE = os.path.join(os.path.dirname(__file__), "haaretz_cookies.json")

def is_cover_filename(url, mag_date=None):
    """Check if image filename looks like a magazine cover.
    For date-pattern covers (D-M-YY-web), validate against mag_date to avoid
    cross-issue false positives from sidebars showing other issues' covers."""
    fname = url.split('/')[-1].split('?')[0].lower()
    # shaar/mu prefix — always a cover
    if 'shaar' in fname or bool(re.match(r'mu\d+', fname)):
        return True
    # frontpage — always a cover
    if fname.startswith('frontpage') or fname.startswith('frontpgae'):
        return True
    # Date-pattern covers: only accept if they match THIS issue's date
    if mag_date and ('-web.' in fname or '-animation.' in fname):
        d = datetime.fromisoformat(mag_date).date()
        year2 = str(d.year)[2:]
        patterns = [
            f"{d.day}-{d.month}-{year2}-web",
            f"{d.day:02d}-{d.month:02d}-{year2}-web",
            f"{d.day}-{d.month}-{year2}-animation",
            f"{d.day:02d}-{d.month:02d}-{year2}-animation",
        ]
        return any(p in fname for p in patterns)
    return False

mag_date = sys.argv[1]
issue = json.load(open(f"{ISSUES_DIR}/{mag_date}.json"))
secs = issue.get("sections", {})
main_arts = secs.get("magazine", {}).get("articles", [])
other_arts = [a for k,v in secs.items() if k != "magazine" for a in v.get("articles",[])]
cookies = json.load(open(COOKIES_FILE))

cover_url = None
cover_article = None
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context()
    ctx.add_cookies(cookies)
    for art in main_arts + other_arts:
        page = ctx.new_page()
        try:
            page.goto(art["url"], wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(3000)
            for img in page.query_selector_all("img"):
                alt = img.get_attribute("alt") or ""
                src = img.get_attribute("src") or ""
                if ("שער" in alt and ("שער מוסף" in alt or is_cover_filename(src, mag_date))) \
                        or is_cover_filename(src, mag_date):
                    srcset = img.get_attribute("srcset") or ""
                    best = src
                    if srcset:
                        entries = re.findall(r"(https?://\S+?)\s+(\d+)w", srcset)
                        if entries:
                            entries.sort(key=lambda x: int(x[1]), reverse=True)
                            best = entries[0][0].rstrip(",")
                    cover_url = best
                    cover_article = art["url"]
                    break
        except: pass
        page.close()
        if cover_url: break
    browser.close()

if cover_url:
    issue["cover_image"] = cover_url
    issue["cover_article_url"] = cover_article
    json.dump(issue, open(f"{ISSUES_DIR}/{mag_date}.json","w"), ensure_ascii=False, indent=2)
    idx = json.load(open(INDEX_PATH))
    for e in idx["issues"]:
        if e["magazine_date"] == mag_date:
            e["cover_image"] = cover_url
    json.dump(idx, open(INDEX_PATH,"w"), ensure_ascii=False, indent=2)
    print(f"✓ {mag_date}: {cover_url.split('/')[-1].split('?')[0]}")
else:
    print(f"– {mag_date}: no cover found")

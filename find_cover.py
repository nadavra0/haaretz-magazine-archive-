#!/usr/bin/env python3
"""Find and patch cover for one magazine date. Usage: python find_cover.py 2024-01-05"""
import sys, json, re, os
from datetime import datetime
from playwright.sync_api import sync_playwright

ISSUES_DIR = os.path.join(os.path.dirname(__file__), "issues")
INDEX_PATH = os.path.join(os.path.dirname(__file__), "index.json")
COOKIES_FILE = os.path.join(os.path.dirname(__file__), "haaretz_cookies.json")

def is_portrait_cover_crop(url):
    """Gate on crop shape, not just filename/alt text. Real Haaretz covers are
    requested at width=1500 & height~1959-1981 (portrait, ratio ~0.756-0.766) —
    the actual scanned front page including masthead + date. Ordinary og:image
    thumbnails are width=1200&height=630 (landscape, ratio 1.9) and can never
    contain the masthead, no matter how plausible the filename/alt looks. See
    scraper.py's is_portrait_cover_crop() for the archive-wide audit that
    established these numbers (2026-08-23)."""
    if not url:
        return False
    m = re.search(r'width=(\d+)&height=(\d+)', url)
    if not m:
        return False
    width, height = int(m.group(1)), int(m.group(2))
    if width <= 0 or height <= width:
        return False
    ratio = width / height
    return 0.70 <= ratio <= 0.80


def alt_date_conflicts(alt, mag_date):
    """True if alt text explicitly cites a day.month different from mag_date.
    Catches inline in-article references to a past cover (e.g. an article
    recalling 'שער מוסף הארץ מ-5.12...') which are not this issue's own cover."""
    d = datetime.fromisoformat(mag_date).date()
    for day, month in re.findall(r'(\d{1,2})[.\-](\d{1,2})(?!\d)', alt):
        if (int(day), int(month)) != (d.day, d.month):
            return True
    return False

def is_strict_cover_filename(url):
    """Filename markers that are exclusively used for real Haaretz magazine
    covers (shaar*, mu\\d+, frontpage*) — safe to trust on their own, with no
    date check and no dependence on alt text."""
    if not url:
        return False
    fname = url.split('/')[-1].split('?')[0].lower()
    return (
        'shaar' in fname or
        bool(re.match(r'mu\d+', fname)) or
        fname.startswith('frontpage') or
        fname.startswith('frontpgae')
    )

def is_cover_filename(url, mag_date=None):
    """Check if image filename looks like a magazine cover.
    For date-pattern covers (D-M-YY-web), validate against mag_date to avoid
    cross-issue false positives from sidebars showing other issues' covers.
    NOTE: date-pattern filenames are a WEAK signal on their own — Haaretz uses
    the same '-web.'/'-animation.' suffix on ordinary same-day photos too, not
    just covers. Callers must pair this with a strict alt-text check (exact
    bare "שער" label, not just a substring) — see find_cover.py's main loop
    and the 2026-08-14 incident this guards against."""
    if not url:
        return False
    fname = url.split('/')[-1].split('?')[0].lower()
    if is_strict_cover_filename(url):
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
                # Accept only: (a) alt explicitly says "שער מוסף", or
                # (b) filename alone is an unambiguous cover asset (shaar/mu/frontpage),
                # or (c) alt is the *exact* bare label "שער" (not just a substring
                # inside some unrelated caption) paired with a date-matched filename.
                # A bare "שער" substring inside a longer caption used to be enough
                # together with any date-matched filename — that's what let a
                # comic-strip illustration get picked up as the 2026-08-14 cover.
                is_explicit = "שער מוסף" in alt
                is_strict_filename = is_strict_cover_filename(src)
                is_bare_label = alt.strip() == "שער" and is_cover_filename(src, mag_date)
                if is_explicit or is_strict_filename or is_bare_label:
                    if alt_date_conflicts(alt, mag_date):
                        continue
                    srcset = img.get_attribute("srcset") or ""
                    best = src
                    if srcset:
                        entries = re.findall(r"(https?://\S+?)\s+(\d+)w", srcset)
                        if entries:
                            entries.sort(key=lambda x: int(x[1]), reverse=True)
                            best = entries[0][0].rstrip(",")
                    if not is_portrait_cover_crop(best):
                        continue
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

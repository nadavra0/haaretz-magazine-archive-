#!/usr/bin/env python3
"""
Haaretz Magazine Archive Scraper
Reads Haaretz sitemaps and builds a JSON archive organized by magazine issue.

Usage:
    python scraper.py                    # fetch current + previous month
    python scraper.py 202604 202605      # specify months
    python scraper.py --fetch-titles     # also scrape article titles (slower)
"""

import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, date
from collections import defaultdict
import difflib
import html
import json
import re
import os
import sys
import time

BASE_URL = "https://www.haaretz.co.il"
ARCHIVE_DIR = os.path.dirname(os.path.abspath(__file__))

# All known magazine sections: URL-path-key → Hebrew display name
MAGAZINE_SECTIONS = {
    "magazine":                     "כתבות ראשיות",
    "magazine/the-edge/mehasafa":   "הקצה – מהשפה",
    "magazine/the-edge":            "הקצה",
    "magazine/20questions-kids":    "20 שאלות לילדים",
    "magazine/20questions":         "20 שאלות",
    "magazine/blacklist":           "רשימה שחורה",
    "magazine/ratingcommittee":     "ועדת המדרוג",
    "magazine/on-the-line":         "על הקו",
    "magazine/quote":               "לא לציטוט",
    "magazine/underthesun":         "תחת השמש",
    "magazine/letters":             "מכתבים",
    "magazine/flights":             "טיסות נכנסות ויוצאות",
    "magazine/panim":               "ענייני פנים",
    "magazine/ayelet-shani":        "איילת שני",
    "magazine/haaretzlogicpuzzle":  "תשבץ",
    "magazine/chess":               "שחמט",
    "magazine/famous":              "המפורסם",
    "magazine/obit":                "נספד",
    "magazine/photosynthesis":      "פוטוסינתזה",
    "magazine/pinatlituf":          "פינת ליטוף",
    "food/dining":                  "מסעדות",
}

# Display order for sections in the UI
SECTION_ORDER = [
    "magazine",
    "magazine/the-edge",
    "magazine/the-edge/mehasafa",
    "magazine/underthesun",
    "magazine/panim",
    "magazine/flights",
    "magazine/ayelet-shani",
    "magazine/blacklist",
    "magazine/ratingcommittee",
    "magazine/on-the-line",
    "magazine/quote",
    "magazine/20questions",
    "magazine/20questions-kids",
    "food/dining",
    "magazine/haaretzlogicpuzzle",
    "magazine/chess",
    "magazine/famous",
    "magazine/obit",
    "magazine/photosynthesis",
    "magazine/pinatlituf",
    "magazine/letters",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
}


def get_magazine_friday(article_date):
    """
    Return the Friday (magazine publication date) of the week containing article_date.
    Israeli week: Sunday = start of week, Friday = magazine day.
    Articles appear Sunday through Friday of that week.
    Saturday articles are treated as belonging to the *next* week's magazine.
    """
    wd = article_date.weekday()  # Monday=0 ... Sunday=6
    if wd == 6:    # Sunday → Friday is 5 days away
        return article_date + timedelta(days=5)
    elif wd == 5:  # Saturday → belongs to next week's magazine
        return article_date + timedelta(days=6)
    else:          # Mon(0)..Fri(4) → days remaining until Friday
        return article_date + timedelta(days=4 - wd)


def get_section(url):
    """
    Match a URL to a known magazine section key.
    Sorted by descending length so longer (more specific) paths match first.
    """
    path = url.replace(BASE_URL, "").lstrip("/")
    for section in sorted(MAGAZINE_SECTIONS, key=len, reverse=True):
        if path.startswith(section + "/"):
            return section
    return None


def extract_date_from_url(url):
    m = re.search(r"/(\d{4}-\d{2}-\d{2})/", url)
    if m:
        return datetime.strptime(m.group(1), "%Y-%m-%d").date()
    return None


def fetch_sitemap(ym):
    """Fetch and parse a monthly sitemap, return list of URL strings."""
    url = f"{BASE_URL}/sitemap-{ym}.xml"
    print(f"  Fetching {url} ...", end=" ", flush=True)
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
    except requests.RequestException as e:
        print(f"ERROR: {e}")
        return []
    if r.status_code != 200:
        print(f"HTTP {r.status_code}")
        return []
    root = ET.fromstring(r.content)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locs = [u.find("sm:loc", ns).text.strip()
            for u in root.findall("sm:url", ns)
            if u.find("sm:loc", ns) is not None]
    print(f"{len(locs):,} URLs")
    return locs


def fetch_metadata(url):
    """Fetch og:title, og:image, and the real magazine cover from an article page.
    Returns (title, og_image, shaar_image).
    shaar_image is extracted from <img alt="שער מוסף..."> — the actual front-page scan."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return None, None, None
        text = r.text
        # og:title
        m = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\'](.*?)["\']', text)
        if not m:
            m = re.search(r'<meta[^>]+content=["\'](.*?)["\'][^>]+property=["\']og:title["\']', text)
        title = html.unescape(m.group(1).strip()) if m else None
        if not title:
            m2 = re.search(r'<h1[^>]*>(.*?)</h1>', text, re.DOTALL)
            if m2:
                title = html.unescape(re.sub(r'<[^>]+>', '', m2.group(1)).strip())
        # og:image
        mi = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\'](.*?)["\']', text)
        if not mi:
            mi = re.search(r'<meta[^>]+content=["\'](https?://[^"\']+)["\'][^>]+property=["\']og:image["\']', text)
        image = html.unescape(mi.group(1).strip()) if mi else None
        # Real magazine front-page cover: <img alt="שער מוסף הארץ ...">
        # Cover alt patterns seen across issues:
        #   "שר מוסף הארץ 9.5"   – explicit cover tag
        #   "שר"                  – simple label, filename must be cover-like
        #   "בשר: אלונה מרגולין…" – caption style, filename must be cover-like
        shaar_image = None
        for ms in re.finditer(r'<img\b[^>]+alt=["\'][^"\']*שער[^"\']*["\'][^>]*>', text, re.DOTALL):
            img_tag = ms.group(0)
            alt_m = re.search(r'\balt=["\']([^"\']*)["\']', img_tag)
            candidate_alt = html.unescape(alt_m.group(1)) if alt_m else ""
            src_m = re.search(r'\bsrc=["\']([^"\']+)["\']', img_tag)
            candidate_src = html.unescape(src_m.group(1)) if src_m else ""
            # Require cover filename unless alt explicitly says "שר מוסף"
            if "שער מוסף" not in candidate_alt and not is_cover_filename(candidate_src):
                continue
            # Extract largest from srcset if available
            srcset_m = re.search(r'\bsrcset=["\']([^"\']+)["\']', img_tag)
            if srcset_m:
                srcset_raw = html.unescape(srcset_m.group(1))
                entries = re.findall(r'(https?://\S+?)\s+(\d+)w', srcset_raw)
                if entries:
                    entries.sort(key=lambda x: int(x[1]), reverse=True)
                    shaar_image = entries[0][0].rstrip(',').rstrip('&')
            if not shaar_image and candidate_src:
                shaar_image = candidate_src
            if shaar_image:
                break
        return title, image, shaar_image
    except Exception:
        return None, None, None


def is_cover_filename(image_url):
    """Check if an image URL filename looks like a Haaretz magazine cover.
    Cover images are named: shaar.jpg, shaar-N.jpg, mu1.jfif, mu2.jfif, etc.
    This is used to validate alt='שר' (exact) matches — distinguishing the
    real in-article cover from the sidebar widget (which has a numeric filename)."""
    if not image_url:
        return False
    filename = image_url.split('/')[-1].split('?')[0].lower()
    return (
        'shaar' in filename or
        bool(re.match(r'mu\d+', filename)) or
        '-web.' in filename or
        '-animation.' in filename
    )


def is_cover_image(image_url, magazine_date):
    """Check whether an og:image filename matches the magazine cover pattern.
    Haaretz names cover images like '1-5-26-web.jpg' (D-M-YY-web)
    or '1-5-26-animation.gif' (animated covers)."""
    if not image_url:
        return False
    d = datetime.fromisoformat(magazine_date).date()
    year2 = str(d.year)[2:]
    filename = image_url.split('/')[-1]
    patterns = [
        f"{d.day}-{d.month}-{year2}-web",
        f"{d.day:02d}-{d.month:02d}-{year2}-web",
        f"{d.day}-{d.month}-{year2}-animation",
        f"{d.day:02d}-{d.month:02d}-{year2}-animation",
    ]
    return any(p in filename for p in patterns)


def load_existing_titles():
    """Load previously fetched title + og_image from existing JSON files, keyed by URL."""
    cache = {}  # url -> {title, og_image}
    issues_dir = os.path.join(ARCHIVE_DIR, "issues")
    if not os.path.isdir(issues_dir):
        return cache
    for fname in os.listdir(issues_dir):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(issues_dir, fname), encoding="utf-8") as f:
                issue = json.load(f)
            for section in issue.get("sections", {}).values():
                for article in section.get("articles", []):
                    if article.get("url"):
                        cache[article["url"]] = {
                            "title": article.get("title"),
                            "og_image": article.get("og_image"),
                            "shaar_image": article.get("shaar_image"),
                            # True only if shaar_image was explicitly stored (even as null)
                            "_shaar_checked": "shaar_image" in article,
                        }
        except Exception:
            pass
    return cache


def load_existing_issue_titles():
    """Load (url, title) pairs from every issue already on disk, grouped by magazine_date.
    Used to catch re-published articles (same story, new URL/date) that would
    otherwise land in the wrong issue — see normalize_title / titles_match."""
    by_date = defaultdict(list)
    issues_dir = os.path.join(ARCHIVE_DIR, "issues")
    if not os.path.isdir(issues_dir):
        return by_date
    for fname in os.listdir(issues_dir):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(issues_dir, fname), encoding="utf-8") as f:
                issue = json.load(f)
            magazine_date = issue.get("magazine_date")
            for section in issue.get("sections", {}).values():
                for article in section.get("articles", []):
                    if article.get("url") and article.get("title"):
                        by_date[magazine_date].append((article["url"], article["title"]))
        except Exception:
            pass
    return by_date


def normalize_title(title):
    """Strip punctuation and generic editorial labels so re-published articles
    (same story, reworded/relabeled) compare equal. E.g. Haaretz sometimes
    re-surfaces an old investigative piece with a "תחקיר" (investigation) label
    moved from prefix to suffix, or with/without a quoted "הארץ" byline."""
    if not title:
        return ""
    t = re.sub(r'["\'׳״:.,‘’“”?]', ' ', title)
    t = re.sub(r'\bתחקיר\b|\bהארץ\b|\bבלעדי\b', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def titles_match(title_a, title_b, threshold=0.9):
    na, nb = normalize_title(title_a), normalize_title(title_b)
    if not na or not nb:
        return False
    return difflib.SequenceMatcher(None, na, nb).ratio() >= threshold


def drop_cross_issue_duplicates(all_articles):
    """Haaretz occasionally re-surfaces an already-published article under a new
    URL with a later date (e.g. a re-highlighted investigative piece), which
    get_magazine_friday() then buckets into the *following* week's issue even
    though the story already ran in an earlier issue. Detect same-story
    duplicates one week apart by title similarity and drop the later copy,
    keeping the one in the issue it actually belongs to."""
    by_date = defaultdict(list)
    for a in all_articles:
        by_date[a["magazine_date"]].append(a)
    existing_by_date = load_existing_issue_titles()

    keep = []
    for a in all_articles:
        mag_date = date.fromisoformat(a["magazine_date"])
        prev_date = (mag_date - timedelta(days=7)).isoformat()
        prev_candidates = [(x["url"], x["title"]) for x in by_date.get(prev_date, [])]
        prev_candidates += existing_by_date.get(prev_date, [])
        duplicate_of = next(
            (url for url, title in prev_candidates
             if url != a["url"] and titles_match(a.get("title"), title)),
            None,
        )
        if duplicate_of:
            print(f"  ⚠ Dropping {a['magazine_date']} duplicate of {prev_date} article "
                  f"({duplicate_of[-40:]}): {a['title']!r}")
            continue
        keep.append(a)
    return keep


def build_archive(year_months, fetch_titles=False):
    # Preserve titles from previous runs so a re-scrape doesn't lose them
    existing_titles = load_existing_titles()
    if existing_titles:
        print(f"  Loaded {len(existing_titles)} cached metadata entries")

    all_articles = []
    for ym in year_months:
        urls = fetch_sitemap(ym)
        count = 0
        for url in urls:
            section = get_section(url)
            if not section:
                continue
            article_date = extract_date_from_url(url)
            if not article_date:
                continue
            cached = existing_titles.get(url, {})
            all_articles.append({
                "url": url,
                "section": section,
                "section_name": MAGAZINE_SECTIONS[section],
                "article_date": article_date.isoformat(),
                "magazine_date": get_magazine_friday(article_date).isoformat(),
                "title": cached.get("title"),
                "og_image": cached.get("og_image"),
                "shaar_image": cached.get("shaar_image"),
                "_shaar_checked": cached.get("_shaar_checked", False),
            })
            count += 1
        print(f"    → {count} magazine articles")

    # Deduplicate by URL
    seen = set()
    unique = []
    for a in all_articles:
        if a["url"] not in seen:
            seen.add(a["url"])
            unique.append(a)
    all_articles = unique
    print(f"\n  Total unique magazine articles: {len(all_articles)}")

    if fetch_titles:
        print(f"  Fetching metadata (title + cover images)...")
        for i, article in enumerate(all_articles, 1):
            # Skip if title, og_image, AND shaar_image have all been fetched before
            if (article.get("title") and article.get("og_image") is not None
                    and article.get("_shaar_checked", False)):
                continue
            print(f"    [{i}/{len(all_articles)}] {article['url'][-60:]}", end="\r")
            title, og_image, shaar_image = fetch_metadata(article["url"])
            if title:
                article["title"] = title
            article["og_image"] = og_image
            article["shaar_image"] = shaar_image
            article["_shaar_checked"] = True
            time.sleep(0.35)
        print()
    else:
        for article in all_articles:
            if "og_image" not in article:
                article["og_image"] = None
            if "shaar_image" not in article:
                article["shaar_image"] = None

    # Drop re-published articles that already ran in the previous week's issue
    # (see drop_cross_issue_duplicates) — requires titles, so only meaningful
    # when fetch_titles=True or titles were already cached from a prior run.
    all_articles = drop_cross_issue_duplicates(all_articles)

    # Group by magazine issue date
    by_issue = defaultdict(list)
    for a in all_articles:
        by_issue[a["magazine_date"]].append(a)

    return by_issue


def save_archive(by_issue):
    issues_dir = os.path.join(ARCHIVE_DIR, "issues")
    os.makedirs(issues_dir, exist_ok=True)

    # Collect existing issue files that aren't being re-scraped
    existing_index = {}
    existing_index_path = os.path.join(ARCHIVE_DIR, "index.json")
    if os.path.exists(existing_index_path):
        with open(existing_index_path, encoding="utf-8") as f:
            old = json.load(f)
        for entry in old.get("issues", []):
            existing_index[entry["magazine_date"]] = entry

    index_entries = []
    for magazine_date in sorted(by_issue.keys(), reverse=True):
        articles = by_issue[magazine_date]

        # Group by section
        by_section = defaultdict(list)
        for a in articles:
            by_section[a["section"]].append(a)

        # Build sections in display order
        ordered_sections = {}
        for key in SECTION_ORDER:
            if key in by_section:
                ordered_sections[key] = {
                    "name": MAGAZINE_SECTIONS[key],
                    "articles": sorted(by_section[key], key=lambda x: x["article_date"])
                }
        # Append any unknown sections at the end
        for key in by_section:
            if key not in ordered_sections:
                ordered_sections[key] = {
                    "name": MAGAZINE_SECTIONS.get(key, key),
                    "articles": sorted(by_section[key], key=lambda x: x["article_date"])
                }

        # Preserve an existing cover if it was previously set (e.g. by --fetch-covers).
        # Only recalculate if no cover exists yet.
        existing_issue_path = os.path.join(issues_dir, f"{magazine_date}.json")
        existing_cover = None
        existing_cover_article = None
        if os.path.exists(existing_issue_path):
            try:
                with open(existing_issue_path, encoding="utf-8") as _f:
                    _old = json.load(_f)
                existing_cover = _old.get("cover_image")
                existing_cover_article = _old.get("cover_article_url")
            except Exception:
                pass

        # Find cover image: priority 1 — <img alt="שער מוסף..."> tag in any article
        cover_image = None
        cover_article_url = None
        for a in articles:
            if a.get("shaar_image"):
                cover_image = a["shaar_image"]
                cover_article_url = a["url"]
                break
        # Priority 2 — og_image filename matching D-M-YY-web pattern
        if not cover_image:
            for a in articles:
                if is_cover_image(a.get("og_image"), magazine_date):
                    cover_image = a["og_image"]
                    cover_article_url = a["url"]
                    break
        # Priority 3 — og_image of first main article
        if not cover_image:
            for a in articles:
                if a["section"] == "magazine" and a.get("og_image"):
                    cover_image = a["og_image"]
                    cover_article_url = a["url"]
                    break

        # Never downgrade an existing cover.
        # Only replace it if we found a Priority 1 shaar_image directly in an article body.
        # Preserve covers set by --fetch-covers / Playwright / manual patching.
        found_via_shaar = any(a.get("shaar_image") for a in articles)
        if existing_cover and not found_via_shaar:
            cover_image = existing_cover
            cover_article_url = existing_cover_article

        # Strip internal flag before writing to JSON
        clean_articles = [{k: v for k, v in a.items() if k != "_shaar_checked"}
                          for a in articles]
        for sec_data in ordered_sections.values():
            sec_data["articles"] = [{k: v for k, v in a.items() if k != "_shaar_checked"}
                                     for a in sec_data["articles"]]

        issue = {
            "magazine_date": magazine_date,
            "total_articles": len(clean_articles),
            "cover_image": cover_image,
            "cover_article_url": cover_article_url,
            "sections": ordered_sections,
        }

        path = os.path.join(issues_dir, f"{magazine_date}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(issue, f, ensure_ascii=False, indent=2)

        index_entries.append({
            "magazine_date": magazine_date,
            "total_articles": len(articles),
            "section_count": len(ordered_sections),
            "cover_image": cover_image,
        })
        print(f"  Saved {magazine_date}: {len(articles)} articles, "
              f"{len(ordered_sections)} sections")

    # Merge in any existing issues that weren't re-scraped in this run
    for magazine_date, entry in sorted(existing_index.items(), reverse=True):
        if magazine_date not in by_issue:
            # Keep the existing index entry; the issue JSON file is already on disk
            index_entries.append(entry)

    # Sort final index by date descending
    index_entries.sort(key=lambda x: x["magazine_date"], reverse=True)

    index = {
        "issues": index_entries,
        "last_updated": datetime.now().isoformat(),
        "total_issues": len(index_entries),
    }
    with open(os.path.join(ARCHIVE_DIR, "index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    print(f"\n✓ Archive complete: {len(index_entries)} issues saved to {ARCHIVE_DIR}/issues/")


COOKIES_FILE = os.path.join(ARCHIVE_DIR, "haaretz_cookies.json")


def save_login_cookies():
    """Open a visible browser so the user can log in to Haaretz, then save the cookies."""
    from playwright.sync_api import sync_playwright
    print("\n🔑  Opening browser — please log in to haaretz.co.il")
    print("    Close the browser window when done. Cookies save automatically.\n")
    cookies = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto("https://www.haaretz.co.il", wait_until="domcontentloaded")

        # Poll until logged in or browser closes — save cookies every tick
        for _ in range(300):
            try:
                page.wait_for_timeout(1000)
            except Exception:
                break  # browser was closed
            try:
                cookies = ctx.cookies()
                # Save on every tick so closing the window never loses them
                with open(COOKIES_FILE, "w", encoding="utf-8") as f:
                    json.dump(cookies, f, ensure_ascii=False, indent=2)
                cookie_map = {c["name"]: c["value"] for c in cookies}
                htzwif = cookie_map.get("_htzwif", "none")
                if htzwif and htzwif != "none":
                    print(f"\n✓ Detected login (subscription: {htzwif})")
                    page.wait_for_timeout(1000)
                    cookies = ctx.cookies()
                    break
            except Exception:
                break  # browser was closed

        # Final save
        try:
            cookies = ctx.cookies()
        except Exception:
            pass
        try:
            browser.close()
        except Exception:
            pass

    with open(COOKIES_FILE, "w", encoding="utf-8") as f:
        json.dump(cookies, f, ensure_ascii=False, indent=2)
    cookie_map = {c["name"]: c["value"] for c in cookies}
    print(f"✓ Saved {len(cookies)} cookies | _htzwif = {cookie_map.get('_htzwif','?')}")


def load_cookies():
    if not os.path.exists(COOKIES_FILE):
        return []
    with open(COOKIES_FILE, encoding="utf-8") as f:
        return json.load(f)


def fetch_shaar_images_playwright(issues_needing_cover):
    """Use Playwright (with saved Haaretz login cookies) to find the magazine cover image
    (שער מוסף) inside article pages for issues that don't have one yet.

    issues_needing_cover: list of (magazine_date, articles_list) tuples.
    Returns: dict of magazine_date → shaar_image_url
    """
    from playwright.sync_api import sync_playwright

    cookies = load_cookies()
    if not cookies:
        print("  ⚠  No Haaretz cookies found. Run: python scraper.py --setup-cookies")
        return {}

    results = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        ctx.add_cookies(cookies)

        for magazine_date, articles in issues_needing_cover:
            # Search all sections — cover is usually in magazine but sometimes in the-edge etc.
            # Put main section first, then the rest
            main = [a for a in articles if a["section"] == "magazine"]
            others = [a for a in articles if a["section"] != "magazine"]
            all_to_check = main + others
            found = False
            for article in all_to_check:
                try:
                    page = ctx.new_page()
                    page.goto(article["url"], wait_until="domcontentloaded", timeout=20000)
                    # Give JS a moment to render article body
                    page.wait_for_timeout(3000)
                    imgs = page.query_selector_all("img")
                    for img in imgs:
                        alt = img.get_attribute("alt") or ""
                        src = img.get_attribute("src") or ""
                        # Match "שר מוסף..." OR exact "שר" with a cover-named image
                        # alt patterns seen: "שר מוסף הארץ...", "שר" (exact), "בשר: ..." caption
                        # Sidebar widget uses alt="שר" with numeric filename (65536887.JPG) — excluded
                        if "שער מוסף" in alt or ("שער" in alt and is_cover_filename(src)):
                            srcset = img.get_attribute("srcset") or ""
                            # Take the largest from srcset if available
                            if srcset:
                                entries = re.findall(r"(https?://\S+?)\s+(\d+)w", srcset)
                                if entries:
                                    entries.sort(key=lambda x: int(x[1]), reverse=True)
                                    src = entries[0][0].rstrip(",")
                            if src:
                                results[magazine_date] = src
                                print(f"  ✓ {magazine_date}: found שער in {article['url'][-40:]}")
                                found = True
                    page.close()
                    if found:
                        break
                except Exception as e:
                    print(f"  ✗ {magazine_date}: error on {article['url'][-40:]}: {e}")
            if not found:
                print(f"  – {magazine_date}: no שער image found in main articles")

        browser.close()
    return results


def prev_month_str(ym):
    """Return the month before ym (e.g. '202604' → '202603')."""
    y, m = int(ym[:4]), int(ym[4:])
    m -= 1
    if m == 0:
        m, y = 12, y - 1
    return f"{y}{m:02d}"


if __name__ == "__main__":
    args  = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    fetch_titles  = "--fetch-titles"  in flags
    setup_cookies = "--setup-cookies" in flags
    fetch_covers  = "--fetch-covers"  in flags

    # ── Cookie setup mode ─────────────────────────────────────────────
    if setup_cookies:
        save_login_cookies()
        sys.exit(0)

    # ── Cover-only mode: re-fetch שער images for all issues ──────────
    if fetch_covers:
        print("=" * 50)
        print("  Fetching magazine cover images (שער מוסף)")
        print("=" * 50)
        issues_dir = os.path.join(ARCHIVE_DIR, "issues")
        issues_needing_cover = []
        for fname in sorted(os.listdir(issues_dir), reverse=True):
            if not fname.endswith(".json"):
                continue
            with open(os.path.join(issues_dir, fname), encoding="utf-8") as f:
                issue = json.load(f)
            # Include issues where cover is missing OR was set from the wrong fallback
            articles = []
            for sec_data in issue.get("sections", {}).values():
                articles.extend(sec_data.get("articles", []))
            issues_needing_cover.append((issue["magazine_date"], articles))

        cover_map = fetch_shaar_images_playwright(issues_needing_cover)

        # Patch JSON files and index
        index_path = os.path.join(ARCHIVE_DIR, "index.json")
        with open(index_path, encoding="utf-8") as f:
            idx = json.load(f)
        idx_by_date = {e["magazine_date"]: e for e in idx["issues"]}

        for magazine_date, shaar_url in cover_map.items():
            issue_path = os.path.join(issues_dir, f"{magazine_date}.json")
            with open(issue_path, encoding="utf-8") as f:
                issue = json.load(f)
            issue["cover_image"] = shaar_url
            # Mark the source article
            for sec_data in issue.get("sections", {}).values():
                for a in sec_data.get("articles", []):
                    if a.get("shaar_image") == shaar_url or a["section"] == "magazine":
                        issue["cover_article_url"] = a["url"]
                        break
            with open(issue_path, "w", encoding="utf-8") as f:
                json.dump(issue, f, ensure_ascii=False, indent=2)
            if magazine_date in idx_by_date:
                idx_by_date[magazine_date]["cover_image"] = shaar_url

        idx["last_updated"] = datetime.now().isoformat()
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(idx, f, ensure_ascii=False, indent=2)

        print(f"\n✓ Updated {len(cover_map)} issue covers.")
        sys.exit(0)

    # ── Normal scrape ─────────────────────────────────────────────────
    if args:
        year_months = args
    else:
        today = date.today()
        this_month = today.strftime("%Y%m")
        prev = (today.replace(day=1) - timedelta(days=1))
        prev_month = prev.strftime("%Y%m")
        year_months = [prev_month, this_month]

    # Always include one extra lookback month so that magazine weeks that start
    # in the last days of the previous month (e.g. April 3 magazine includes
    # articles from March 29–31) are fully covered.
    lookback = prev_month_str(min(year_months))
    if lookback not in year_months:
        year_months = [lookback] + list(year_months)
        print(f"  (Auto-adding lookback month {lookback} for cross-month weeks)")

    print("=" * 50)
    print("  Haaretz Magazine Archive Scraper")
    print("=" * 50)
    print(f"  Months      : {', '.join(year_months)}")
    print(f"  Fetch titles: {fetch_titles}")
    print(f"  Output dir  : {ARCHIVE_DIR}")
    print()

    by_issue = build_archive(year_months, fetch_titles=fetch_titles)
    save_archive(by_issue)

# Haaretz Magazine Archive — cover-fix checklist

There have been repeated wrong-cover incidents (2026-07-09, 2026-07-31, 2026-08-14 —
the last one wrong twice in a row from guessing — and 2026-08-21, see below). Before
ever writing a `cover_image`
value by hand (not via the automated scripts):

1. Find the real cover asset by its filename, not by "this photo looks cover-like."
   The genuine cover is almost always literally named `shaar.jpg` / `shaar-N.jpg` /
   `mu\d+.*` / `frontpage*` on some page in that issue. Grep for that filename
   pattern across the issue's article pages before considering anything else.
2. Download the candidate image and actually view it (Read tool on the downloaded
   file). Do not accept a plausible-looking portrait or photo as the cover without
   looking at it. A real cover shows the "מוסף הארץ" masthead + issue date + cover
   lines printed on the image itself — if that text isn't visible, it's not the
   cover, it's just some other photo from an article.
3. Only after visual confirmation, write `cover_image` (and `cover_article_url`) into
   `issues/YYYY-MM-DD.json`, `index.json`, and both `docs/` copies — all four files,
   kept consistent.
4. Don't guess from "this article looks like the flagship feature" or "this og:image
   looks cover-quality" — both of those are exactly how the two wrong guesses on
   2026-08-14 happened. If you can't find a `shaar`/`mu`/`frontpage`-named asset,
   say so and ask rather than picking the best-looking alternative.

See `weekly_update.py`'s module docstring for how the automated detection
(`scraper.py` + `find_cover.py`) was hardened on 2026-08-17 to reduce false
positives — but automated detection can still come back empty, and that's fine:
it now leaves `cover_image` unset and prints a warning instead of shipping a guess.

## 2026-08-21 incident: og:image date-match false positive, AND our scraper session can't see the שער widget (cause unconfirmed)

The 2026-08-21 issue's cover was auto-set to a photo from a personal column
("פעם חיבבתי את ביסמוט...") — that article's own per-article `og:image` happened
to be named `21-8-26-web.jpg`, which matched the date-pattern check (Priority 2)
even though it has nothing to do with the actual cover. That part is a confirmed,
fixed bug (see below).

The real cover **does exist** and **is** embedded on the flagship article's page
(`.../magazine/2026-08-20/.../000001a0-19df-dfad-a3a1-bdff6fff0000`, the
"המגמה חדה: ערבים מהגרים לערים יהודיות" piece) — Nadav found it there directly
(`shaar.jpg`, content ID `000001a0-1a84-dfad-a3a1-bfa798b90001`, confirmed by
downloading and viewing it: shows the "מוסף הארץ" masthead + "21 08 2026" date,
matching format exactly). But repeated attempts to find it via this repo's
scraper session (Playwright + `haaretz_cookies.json`, headless, in this sandboxed
environment) — full HTML dump after scrolling, multiple wait strategies — found
**zero** "שער"/"shaar" occurrences anywhere on that same page. Root cause of
*that* gap is NOT confirmed — checked and ruled out: the site homepage and the
`/magazine/musafcover` tag-archive page as alternate sources (neither has it
either). Saw paywall/comment-subscribe markers on the page suggesting our scraper
session may not be authenticating as a full logged-in subscriber the way a normal
browser session would, even though `sso_token`/`user_details`/etc. cookies have
long expiry dates on paper — but this is a hypothesis, not confirmed. Could also
be headless/bot-detection or a geo/IP difference between the scraper's environment
and a normal browser. If `refresh_cookies.py` (interactive headed-browser login,
needs to be run locally, not from this scraping session) doesn't fix it, this
needs more investigation before concluding anything further about *why* Priority 1
can't see the widget — don't re-assume "Haaretz removed the feature."

**Fix applied:** added `is_portrait_cover_crop()` (in `scraper.py`, mirrored in
`find_cover.py`) as a hard gate on every cover candidate, from every priority
path, including the "already has a cover, skip re-checking" logic in
`weekly_update.py` — applies going forward automatically. Real Haaretz covers are
always requested from their image CMS at `width=1500&height=1959-1981` (portrait,
ratio ~0.756-0.766 — an actual scanned front page); ordinary `og:image` thumbnails
are `width=1200&height=630` (landscape, ratio 1.9) and can never contain the
masthead. This specifically closes the Priority-2 false-positive hole that caused
this incident, independent of whatever is going on with Priority 1's visibility.

An archive-wide audit against this rule also found 3 older issues with the same
wrong crop shape (2024-08-23, 2024-09-13, 2025-06-13) — left as-is on Nadav's call
(2026-08-23): only the 2026-08-21 cover was fixed (to the real `shaar.jpg` found
above), since a genuine replacement wasn't sought for the other three. If those
older ones ever come up again, `is_portrait_cover_crop()` confirms they're wrong.

**Practical consequence:** if Priority 1 keeps failing to see the שער widget on
future runs for whatever reason, issues will come back "NO COVER FOUND" instead of
a wrong guess (correct, safe behavior) — but the widget itself is very likely still
there when Haaretz is accessed normally, so this should be actively investigated
(try `refresh_cookies.py` first) rather than assumed permanent.

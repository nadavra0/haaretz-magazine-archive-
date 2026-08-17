# Haaretz Magazine Archive — cover-fix checklist

There have been repeated wrong-cover incidents (2026-07-09, 2026-07-31, 2026-08-14 —
the last one wrong twice in a row from guessing). Before ever writing a `cover_image`
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

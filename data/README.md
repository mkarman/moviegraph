# data/

Everything in this folder except this file is gitignored, because it is personal viewing history.

## Staging: put your exports here

```
data/staging/
  amazon/watch-history.csv          Prime Video watch history page export
  netflix/ViewingActivity.csv       from Netflix "Download your personal information", CONTENT_INTERACTION folder
  netflix/Ratings.csv               same folder; optional, adds your ratings
  profiles.txt                      optional: Netflix profiles to keep, one name per line (default: all)
```

File and folder names don't matter: each CSV is recognized by its columns, and the Netflix .zip can be dropped in
whole. Several exports (two Amazon accounts, a household's Netflix) can sit side by side; they are merged.
The Netflix files not listed above are not used.

## What the pipeline writes

| File | Written by | Contents |
|---|---|---|
| `normalized/movies.csv` | `scripts/normalize.py` | one row per unique movie across all services, with watch dates, profiles, your rating, and whether TMDB should confirm it is a film (`verify_type`) |
| `normalized/tv_shows.csv` | `scripts/normalize.py` | one row per show, with seasons, episode counts and rating |
| `normalized/extras.csv` | `scripts/normalize.py` | trailers, clips, and movies only sampled for a few minutes |
| `normalized/ratings.csv` | `scripts/normalize.py` | every rating with its raw value and scale, normalized label and score, and what it matched |
| `enriched_tmdb.json` | `scripts/enrich_tmdb.py` | TMDB match and metadata per movie, plus the history and rating fields above |
| `blurbs.json` | `scripts/write_blurbs.py` | optional: a one-line menu note per film, keyed by TMDB id |

The older layout (`data/watch-history.csv` with no `staging/` folder) still works for an Amazon-only run.

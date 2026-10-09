# data/

Everything in this folder except this file is gitignored, because it is personal viewing history.

Put your Amazon Prime Video export here as `watch-history.csv`
(downloaded from your Prime Video watch history page). The pipeline writes:

| File | Written by | Contents |
|---|---|---|
| `movies_clean.csv` | `scripts/clean_watch_history.py` | one row per unique movie |
| `tv_shows.csv` | `scripts/clean_watch_history.py` | one row per show/season, with episode counts |
| `extras.csv` | `scripts/clean_watch_history.py` | trailers and other non-movie rows tagged "Movie" |
| `enriched_tmdb.json` | `scripts/enrich_tmdb.py` | TMDB match and metadata per movie |

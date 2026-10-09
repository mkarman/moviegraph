# MovieGraph

Turn an Amazon Prime Video watch history export into an interactive, filterable graph of the movies you've watched,
linked by shared directors, cast and genres, so it's easy to pick recommendations for friends.

The pipeline has three steps, all plain Python 3 with no third-party packages:

1. **Clean** the export into unique movies, TV shows and extras.
2. **Enrich** each movie from [TMDB](https://www.themoviedb.org/): genres, directors, writers, cast, keywords, rating, runtime.
3. **Build** a single self-contained HTML page with the graph and filters (D3, loaded from a CDN).

## Quick start

```bash
# 1. Put your export at data/watch-history.csv, then clean it
python scripts/clean_watch_history.py

# 2. Match to TMDB (needs a free API key: https://www.themoviedb.org/settings/api)
export TMDB_API_KEY=your-key            # PowerShell: $env:TMDB_API_KEY = "your-key"
python scripts/enrich_tmdb.py           # --limit 20 for a quick trial

# 3. Build the graph and open it in a browser
python graph/build_graph.py data/enriched_tmdb.json graph/movie-graph.html
```

To try the graph without any personal data, run `python graph/build_graph.py`; it uses the ~90 hand-entered
titles in `graph/sample_movies.json`.

## Layout

| Path | What it does |
|---|---|
| `scripts/clean_watch_history.py` | Parses the export, strips Amazon edition tags ("(4K UHD)", "(English Dubbed)"), dedupes by title, splits out TV shows and trailers |
| `scripts/enrich_tmdb.py` | Searches TMDB per title (exact match first, most-voted on ties, then fuzzy), fetches credits and keywords. Hand fixes go in `OVERRIDES` |
| `graph/build_graph.py` | Injects movie JSON into `graph/template.html` to produce `movie-graph.html` |
| `graph/template.html` | The graph UI: force layout, filters, search |
| `graph/make_sample.py` | Regenerates `graph/sample_movies.json` |
| `docs/enrichment.md` | Why TMDB, match-rate results and known gaps |
| `data/` | Your local data. Gitignored except its README |

## Website (GitHub Pages)

`.github/workflows/pages.yml` publishes `site/` on every push to `main`, plus `graph.html` built at deploy time.
It uses `site/movies.json` if that file is committed, and otherwise the sample data. A Pages site is public,
so committing `site/movies.json` publishes your movie list. Turn Pages on once under
Settings → Pages → Build and deployment → Source: **GitHub Actions**.

## Privacy and secrets

- Your watch history and everything derived from it (`data/*`, `graph/movie-graph.html`) is gitignored.
  Commit a built graph only if you mean to share it.
- The TMDB key is read only from the `TMDB_API_KEY` environment variable. Never put it in a file in this repo.

## Known limitations

- Amazon's export gives no release year, so titles shared by several films are resolved by vote count, which is a guess.
  Check rows whose `status` mentions a tie in `enriched_tmdb.json`.
- If the export was opened and re-saved in Excel, the "Date Watched" column can be reduced to `MM:SS.f`, losing the dates.

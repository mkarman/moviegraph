# MovieGraph

Turn your Amazon Prime Video and Netflix watch history exports into an interactive, filterable graph of the movies
you've watched, linked by shared directors, cast and genres, so it's easy to pick recommendations for friends.

The pipeline has four stages, all plain Python 3 with no third-party packages:

1. **Stage**: drop the raw exports into `data/staging/` (subfolders and .zip files are fine).
2. **Normalize**: recognize each file by its columns, sort movies from TV and extras, merge the same film across
   services, and map every rating onto one scale.
3. **Enrich**: match each movie on [TMDB](https://www.themoviedb.org/) for genres, directors, writers, cast, keywords,
   rating and runtime, and confirm titles whose type the export didn't state.
4. **Graph**: build a single self-contained HTML page with the graph and filters (D3, loaded from a CDN).

## Quick start

```bash
# 1. Stage your exports (any file names, any subfolders)
#    data/staging/amazon/watch-history.csv
#    data/staging/netflix/ViewingActivity.csv, Ratings.csv   (or the whole Netflix .zip)

# 2-4. Normalize, enrich and build (needs a free TMDB key: https://www.themoviedb.org/settings/api)
export TMDB_API_KEY=your-key            # PowerShell: $env:TMDB_API_KEY = "your-key"
python scripts/run_pipeline.py          # --profile NAME to keep one Netflix profile; open graph/movie-graph.html
```

Each stage also runs on its own: `scripts/normalize.py`, `scripts/enrich_tmdb.py` (`--limit 20` for a quick trial),
and `graph/build_graph.py data/enriched_tmdb.json graph/movie-graph.html`. Enrichment reuses earlier matches from
`data/enriched_tmdb.json`, so adding a new export only looks up the new titles.

To try the graph without any personal data, run `python graph/build_graph.py`; it uses the ~90 hand-entered
titles in `graph/sample_movies.json`. `python -m unittest discover tests` runs the pipeline on synthetic exports.

## Sources and how they're reconciled

| | Amazon Prime Video | Netflix |
|---|---|---|
| File | watch history CSV | `ViewingActivity.csv`, `Ratings.csv` (from "Download your personal information") |
| Movie or TV | stated (`Type` column) | not stated; inferred from the title, then confirmed on TMDB |
| Dates | none usable (see limitations) | UTC start time per view |
| Profiles | none | per view and per rating |
| Ratings | none | 1-5 stars (older) and thumbs (newer) |

**Movie or TV (Netflix).** Netflix logs an episode as `Show: Season 2: Episode Name (Episode 3)`. `normalize.py`
treats `(Episode N)`, a middle segment like `Season 2` / `Book 1` / `Limited Series`, or a title that is exactly a
show name seen elsewhere as TV, and trailers, clips and other `Supplemental Video Type` rows as extras. Everything
else is a movie candidate, which `enrich_tmdb.py` also searches as a TV show: if TMDB knows it only as a show, or
the show has more votes than the film of that name, it is dropped from the graph as TV. A Netflix movie watched for
under 20 minutes in total and never rated counts as sampled, not watched (`--min-minutes` changes this).

**Ratings.** Every rating becomes `rating_label` (liked / neutral / disliked) and `rating_score` (0 to 1), and the
raw value and scale stay in `data/normalized/ratings.csv`.

| Raw | Label | Score |
|---|---|---|
| 5 stars / double thumbs up (3) | liked | 1.0 |
| 4 stars / thumbs up (2) | liked | 0.75 |
| 3 stars | neutral | 0.5 |
| 2 stars | disliked | 0.25 |
| 1 star / thumbs down (1) | disliked | 0.0 |
| thumbs 0, stars 0 (deleted), -1 (not interested), -2 (not seen) | no rating | |

Thumbs up is scored as 4 stars because Netflix's own conversion folded 3-5 stars into thumbs up. Each profile's most
recent rating of a title wins, and several profiles' ratings are averaged. A title rated but never streamed (common
for star ratings from the DVD era) is kept as a movie candidate, since a rating means it was seen.

**Same film, two services.** Titles merge when they match after edition tags (`(4K UHD)`, `: International
Version`) and punctuation are stripped, and again in the graph when two titles land on the same TMDB film.

## Layout

| Path | What it does |
|---|---|
| `scripts/run_pipeline.py` | Runs normalize, enrich and graph in order |
| `scripts/normalize.py` | Reads every export in `data/staging/`, writes `data/normalized/` (movies, TV shows, extras, ratings) |
| `scripts/sources/` | One adapter per service (`amazon.py`, `netflix.py`) plus shared title and rating helpers. A new service is a new adapter with `detect()` and `views()` |
| `scripts/enrich_tmdb.py` | Searches TMDB per title (exact match first, most-voted on ties, then fuzzy), checks unknown types against TV search, fetches credits and keywords. Hand fixes go in `OVERRIDES` |
| `graph/build_graph.py` | Injects movie JSON into `graph/template.html` to produce `movie-graph.html` |
| `graph/template.html` | The graph UI: force layout, filters (genre, your rating, service, profile, year, TMDB rating), search |
| `graph/make_sample.py` | Regenerates `graph/sample_movies.json` |
| `tests/` | Synthetic Amazon and Netflix exports and end-to-end tests |
| `docs/enrichment.md` | Why TMDB, match-rate results and known gaps |
| `data/` | Your local data. Gitignored except its README |

## Menu mode

The **Menu mode** button in the graph's header swaps the "if you liked" panel for a menu builder:

- Drag a movie onto one of four courses, or click it and pick a course. **Lasso select** grabs a whole cluster.
- **Suggest courses** pre-fills every visible, untagged movie from simple genre, runtime and rating rules, shown as
  dashed rings until you accept them. Filter first (say, Horror) to suggest for just that slice.
- Courses are neutral roles (opener, second, main, finish). The house style (Italian, French, diner, izakaya) only
  renames them and changes the printed card in **Preview menu**, so switching styles never means re-tagging.
- Tags belong to a named menu, so the same film can open one menu and headline another. Menus are saved in the
  browser's local storage, and **Copy as text** gives a plain list to send to a friend.

## Website (GitHub Pages)

`.github/workflows/pages.yml` publishes `site/` on every push to `main`, plus `graph.html` built at deploy time.
It uses `site/movies.json` if that file is committed, and otherwise the sample data. `site/menu.html` is the horror tasting menu. A Pages site is public,
so committing `site/movies.json` publishes your movie list (this repo does, on purpose). Turn Pages on once under
Settings → Pages → Build and deployment → Source: **GitHub Actions**.

## Privacy and secrets

- Your raw exports and pipeline outputs (`data/*`, including `data/staging/`, and `graph/movie-graph.html`) are gitignored.
  The published movie list in `site/movies.json` is a trimmed copy: TMDB id, title, year, genres, directors, cast, rating, runtime.
  The pipeline's output now also carries your ratings, watch dates and Netflix profile names; leave those out if you
  refresh `site/movies.json` from it.
- The TMDB key is read only from the `TMDB_API_KEY` environment variable. Never put it in a file in this repo.

## Known limitations

- Neither export gives a release year, so titles shared by several films are resolved by vote count, which is a guess.
  Check rows whose `status` mentions a tie in `enriched_tmdb.json`.
- Netflix's movie/TV call is a heuristic plus a TMDB check. A one-off special logged under a show's name (an MST3K
  episode, a stand-up special) can go either way; `status` in `enriched_tmdb.json` says which rule decided it.
- Some Netflix rows lose the show name (`:  1: Episode 4`); they are grouped as "(show name missing in export)".
- If the export was opened and re-saved in Excel, the "Date Watched" column can be reduced to `MM:SS.f`, losing the dates.

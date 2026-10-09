# Movie enrichment: source choice and sample results

## Recommendation: TMDB as the primary source
TMDB gives everything the graph needs in one call per movie (`/movie/{id}?append_to_response=credits,keywords`):
genres, directors, writers, full cast, user keywords, runtime, rating, poster, and the IMDb id.
It needs a free API key from https://www.themoviedb.org/settings/api, read from the `TMDB_API_KEY` environment variable. Rate limit is roughly 50 requests/sec,
so all 677 titles take two calls each and a couple of minutes.

Wikidata (free, no key) is a good secondary source, not a primary one: it stores TMDB and IMDb ids (property P4947),
so it can be joined later for things TMDB lacks (awards, based-on, country of origin), but its keyword coverage is thin and
its cast lists are incomplete for small films. It could not be tested live from this environment.

## Sample: 20 random titles from data/movies.json
| Amazon title | TMDB match | How |
|---|---|---|
| Die Hard (4K UHD) | Die Hard (1988) | exact after stripping "(4K UHD)" |
| Hundreds of Beavers | Hundreds of Beavers (2024) | exact |
| Harry Potter and the Prisoner of Azkaban | (2004) | exact |
| African Cats | (2011) | exact |
| Strawberry Mansion | (2021) | exact |
| Popstar: Never Stop Never Stopping | (2016) | exact |
| Megamind | (2010) | exact |
| How to Kill Monsters | (2023) | exact |
| The City Of Lost Children | (1995) | exact |
| Moana Trailer | none | trailer, not a film |
| Lord of Illusions | (1995) | 2 exact titles, most-voted wins |
| Robot Carnival (English Dubbed) | (1987) | exact after stripping "(English Dubbed)" |
| Episode 0: The Winning Team! | none | episode/special, not on TMDB |
| Caveat | (2021) | 2 exact titles, most-voted wins |
| Mikey and Nicky | (1976) | exact |
| Hackers | (1995) | 2 exact titles, most-voted wins |
| Inception | (2010) | exact |
| MST3K: The Christmas Dragon | none | live-show special, not on TMDB |
| Venture Bros: Radiant is the Blood of the Baboon Heart | (2023) | fuzzy ("The Venture Bros.: …") |
| To Live And Die In L.A. (1985) | (1985) | exact, year used from title |

**17 of 20 matched (85%); 17 of 18 actual films (94%).** The 3 misses are a trailer, an episode and an MST3K special.
4 of 20 titles had several films with the same name; picking the most-voted one was right every time here, but
it is a guess, since the Amazon export gives no year. The first search result alone would have been wrong for "Moana"
(TMDB lists the 2026 remake first).

## Coverage on matched films (spot-checked 4, including obscure ones)
| Film | Genres | Directors | Cast | Keywords |
|---|---|---|---|---|
| How to Kill Monsters (10 votes) | Comedy, Horror | Stewart Sparke | 20 | 4 |
| Hundreds of Beavers | Comedy, Adventure, Action | Mike Cheslik | 27 | 7 |
| Mikey and Nicky | Crime, Drama | Elaine May | 21 | 13 |
| Robot Carnival | Animation, Science Fiction | 9 (anthology) incl. Katsuhiro Otomo | 18 | 11 |

Even the least-known film had genres, a director, a cast and keywords. Keywords are the noisiest field (mood tags like
"gloomy", "bold" mixed with plot tags), so they suit filtering better than graph edges unless pruned.

## Prototype
`scripts/enrich_tmdb.py` strips Amazon decorations, pulls a year out of "(1985)", skips trailers and episodes,
prefers exact title matches (most-voted on ties), falls back to a close fuzzy match, then fetches details.
Output goes to `data/enriched_tmdb.json` as a flat list in the shape `graph/build_graph.py` reads (title, year, genres, directors, cast, rating, runtime, tmdb_id), plus `matched` and a `status` per row saying how it matched, so ties can be reviewed.

    TMDB_API_KEY=<key> python scripts/enrich_tmdb.py   # reads data/movies_clean.csv by default

## Notes
- The earlier `fetch_metadata.py` took the first search result, which is wrong for ambiguous titles; `enrich_tmdb.py` replaces it.

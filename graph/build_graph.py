#!/usr/bin/env python3
"""Build movie-graph.html from a movie metadata JSON file.

Usage: python3 build_graph.py [input.json] [output.html]
Default input is sample_movies.json. Input may be a list of movies or {"movies": [...]}.
Each movie needs a title; these fields are used when present (aliases in brackets):
  year [release_date], genres, directors [director], cast (names or {"name":..}),
  rating [vote_average], runtime, tmdb_id [id].
Viewing history from scripts/normalize.py is carried along when present: sources, profiles, last_watched, and
your own rating as rating_label (liked / neutral / disliked) and rating_score (0 to 1).
A one-line menu note per film ("blurb") comes from the input's own blurb field or from data/blurbs.json
(scripts/write_blurbs.py), keyed by TMDB id; --blurbs PATH points somewhere else.
Rows TMDB identified as TV shows (media_type "tv") are left out, and two rows that matched the same TMDB film
(say "Die Hard (4K UHD)" from Amazon and "Die Hard" from Netflix) become one node.
"""
import json, sys, pathlib
here = pathlib.Path(__file__).parent
argv = sys.argv[1:]
blurb_file = here.parent / "data" / "blurbs.json"
if "--blurbs" in argv:
    i = argv.index("--blurbs"); blurb_file = pathlib.Path(argv[i + 1]); del argv[i:i + 2]
src = pathlib.Path(argv[0]) if argv else here / "sample_movies.json"
out = pathlib.Path(argv[1]) if len(argv) > 1 else here / "movie-graph.html"
blurbs = json.loads(blurb_file.read_text(encoding="utf-8")) if blurb_file.exists() else {}

data = json.loads(src.read_text(encoding="utf-8"))
items = data["movies"] if isinstance(data, dict) else data
sample = bool(data.get("sample")) if isinstance(data, dict) else False

def names(v):
    if not v: return []
    if isinstance(v, str): v = [v]
    return [x["name"] if isinstance(x, dict) else str(x) for x in v if x]

def your_label(score):
    # Same cut points as scripts/sources/common.py: 3 of 5 stars (0.5) is neutral
    return "liked" if score >= 0.625 else "disliked" if score <= 0.375 else "neutral"

movies, by_id = [], {}
for i, m in enumerate(items):
    if not m.get("title") or m.get("matched") is False or m.get("media_type") == "tv": continue
    year = m.get("year") or (str(m.get("release_date") or "")[:4] or None)
    rating = m.get("rating", m.get("vote_average"))
    node_id = str(m.get("tmdb_id") or m.get("id") or f"m{i}")
    score = m.get("rating_score")
    node = {
        "id": node_id,
        "title": m["title"],
        "year": int(year) if year and str(year).isdigit() else None,
        "genres": names(m.get("genres")),
        "directors": names(m.get("directors") or m.get("director")),
        "cast": names(m.get("cast"))[:8],
        "rating": round(float(rating), 1) if rating not in (None, "") else None,
        "runtime": m.get("runtime") or None,
        "sources": sorted(set(names(m.get("sources")))),
        "profiles": sorted(set(names(m.get("profiles")))),
        "last_watched": m.get("last_watched") or None,
        "blurb": m.get("blurb") or blurbs.get(node_id) or None,
        "scores": [float(score)] if score not in (None, "") else [],
    }
    seen = by_id.get(node_id)
    if seen:  # same film under two spellings or from two services
        for f in ("sources", "profiles"):
            seen[f] = sorted(set(seen[f]) | set(node[f]))
        seen["scores"] += node["scores"]
        seen["last_watched"] = max(filter(None, [seen["last_watched"], node["last_watched"]]), default=None)
        continue
    by_id[node_id] = node
    movies.append(node)

for m in movies:
    scores = m.pop("scores")
    m["my_score"] = round(sum(scores) / len(scores), 2) if scores else None
    m["my_rating"] = your_label(m["my_score"]) if scores else None

blob = json.dumps({"sample": sample, "movies": movies}, ensure_ascii=False).replace("</", "<\\/")
html = (here / "template.html").read_text(encoding="utf-8").replace("/*__MOVIE_DATA__*/", blob)
out.write_text(html, encoding="utf-8")
print(f"{len(movies)} movies -> {out}")

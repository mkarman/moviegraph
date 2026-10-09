#!/usr/bin/env python3
"""Build movie-graph.html from a movie metadata JSON file.

Usage: python3 build_graph.py [input.json] [output.html]
Default input is sample_movies.json. Input may be a list of movies or {"movies": [...]}.
Each movie needs a title; these fields are used when present (aliases in brackets):
  year [release_date], genres, directors [director], cast (names or {"name":..}),
  rating [vote_average], runtime, id [tmdb_id].
"""
import json, sys, pathlib
here = pathlib.Path(__file__).parent
src = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else here / "sample_movies.json"
out = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else here / "movie-graph.html"

data = json.loads(src.read_text(encoding="utf-8"))
items = data["movies"] if isinstance(data, dict) else data
sample = bool(data.get("sample")) if isinstance(data, dict) else False

def names(v):
    if not v: return []
    if isinstance(v, str): v = [v]
    return [x["name"] if isinstance(x, dict) else str(x) for x in v if x]

movies = []
for i, m in enumerate(items):
    if not m.get("title") or m.get("matched") is False: continue
    year = m.get("year") or (str(m.get("release_date") or "")[:4] or None)
    rating = m.get("rating", m.get("vote_average"))
    movies.append({
        "id": str(m.get("id") or m.get("tmdb_id") or f"m{i}"),
        "title": m["title"],
        "year": int(year) if year and str(year).isdigit() else None,
        "genres": names(m.get("genres")),
        "directors": names(m.get("directors") or m.get("director")),
        "cast": names(m.get("cast"))[:8],
        "rating": round(float(rating), 1) if rating not in (None, "") else None,
        "runtime": m.get("runtime") or None,
    })

blob = json.dumps({"sample": sample, "movies": movies}, ensure_ascii=False).replace("</", "<\\/")
html = (here / "template.html").read_text(encoding="utf-8").replace("/*__MOVIE_DATA__*/", blob)
out.write_text(html, encoding="utf-8")
print(f"{len(movies)} movies -> {out}")

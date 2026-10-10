#!/usr/bin/env python3
"""
export_site.py - Write the public movie list for the GitHub Pages site from the enrichment output.

Usage: python scripts/export_site.py [data/enriched_tmdb.json] [site/movies.json] [--no-ratings]

Keeps only what the graph needs: TMDB id, title, year, genres, directors, cast, TMDB rating, runtime, and
which services the film was watched on. Your own rating (liked / neutral / disliked, 0-1 score) is included
unless --no-ratings is given. Watch dates, profile names and raw rating details are never written, since the
site is public. TV shows and unmatched titles are left out, and two titles that matched one TMDB film
become one entry.
"""

import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
args = [a for a in sys.argv[1:] if not a.startswith("--")]
src = Path(args[0]) if args else root / "data" / "enriched_tmdb.json"
out = Path(args[1]) if len(args) > 1 else root / "site" / "movies.json"
ratings = "--no-ratings" not in sys.argv

movies = {}
for r in json.loads(src.read_text(encoding="utf-8")):
    if not r.get("matched") or r.get("media_type") == "tv" or not r.get("tmdb_id"):
        continue
    m = movies.get(r["tmdb_id"])
    if m:  # same film under two titles: merge services and ratings
        m["sources"] = sorted(set(m["sources"]) | set(r.get("sources") or []))
        if ratings and r.get("rating_score") is not None:
            m["_scores"].append(float(r["rating_score"]))
        continue
    movies[r["tmdb_id"]] = {
        "id": r["tmdb_id"], "title": r["title"], "year": r.get("year"), "genres": r.get("genres") or [],
        "directors": r.get("directors") or [], "cast": (r.get("cast") or [])[:10], "rating": r.get("rating"),
        "runtime": r.get("runtime"), "sources": sorted(r.get("sources") or []),
        "_scores": [float(r["rating_score"])] if ratings and r.get("rating_score") is not None else [],
    }

rows = []
for m in movies.values():
    scores = m.pop("_scores")
    if scores:
        m["rating_score"] = round(sum(scores) / len(scores), 2)
    rows.append(m)
out.write_text(json.dumps(rows, indent=0, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"{len(rows)} movies ({sum('rating_score' in m for m in rows)} with your rating) -> {out}")

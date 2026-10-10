#!/usr/bin/env python3
"""
run_pipeline.py - Run every stage: staging -> normalize -> enrich -> graph.

Usage: python scripts/run_pipeline.py [--profile NAME ...] [--min-minutes 20] [--skip-enrich]

  1. normalize.py   data/staging/**        -> data/normalized/*.csv
  2. enrich_tmdb.py data/normalized/movies.csv -> data/enriched_tmdb.json   (needs TMDB_API_KEY for new titles)
  3. build_graph.py data/enriched_tmdb.json   -> graph/movie-graph.html

--skip-enrich rebuilds the graph from the existing data/enriched_tmdb.json, for when there is no API key at hand.
"""

import argparse
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
ap = argparse.ArgumentParser()
ap.add_argument("--profile", action="append", default=[])
ap.add_argument("--min-minutes")
ap.add_argument("--skip-enrich", action="store_true")
args = ap.parse_args()


def step(*cmd):
    print(f"\n$ python {' '.join(map(str, cmd))}", flush=True)
    subprocess.run([sys.executable, *map(str, cmd)], check=True, cwd=root)


norm = ["scripts/normalize.py"] + [x for p in args.profile for x in ("--profile", p)]
if args.min_minutes:
    norm += ["--min-minutes", args.min_minutes]
step(*norm)
if not args.skip_enrich:
    step("scripts/enrich_tmdb.py")
step("graph/build_graph.py", "data/enriched_tmdb.json", "graph/movie-graph.html")

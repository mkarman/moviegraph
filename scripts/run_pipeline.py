#!/usr/bin/env python3
"""
run_pipeline.py - Run every stage: staging -> normalize -> enrich -> graph, then open the graph.

Usage: python scripts/run_pipeline.py [--import [FOLDER]] [--profile NAME ...] [--min-minutes 20]
                                      [--skip-enrich] [--no-open]

  0. --import       FOLDER (default: your Downloads) -> data/staging/   newest Amazon and Netflix export
  1. normalize.py   data/staging/**        -> data/normalized/*.csv
  2. enrich_tmdb.py data/normalized/movies.csv -> data/enriched_tmdb.json   (needs TMDB_API_KEY for new titles)
  3. write_blurbs.py data/enriched_tmdb.json  -> data/blurbs.json         (only with --blurbs; needs ANTHROPIC_API_KEY)
  4. build_graph.py data/enriched_tmdb.json   -> graph/movie-graph.html

Before anything runs it checks that there are exports to read and a TMDB key to use, and says what to do if
not. The key comes from the TMDB_API_KEY environment variable or the repo's .env file (gitignored); when it is
missing, you are asked for it once and can save it to .env so later runs need nothing set.

--skip-enrich rebuilds the graph from the existing data/enriched_tmdb.json, for when there is no API key at hand.
"""

import argparse
import getpass
import os
import subprocess
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from local_setup import ENV_FILE, HOW_TO_GET, ROOT, find_exports, load_env, save_env, staged  # noqa: E402

ap = argparse.ArgumentParser(description="Normalize, enrich and graph your watch history.")
ap.add_argument("--import", dest="import_from", nargs="?", const=str(Path.home() / "Downloads"), metavar="FOLDER",
                help="first copy the newest Amazon and Netflix exports from FOLDER (default: your Downloads)")
ap.add_argument("--profile", action="append", default=[])
ap.add_argument("--min-minutes")
ap.add_argument("--skip-enrich", action="store_true")
ap.add_argument("--no-open", action="store_true", help="don't open the graph in a browser at the end")
args = ap.parse_args()

staging = ROOT / "data" / "staging"
legacy = ROOT / "data" / "watch-history.csv"


def step(*cmd):
    print(f"\n$ python {' '.join(map(str, cmd))}", flush=True)
    if subprocess.run([sys.executable, *map(str, cmd)], cwd=ROOT).returncode:
        sys.exit(f"\n{cmd[0]} stopped with an error (see above). Fix that and run this again; "
                 "TMDB matches found so far are kept.")


def need_tmdb_key():
    """Make sure TMDB_API_KEY is set, asking for it (and offering to save it) when run by hand."""
    if os.environ.get("TMDB_API_KEY"):
        return
    print("\nNo TMDB API key found. Get a free one at https://www.themoviedb.org/settings/api "
          "(the \"API Key\", not the read access token).")
    if not sys.stdin.isatty():
        sys.exit(f"Put TMDB_API_KEY=your-key in {ENV_FILE}, or run with --skip-enrich to reuse earlier results.")
    value = getpass.getpass("Paste your TMDB API key (input hidden, Enter to stop): ").strip()
    if not value:
        sys.exit("Stopped: no key. Run with --skip-enrich to rebuild the graph from earlier results.")
    os.environ["TMDB_API_KEY"] = value
    if input(f"Save it to {ENV_FILE.name} so you aren't asked again? [Y/n] ").strip().lower() in ("", "y", "yes"):
        save_env("TMDB_API_KEY", value)
        print(f"Saved to {ENV_FILE} (gitignored).")


load_env()  # before anything reads a key; the stages below inherit os.environ

if args.import_from:
    print(f"Looking for exports in {args.import_from}")
    find_exports(args.import_from, staging)

have = staged(staging)
if not have and not legacy.exists():
    sys.exit(f"\nNo Amazon or Netflix exports in {staging}.\n\n{HOW_TO_GET}")
services = sorted({s for kinds in have.values() for s, _ in kinds})
if services:
    print(f"Exports staged: {', '.join(services)}")
    if "netflix" in services and not (staging / "profiles.txt").exists() and not args.profile:
        print("  All Netflix profiles are included; normalize lists them below if you want to keep only some.")

enriched = ROOT / "data" / "enriched_tmdb.json"
if args.skip_enrich and not enriched.exists():
    sys.exit(f"--skip-enrich needs an earlier {enriched.relative_to(ROOT)}, and there isn't one yet. "
             "Run once without it.")
if not args.skip_enrich:
    need_tmdb_key()

norm = ["scripts/normalize.py"] + [x for p in args.profile for x in ("--profile", p)]
if args.min_minutes:
    norm += ["--min-minutes", args.min_minutes]
step(*norm)
if not args.skip_enrich:
    step("scripts/enrich_tmdb.py")
graph = ROOT / "graph" / "movie-graph.html"
step("graph/build_graph.py", enriched.relative_to(ROOT), graph.relative_to(ROOT))

print(f"\nDone: {graph}")
if not args.no_open and sys.stdin.isatty():
    webbrowser.open(graph.as_uri())

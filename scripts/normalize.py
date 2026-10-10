#!/usr/bin/env python3
"""
normalize.py - Turn every export in the staging folder into one set of clean tables.

Usage: python scripts/normalize.py [--staging data/staging] [--out data/normalized]
                                   [--profile NAME ...] [--min-minutes 20]

Drop exports anywhere under the staging folder (subfolders and .zip files are fine). Each CSV is recognized
by its columns, not its name, so a fresh export from any account works without renaming:

  Amazon Prime Video   watch-history CSV           -> views (type given by Amazon)
  Netflix              ViewingActivity.csv         -> views (type inferred from the title, see sources/netflix.py)
  Netflix              Ratings.csv                 -> ratings (stars and thumbs mapped to one scale)
  Netflix              PlaybackRelatedEvents.csv   -> skipped, it repeats ViewingActivity

Writes to the out folder:
  movies.csv     one row per unique movie across all sources, with watch dates, profiles and your rating
  tv_shows.csv   one row per show, with seasons, episode counts and rating
  extras.csv     trailers, clips, and movies only sampled for a few minutes
  ratings.csv    every rating, normalized, with what it was matched to

A title counts as the same movie across sources when its key (lowercase, punctuation stripped, edition tags
like "(4K UHD)" removed) matches.
"""

import argparse
import csv
import io
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

from sources import amazon, netflix
from sources.common import key, label_for, normalize_rating, pick_display

ADAPTERS = [amazon, netflix]


def read_csvs(staging):
    """Yield (name, header, rows) for every CSV under staging, including inside .zip files."""
    for path in sorted(staging.rglob("*")):
        if path.suffix.lower() == ".csv":
            with open(path, encoding="utf-8-sig", newline="") as f:
                yield str(path), list(csv.DictReader(f))
        elif path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as z:
                for name in sorted(z.namelist()):
                    if name.lower().endswith(".csv"):
                        text = z.read(name).decode("utf-8-sig")
                        yield f"{path}!{name}", list(csv.DictReader(io.StringIO(text)))


def load(staging):
    views, ratings = [], []
    for name, rows in read_csvs(staging):
        header = rows[0].keys() if rows else []
        for adapter in ADAPTERS:
            what = adapter.detect(header)
            if what == "views":
                got = list(adapter.views(rows))
                views += got
            elif what == "ratings":
                got = list(adapter.ratings(rows))
                ratings += got
            if what:
                print(f"  {adapter.NAME:8} {what:8} {len(rows):6} rows  {name}")
                break
        else:
            print(f"  skipped  (unrecognized columns)  {name}")
    return views, ratings


def summarize_ratings(rs):
    """Average the latest rating per profile into (label, score, detail)."""
    if not rs:
        return "", "", ""
    score = sum(r["score"] for r in rs) / len(rs)
    detail = "; ".join(f"{r['profile'] or r['source']}: {r['desc']} ({r['date']})" for r in rs)
    return label_for(score), f"{score:.2f}", detail


def main():
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--staging", type=Path, default=root / "data" / "staging")
    ap.add_argument("--out", type=Path, default=root / "data" / "normalized")
    ap.add_argument("--profile", action="append", default=[],
                    help="only keep this Netflix profile (repeatable); default keeps every profile")
    ap.add_argument("--min-minutes", type=float, default=20,
                    help="a Netflix-only movie watched for less than this in total, and not rated, counts as "
                         "sampled and goes to extras.csv (default 20)")
    args = ap.parse_args()

    staging = args.staging
    if not staging.exists():
        legacy = root / "data" / "watch-history.csv"
        if not legacy.exists():
            sys.exit(f"No staging folder at {staging}. Put your exports in data/staging/ (see data/README.md).")
        print(f"No {staging}; using the older layout's {legacy}")
        # Only the Amazon file; data/ also holds this script's own outputs
        views, ratings = list(amazon.views(csv.DictReader(open(legacy, encoding="utf-8-sig")))), []
    else:
        print(f"Reading {staging}")
        views, ratings = load(staging)
    if not views:
        sys.exit("No watch history found in the staging folder.")

    wanted = {p.lower() for p in args.profile}
    if wanted:
        views = [v for v in views if not v["profile"] or v["profile"].lower() in wanted]
        ratings = [r for r in ratings if r["profile"].lower() in wanted]

    movies = defaultdict(lambda: {"variants": defaultdict(int), "years": set(), "editions": set(),
                                  "sources": set(), "ids": [], "dates": [], "minutes": 0.0, "views": 0,
                                  "profiles": set(), "basis": set(),
                                  "verify": True, "first_row": 10 ** 9, "ratings": []})
    shows = defaultdict(lambda: {"variants": defaultdict(int), "seasons": set(), "episodes": set(),
                                 "sources": set(), "dates": [], "views": 0, "profiles": set(), "basis": set(),
                                 "ratings": []})
    extras = []

    for v in views:
        if v["kind"] == "extra":
            extras.append(v)
        elif v["kind"] == "movie" and key(v["title"]):
            m = movies[key(v["title"])]
            m["variants"][v["title"]] += 1
            if v["year"]:
                m["years"].add(v["year"])
            m["editions"].update(v["editions"])
            m["sources"].add(v["source"])
            if v["source_id"] and v["source_id"] not in m["ids"]:
                m["ids"].append(v["source_id"])
            if v["date"]:
                m["dates"].append(v["date"])
            m["minutes"] += v["minutes"]
            m["views"] += 1
            if v["profile"]:
                m["profiles"].add(v["profile"])
            m["basis"].add(v["type_basis"])
            m["verify"] &= v["verify"]  # a service that states the type (Amazon) settles it
            m["first_row"] = min(m["first_row"], v["row"])
        elif v["kind"] == "episode":
            s = shows[key(v["show"]) or key(v["raw_title"])]
            s["variants"][v["show"]] += 1
            if v["season"]:
                s["seasons"].add(v["season"])
            s["episodes"].add(v["episode"])
            s["sources"].add(v["source"])
            if v["date"]:
                s["dates"].append(v["date"])
            s["views"] += 1
            if v["profile"]:
                s["profiles"].add(v["profile"])
            s["basis"].add(v["type_basis"])

    # Movies only Netflix saw, for a few minutes, with no rating: sampled, not watched
    rated = {key(r["title"]) for r in ratings if normalize_rating(r["scale"], r["value"])}
    for k, m in list(movies.items()):
        if m["sources"] == {"netflix"} and m["minutes"] < args.min_minutes and k not in rated:
            extras.append({"source": "netflix", "row": m["first_row"], "raw_title": pick_display(m["variants"]),
                           "reason": f"sampled: {m['minutes']:.0f} min watched", "profile": "|".join(sorted(m["profiles"])),
                           "date": max(m["dates"], default="")})
            del movies[k]

    # Ratings: keep each profile's latest rating per title, then attach to a movie, a show, or a new
    # rated-only row (a title rated but not in the viewing history; TMDB decides whether it is a film).
    latest = {}
    for r in ratings:
        k = (r["source"], r["profile"], key(r["title"]))
        if k not in latest or r["date"] > latest[k]["date"]:
            latest[k] = r
    rating_rows = []
    for r in ratings:
        norm = normalize_rating(r["scale"], r["value"])
        is_latest = latest[(r["source"], r["profile"], key(r["title"]))] is r
        k = key(r["title"])
        if not k:  # a title with no letters or digits ("--") can't be matched to anything
            continue
        target = "movie" if k in movies else "tv" if k in shows else "rated only" if norm else ""
        rating_rows.append({**r, "label": norm[0] if norm else "", "score": norm[1] if norm else "",
                            "kept": "yes" if is_latest and norm else "no", "matched_to": target})
        if not (is_latest and norm):
            continue
        entry = {**r, "label": norm[0], "score": norm[1], "desc": norm[2]}
        if k in shows:
            shows[k]["ratings"].append(entry)
            continue
        m = movies[k]
        if not m["sources"]:  # new rated-only row
            m["variants"][r["title"]] += 1
            m["basis"].add(f"rated on {r['source'].title()}, not in viewing history")
        m["ratings"].append(entry)
        if r["profile"]:
            m["profiles"].add(r["profile"])

    args.out.mkdir(parents=True, exist_ok=True)
    with open(args.out / "movies.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "title", "year", "verify_type", "type_basis", "sources", "watch_count", "first_watched",
                    "last_watched", "minutes_watched", "profiles", "rating_label", "rating_score", "ratings",
                    "editions", "title_variants", "source_ids"])
        order = sorted(movies.items(), key=lambda kv: (max(kv[1]["dates"], default=""), -kv[1]["first_row"]),
                       reverse=True)
        for k, m in order:
            w.writerow([k, pick_display(m["variants"]), "|".join(sorted(m["years"])),
                        "yes" if m["verify"] else "no", "|".join(sorted(m["basis"])),
                        "|".join(sorted(m["sources"])), m["views"], min(m["dates"], default=""),
                        max(m["dates"], default=""), round(m["minutes"]) or "", "|".join(sorted(m["profiles"])),
                        *summarize_ratings(m["ratings"]), "|".join(sorted(m["editions"])),
                        "|".join(m["variants"]), "|".join(m["ids"])])

    with open(args.out / "tv_shows.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["show", "sources", "seasons", "episodes_watched", "views", "first_watched", "last_watched",
                    "profiles", "rating_label", "rating_score", "ratings", "type_basis"])
        for s in sorted(shows.values(), key=lambda s: max(s["dates"], default=""), reverse=True):
            w.writerow([pick_display(s["variants"]), "|".join(sorted(s["sources"])),
                        "|".join(sorted(s["seasons"], key=lambda x: (len(x), x))), len(s["episodes"]), s["views"],
                        min(s["dates"], default=""), max(s["dates"], default=""), "|".join(sorted(s["profiles"])),
                        *summarize_ratings(s["ratings"]), "|".join(sorted(s["basis"]))])

    with open(args.out / "extras.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["source", "row", "title", "reason", "profile", "date"])
        for e in extras:
            w.writerow([e["source"], e["row"], e["raw_title"], e["reason"], e.get("profile", ""), e.get("date", "")])

    with open(args.out / "ratings.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["source", "profile", "title", "scale", "raw_value", "label", "score", "date", "kept",
                    "matched_to"])
        for r in rating_rows:
            w.writerow([r["source"], r["profile"], r["raw_title"], r["scale"], r["value"], r["label"], r["score"],
                        r["date"], r["kept"], r["matched_to"]])

    n_rated_only = sum(1 for m in movies.values() if not m["sources"])
    print(f"{len(views)} views, {len(ratings)} ratings -> {len(movies)} movies "
          f"({n_rated_only} rated only, {sum(m['verify'] for m in movies.values())} to confirm on TMDB), "
          f"{len(shows)} shows, {len(extras)} extras -> {args.out}")


if __name__ == "__main__":
    main()

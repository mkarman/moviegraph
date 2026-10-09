#!/usr/bin/env python3
"""
clean_watch_history.py - Turn the Amazon Prime Video watch history export into
clean tables of unique movies and TV shows.

Usage: python clean_watch_history.py [path/to/watch-history.csv] [out_dir]

Writes to out_dir (default: ../data):
  movies_clean.csv   one row per unique movie
  tv_shows.csv       one row per show/season title, with episode counts
  extras.csv         trailers, previews and other non-movie rows tagged "Movie"

The export is assumed to be newest first, so row 1 is the most recent watch.
"""

import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

here = Path(__file__).resolve().parent
csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else here.parent / "data" / "watch-history.csv"
out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else here.parent / "data"

EXTRA_RE = re.compile(r"^Episode \d+:|\btrailer\b|behind the scenes|sneak pea[kc]|first look", re.I)
# Edition/version tags Amazon appends to titles; stripped into an "editions" column.
EDITION_RES = [
    re.compile(r"\s*-?\s*\(?Bonus X-Ray Edition\)?\s*$", re.I),
    re.compile(r"\s*\((4K UHD|English Subtitled|English Dubbed|English dub version|"
               r"Theatrical/Rated Version|Unrated Version|Extended|Non-Interactive|"
               r"DC Showcase Shorts Collection|Not Suitable For Children)\)\s*$", re.I),
    re.compile(r"\s+Special Edition\s*$", re.I),
    re.compile(r":\s*Remastered\s*$", re.I),
]
YEAR_RE = re.compile(r"\s*\(((?:19|20)\d\d)\)\s*$")
SEASON_RE = re.compile(r"\s*(?:[,:-]\s*)?\(?(?:Season\s+|S)(\d+)\)?\s*$", re.I)
DUB_RE = re.compile(r"\s*\((?:English )?(?:Dub|Dubbed|Subtitled)\)\s*$", re.I)


def clean_title(raw):
    title, editions, year = raw.strip(), [], ""
    changed = True
    while changed:
        changed = False
        m = YEAR_RE.search(title)
        if m:
            year, title, changed = m.group(1), title[:m.start()], True
        for rx in EDITION_RES:
            m = rx.search(title)
            if m:
                editions.append(m.group(0).strip(" -:()"))
                title, changed = title[:m.start()], True
    return title.strip(" -"), year, editions


def key(title):
    t = title.lower().replace("’", "'").replace("&", "and")
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def pick_display(variants):
    # Prefer the most frequent spelling, and mixed case over ALL CAPS.
    return max(variants, key=lambda v: (variants[v], not v.isupper()))


rows = list(csv.DictReader(open(csv_path, encoding="utf-8-sig")))
movies = defaultdict(lambda: {"rows": [], "variants": defaultdict(int), "years": set(),
                              "editions": set(), "ids": [], "paths": [], "images": [],
                              "raw_times": []})
shows = defaultdict(lambda: {"rows": [], "variants": defaultdict(int), "episodes": set(),
                             "seasons": set(), "ids": set()})
extras = []

for i, row in enumerate(rows, start=1):
    raw = row["Title"].strip()
    if row["Type"] == "Movie":
        if EXTRA_RE.search(raw):
            extras.append({"row": i, "title": raw, "global_title_id": row["Global Title Identifier"],
                           "path": row["Path"]})
            continue
        title, year, editions = clean_title(raw)
        m = movies[key(title)]
        m["rows"].append(i)
        m["variants"][title] += 1
        if year:
            m["years"].add(year)
        m["editions"].update(editions)
        for field, col in (("ids", "Global Title Identifier"), ("paths", "Path"), ("images", "Image URL")):
            if row[col] not in m[field]:
                m[field].append(row[col])
        m["raw_times"].append(row["Date Watched"])
    else:
        base = DUB_RE.sub("", raw)
        sm = SEASON_RE.search(base)
        show = base[:sm.start()].strip(" ,:-") if sm else base
        show = re.sub(r"\s+S\d+$", "", DUB_RE.sub("", show))
        s = shows[key(show) or key(raw)]
        s["rows"].append(i)
        s["variants"][show or raw] += 1
        if sm:
            s["seasons"].add(int(sm.group(1)))
        s["episodes"].add(row["Episode Global Title Identifier"])
        s["ids"].add(row["Global Title Identifier"])

out_dir.mkdir(parents=True, exist_ok=True)
with open(out_dir / "movies_clean.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["title", "year", "watch_count", "most_recent_row", "earliest_row", "editions",
                "title_variants", "amazon_title_ids", "amazon_paths", "image_url", "date_watched_raw"])
    for m in sorted(movies.values(), key=lambda m: min(m["rows"])):
        w.writerow([pick_display(m["variants"]), "|".join(sorted(m["years"])), len(m["rows"]),
                    min(m["rows"]), max(m["rows"]), "|".join(sorted(m["editions"])),
                    "|".join(m["variants"]), "|".join(m["ids"]), "|".join(m["paths"]),
                    m["images"][0], "|".join(m["raw_times"])])

with open(out_dir / "tv_shows.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["show", "seasons", "episode_rows", "unique_episodes", "most_recent_row",
                "earliest_row", "amazon_title_ids"])
    for s in sorted(shows.values(), key=lambda s: min(s["rows"])):
        w.writerow([pick_display(s["variants"]), "|".join(map(str, sorted(s["seasons"]))),
                    len(s["rows"]), len(s["episodes"]), min(s["rows"]), max(s["rows"]),
                    "|".join(sorted(s["ids"]))])

with open(out_dir / "extras.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["row", "title", "global_title_id", "path"])
    w.writeheader()
    w.writerows(extras)

print(f"{len(rows)} rows -> {len(movies)} unique movies, {len(shows)} show/season titles, "
      f"{len(extras)} extras")

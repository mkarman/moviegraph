"""Amazon Prime Video watch history export (the CSV from the Prime Video watch history page).

Amazon labels every row Movie or Series, so the type is taken as given. Trailers and bonus clips are
tagged "Movie" too, so they are filtered by title. The export has no ratings and no profiles.
"""

import re

from .common import clean_title, parse_date

NAME = "amazon"
COLUMNS = {"Date Watched", "Type", "Title", "Global Title Identifier"}

EXTRA_RE = re.compile(r"^Episode \d+:|\btrailer\b|behind the scenes|sneak pea[kc]|first look", re.I)
SEASON_RE = re.compile(r"\s*(?:[,:-]\s*)?\(?(?:Season\s+|S)(\d+)\)?\s*$", re.I)
DUB_RE = re.compile(r"\s*\((?:English )?(?:Dub|Dubbed|Subtitled)\)\s*$", re.I)


def detect(header):
    return "views" if COLUMNS <= set(header) else None


def views(rows):
    """Yield one view record per row. The export is newest first, so row 1 is the latest watch."""
    for i, row in enumerate(rows, start=1):
        raw = row["Title"].strip()
        base = {"source": NAME, "row": i, "raw_title": raw, "date": parse_date(row.get("Date Watched")),
                "minutes": 0.0, "profile": "", "source_id": row.get("Global Title Identifier", "")}
        if row["Type"] == "Movie":
            if EXTRA_RE.search(raw):
                yield {**base, "kind": "extra", "reason": "trailer or bonus clip"}
                continue
            title, year, editions = clean_title(raw)
            yield {**base, "kind": "movie", "title": title, "year": year, "editions": editions,
                   "type_basis": "Amazon type Movie", "verify": False}
        else:
            show = DUB_RE.sub("", raw)
            sm = SEASON_RE.search(show)
            season = f"Season {sm.group(1)}" if sm else ""
            show = show[:sm.start()].strip(" ,:-") if sm else show
            show = re.sub(r"\s+S\d+$", "", DUB_RE.sub("", show)) or raw
            yield {**base, "kind": "episode", "show": show, "season": season,
                   "episode": row.get("Episode Global Title Identifier") or row.get("Episode Title", ""),
                   "type_basis": "Amazon type Series"}

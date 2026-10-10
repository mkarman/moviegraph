"""Netflix "Download your personal information" export (CONTENT_INTERACTION folder).

ViewingActivity.csv says nothing about whether a title is a movie or a TV episode, so the type is
inferred from the title:

  1. A "Supplemental Video Type" (TRAILER, HOOK, ...) or "(Trailer)" in the title  -> extra
  2. "... (Episode 12)" at the end                                                  -> episode
  3. A middle segment like "Season 2", "Limited Series", "Book 1", "Part 3"
     ("SeaQuest DSV: Season 1: Pilot")                                              -> episode
  4. The whole title is a show name seen in rules 2-3, or ends in "Season N"        -> TV
  5. Anything else                                                                  -> movie candidate

Rule 5 is right for most titles, but a show logged without episode numbers, or a film whose name starts
with a show's name ("Futurama: Into the Wild Green Yonder"), can land on either side, so every Netflix
movie candidate is marked verify=True and enrich_tmdb.py confirms it against TMDB's movie and TV search.

Ratings.csv mixes two scales: 1-5 stars (older) and thumbs (0 unrated, 1 down, 2 up, 3 double up). Star
rows also carry a Thumbs Value that Netflix derived from the stars; the original star value is used.
Star values 0 (deleted), -1 (not interested) and -2 (not seen) carry no opinion and are dropped.
"""

import re

from .common import clean_title, minutes, parse_date

NAME = "netflix"
VIEW_COLUMNS = {"Profile Name", "Start Time", "Duration", "Title"}
RATING_COLUMNS = {"Profile Name", "Title Name", "Rating Type", "Thumbs Value"}
EVENT_COLUMNS = {"Playtraces", "Title Description"}

EPISODE_RE = re.compile(r"\s*\(Episode (\d+)\)\s*$")
TRAILER_RE = re.compile(r"\((?:Official )?(?:Teaser )?Trailer(?: \d+)?\)\s*$|^(?:Season \d+ )?Clip( \d+)?:", re.I)
SEASON_SEG = re.compile(r"^(?:(?:Season|Series|Book|Volume|Vol\.|Part|Chapter|Collection|Temporada|Staffel)"
                        r"\s*[\dIVX]*|Limited Series|Miniseries|Mini-Series|The Complete Series|Collection|"
                        r"Specials?|\d+)$", re.I)
# A season segment that can end a show-level title ("Wednesday: Season 1"). Narrower than SEASON_SEG, since a
# film can end in "Part 1", "Vol. 1", "Chapter 2" or a year ("Fear Street Part 1: 1994").
SHOW_TAIL = re.compile(r"^(?:(?:Season|Series|Temporada|Staffel)\s*\d+|Limited Series|Miniseries|"
                       r"The Complete Series)$", re.I)


def detect(header):
    h = set(header)
    if VIEW_COLUMNS <= h:
        return "views"
    if RATING_COLUMNS <= h:
        return "ratings"
    if EVENT_COLUMNS <= h:
        return "ignored"  # PlaybackRelatedEvents: the same plays as ViewingActivity, only for recent months
    return None


def segments(title):
    return [s.strip() for s in title.split(":")]


def split_episode(title):
    """For an episode title, return (show, season). Some Netflix rows lose the show name (":  1: Episode 4")."""
    segs = segments(title)
    if not segs[0]:
        return "(show name missing in export)", segs[1] if len(segs) > 2 else ""
    for i in range(1, len(segs)):
        if SEASON_SEG.match(segs[i]):
            return ": ".join(segs[:i]), segs[i]
    return segs[0], segs[1] if len(segs) > 2 else ""


def views(rows):
    rows = list(rows)
    # First pass: collect show names from titles that are certainly episodes, for rules 3-4.
    shows = set()
    for row in rows:
        t = row["Title"].strip()
        if row.get("Supplemental Video Type") or TRAILER_RE.search(t):
            continue
        m = EPISODE_RE.search(t)
        segs = segments(t)
        if m or any(SEASON_SEG.match(s) for s in segs[1:-1]):
            shows.add(split_episode(t[:m.start()] if m else t)[0].lower())

    for i, row in enumerate(rows, start=1):
        raw = row["Title"].strip()
        base = {"source": NAME, "row": i, "raw_title": raw, "date": parse_date(row.get("Start Time")),
                "minutes": minutes(row.get("Duration")), "profile": row.get("Profile Name", "").strip(),
                "source_id": ""}
        supp = (row.get("Supplemental Video Type") or "").strip()
        if supp or TRAILER_RE.search(raw):
            yield {**base, "kind": "extra", "reason": (supp or "trailer").lower()}
            continue
        m = EPISODE_RE.search(raw)
        segs = segments(raw)
        if m:
            show, season = split_episode(raw[:m.start()])
            yield {**base, "kind": "episode", "show": show, "season": season, "episode": raw,
                   "type_basis": "title ends in (Episode N)"}
        elif any(SEASON_SEG.match(s) for s in segs[1:-1]):
            show, season = split_episode(raw)
            yield {**base, "kind": "episode", "show": show, "season": season, "episode": raw,
                   "type_basis": "season segment in title"}
        elif raw.lower() in shows or (len(segs) > 1 and SHOW_TAIL.match(segs[-1])):
            show, season = split_episode(raw) if len(segs) > 1 else (raw, "")
            yield {**base, "kind": "episode", "show": show, "season": season, "episode": raw,
                   "type_basis": "title is a show name"}
        else:
            title, year, editions = clean_title(raw)
            basis = (f"no episode marker; '{segs[0]}' is also a show" if segs[0].lower() in shows
                     else "no episode marker")
            yield {**base, "kind": "movie", "title": title, "year": year, "editions": editions,
                   "type_basis": basis, "verify": True}


def ratings(rows):
    for row in rows:
        kind = (row.get("Rating Type") or "").strip().lower()
        if kind == "star":
            scale, value = "stars", row.get("Star Value")
        elif kind == "thumb":
            scale, value = "thumbs", row.get("Thumbs Value")
        else:
            continue
        title, _, _ = clean_title(row["Title Name"])
        yield {"source": NAME, "profile": row.get("Profile Name", "").strip(), "title": title,
               "raw_title": row["Title Name"], "scale": scale, "value": (value or "").strip(),
               "date": parse_date(row.get("Event Utc Ts"))}

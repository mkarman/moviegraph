"""Amazon's own Prime Video data request (Request your data -> Prime Video), the "Prime Video.zip".

Two files in it are used:

  Your Prime Video Viewing Activity/Viewing History.csv   one row per playback session
  Your Prime Video Library & Purchases/Customer Feedback.csv   Like / Dislike / Not Interested per title

Every value in Viewing History.csv is wrapped in an extra pair of quotes ('"Clueless"'), which are removed.
Rows count only when "Material Type Description" is Full or Feature (the main video, as opposed to Promo,
Trailer or Live) and the stream is on demand. Unlike the watch history page export, nothing says whether a
title is a movie or an episode, so the type is read from the title:

  "The Darkness-Foundation - Season 3"     episode name, a hyphen with no spaces, then the show
  "Visitation-Oz Season 5"
  "The Incident-Schitt's Creek"            no season, but the same show follows several episode names
  "Episode 3-Season 1"                     the show's name is missing; grouped like Netflix's missing names

A title counts as an episode when some unspaced hyphen splits it into an episode name and a right-hand side
that names a season or follows two or more different episode names. Everything else is a movie candidate that
enrich_tmdb.py confirms on TMDB, as with Netflix. "Seconds Viewed" gives minutes watched, so a movie only
sampled for a few minutes goes to extras like a Netflix one.

Feedback "Like" and "Dislike" become thumbs up and down; "Not Interested" carries no opinion and is dropped.
The file has no profiles, so Amazon views and ratings have no profile name.
"""

import re
from collections import defaultdict

from .amazon import EXTRA_RE
from .common import clean_title, parse_date

NAME = "amazon"
VIEW_COLUMNS = {"Playback Start Datetime (UTC)", "Seconds Viewed", "Material Type Description", "Title"}
RATING_COLUMNS = {"Entity Type", "Feedback Date", "Feedback Type", "Title Name"}
MAIN_VIDEO = {"full", "feature"}
SEASON_RE = re.compile(r"\s*(?:[-–,:]\s*)?\(?\b(?:Season\s*|S)(\d+)\)?(?:\s*[-–:].*)?$", re.I)
MISSING = "(show name missing in export)"
# Either side of the hyphen giving away an episode: "Pilot-Sea Oak", "Pilot-... : The Complete Series"
EPISODE_NAME = re.compile(r"^(?:Pilot|(?:Episode|Ep\.?|Chapter|Part)\s*\d+)\b", re.I)
SHOW_TAIL = re.compile(r"\b(?:The Complete (?:Series|Collection|\w+ Volume)|Collection|Volume \d+|Vol\. ?\d+)\s*$", re.I)
# Prime Video launched in 2006; earlier playback dates in the export (1987, 1990) are placeholders
FIRST_YEAR = "2006"


def detect(header):
    h = set(header)
    if VIEW_COLUMNS <= h:
        return "views"
    if RATING_COLUMNS <= h:
        return "ratings"
    return None


def unquote(s):
    s = (s or "").strip()
    if len(s) >= 2 and s[0] == s[-1] == '"':
        s = s[1:-1]
    return "" if s in ("Not available", "Not Available") else s.strip()


def splits(title):
    """(episode, show) for every hyphen with no space on either side ("Ep-Show", not "Ep - Show")."""
    return [(title[:i].strip(), title[i + 1:].strip()) for i, c in enumerate(title)
            if c == "-" and 0 < i < len(title) - 1 and not title[i - 1].isspace() and not title[i + 1].isspace()]


def show_and_season(show):
    m = SEASON_RE.search(show)
    return (show[:m.start()].strip(" -–,:"), f"Season {m.group(1)}") if m else (show, "")


def views(rows):
    rows = [r for r in rows if unquote(r.get("Material Type Description")).lower() in MAIN_VIDEO
            and unquote(r.get("Stream Type")) in ("VOD", "")]
    titles = {unquote(r["Title"]) for r in rows}
    # How many different episode names precede each right-hand side, to recognize shows without "Season N"
    names = defaultdict(set)
    for t in titles:
        for ep, show in splits(t):
            names[show_and_season(show)[0].lower()].add(ep.lower())

    def episode(t):
        best = None
        for ep, right in splits(t):
            show, season = show_and_season(right)
            n = len(names[show.lower()])
            if season and not show:  # "Episode 3-Season 1": Amazon left out the show's name
                show = MISSING
            marker = EPISODE_NAME.match(ep) or SHOW_TAIL.search(show)
            if (season or marker or n >= 2) and show and (not best or n > best[0]):
                basis = ("season in title" if season else "episode or collection marker" if marker
                         else f"{n} episodes of '{show}' in history")
                best = (n, ep, show, season, basis)
        return best

    for i, row in enumerate(rows, start=1):
        raw = unquote(row["Title"])
        if not raw:
            continue
        date = parse_date(unquote(row.get("Playback Start Datetime (UTC)")))
        try:
            mins = round(float(unquote(row.get("Seconds Viewed")) or 0) / 60, 1)
        except ValueError:
            mins = 0.0
        base = {"source": NAME, "row": i, "raw_title": raw, "date": date if date >= FIRST_YEAR else "",
                "minutes": mins, "timed": True, "profile": "", "source_id": ""}
        if EXTRA_RE.search(raw):
            yield {**base, "kind": "extra", "reason": "trailer or bonus clip"}
            continue
        ep = episode(raw)
        if ep:
            _, name, show, season, basis = ep
            yield {**base, "kind": "episode", "show": show, "season": season, "episode": name, "type_basis": basis}
        else:
            title, year, editions = clean_title(raw)
            yield {**base, "kind": "movie", "title": title, "year": year, "editions": editions,
                   "type_basis": "no episode marker", "verify": True}


def ratings(rows):
    for row in rows:
        value = {"like": "2", "dislike": "1"}.get(row.get("Feedback Type", "").strip().lower())
        if not value or row.get("Entity Type", "").strip() == "TV Season":
            continue
        title, _, _ = clean_title(row["Title Name"])
        yield {"source": NAME, "profile": "", "title": title, "raw_title": row["Title Name"], "scale": "thumbs",
               "value": value, "date": parse_date(row.get("Feedback Date"))}

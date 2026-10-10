"""Helpers shared by every source adapter: title keys, edition stripping, rating scales, dates."""

import re
from datetime import datetime

# Edition/version tags services append to titles; stripped into an "editions" column.
EDITION_RES = [
    re.compile(r"\s*-?\s*\(?Bonus X-Ray Edition\)?\s*$", re.I),
    re.compile(r"\s*\((4K UHD|English Subtitled|English Dubbed|English dub version|"
               r"Theatrical/Rated Version|Original Theatrical Version|Unrated Version|Extended|Non-Interactive|"
               r"DC Showcase Shorts Collection|Not Suitable For Children)\)\s*$", re.I),
    re.compile(r"\s+Special Edition\s*$", re.I),
    re.compile(r"\s*[:-]\s*(Original Theatrical Version|Director['’]?s Cut|Theatrical (?:and Director['’]?s )?Cut|"
               r"\d+(?:st|nd|rd|th) Anniversary(?: Ultimate| Special)? Edition)\s*$", re.I),
    re.compile(r":\s*(Remastered|International Version|Collector'?s Edition|"
               r"(?:Remix! )?Special (?:Anniversary |Fan )?Edition|Uncensored Extended)\s*$", re.I),
]
YEAR_RE = re.compile(r"\s*\(((?:19|20)\d\d)\)\s*$")


def clean_title(raw):
    """Return (title, year, editions) with edition tags and a trailing "(1985)" removed."""
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
    """Matching key for a title across sources: lowercase, punctuation-free."""
    t = title.lower().replace("’", "'").replace("&", "and")
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def pick_display(variants):
    """Prefer the most frequent spelling, and mixed case over ALL CAPS."""
    return max(variants, key=lambda v: (variants[v], not v.isupper()))


DATE_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%d", "%m/%d/%Y %H:%M", "%m/%d/%Y", "%m/%d/%y %H:%M", "%m/%d/%y")


def parse_date(s):
    """ISO date (YYYY-MM-DD) for a timestamp in any common export format, or "" if unparseable."""
    s = (s or "").strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return ""


def minutes(hms):
    """Netflix duration "01:06:22" -> 66.4 minutes; anything else -> 0."""
    m = re.fullmatch(r"\s*(\d+):(\d\d):(\d\d)\s*", hms or "")
    return round(int(m[1]) * 60 + int(m[2]) + int(m[3]) / 60, 1) if m else 0.0


# ---------- ratings ----------
# Every rating becomes (label, score): label is liked / neutral / disliked, score runs 0 (worst) to 1 (best).
# Stars map linearly (1 -> 0, 5 -> 1). Netflix's own conversion put 3-5 stars under thumbs up and 1-2 under
# thumbs down, so a thumb is scored at the middle of the star range it replaced: down = 1 star, up = 4 stars,
# double up = 5 stars.
STAR_LABEL = {1: "disliked", 2: "disliked", 3: "neutral", 4: "liked", 5: "liked"}
THUMB_SCALE = {1: ("disliked", 0.0, "thumbs down"), 2: ("liked", 0.75, "thumbs up"),
               3: ("liked", 1.0, "double thumbs up")}


def normalize_rating(scale, value):
    """Map one raw rating to (label, score, description), or None when it carries no opinion.

    scale is "stars" (1-5) or "thumbs" (Netflix: 0 unrated, 1 down, 2 up, 3 double up).
    Zero, negative and out-of-range values (deleted, "not interested", "not seen") return None.
    """
    try:
        v = int(float(value))
    except (TypeError, ValueError):
        return None
    if scale == "stars" and 1 <= v <= 5:
        return STAR_LABEL[v], round((v - 1) / 4, 2), f"{v}/5 stars"
    if scale == "thumbs" and v in THUMB_SCALE:
        return THUMB_SCALE[v]
    return None


def label_for(score):
    """Label for an averaged score, using the same cut points as stars (3 stars = 0.5 = neutral)."""
    return "liked" if score >= 0.625 else "disliked" if score <= 0.375 else "neutral"

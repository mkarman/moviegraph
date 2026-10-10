#!/usr/bin/env python3
"""
enrich_tmdb.py - Match watched titles to TMDB and pull genres, directors, cast and keywords.

Usage:
    TMDB_API_KEY=... python scripts/enrich_tmdb.py [--input data/normalized/movies.csv]
                     [--output data/enriched_tmdb.json] [--limit N] [--refresh]

Input is data/normalized/movies.csv from normalize.py, the older data/movies_clean.csv, or a JSON list of
{"id", "title"}. Uses only the standard library. Two TMDB calls per movie: search, then details with credits
and keywords appended.

Rows marked verify_type=yes (Netflix titles, whose export never says movie or TV) also get a TMDB TV search.
If TMDB knows the title as a show and not as a film, or the show has more votes than the film, the row comes
out as matched=false, media_type="tv", so it stays out of the movie graph.

Rows already matched in an earlier --output file are reused by title, so re-running after adding a new
export only calls TMDB for new titles. --refresh ignores the earlier file.
"""

import argparse
import csv
import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

from sources.common import key

API = "https://api.themoviedb.org/3"
KEY = os.environ.get("TMDB_API_KEY")

# Amazon decorations that TMDB titles never carry
NOISE = re.compile(r"\s*[\(\[](4K UHD|UHD|HD|English Dubbed|English Subtitled|Dubbed|Subtitled|Extended Edition|Unrated|Director'?s Cut)[\)\]]", re.I)
# Same decorations without brackets, at the end of the title ("Step Brothers Unrated", "Eurotrip - Unrated")
TRAILING = re.compile(r"\s*[-:]?\s*\b(Unrated|Extended Version|Extended Edition|Director'?s Cut|The Original Classic|Remastered)\s*$", re.I)
# "John Carpenter's The Ward", "William Shakespeare's Romeo + Juliet"
POSSESSIVE = re.compile(r"^[A-Z][\w.]+(?: [A-Z][\w.]+)?['\u2019]s\s+")
# Titles a search cannot get right on its own: Amazon title -> (query, year), a TMDB id, or None for "not on TMDB"
OVERRIDES = {
    "1984": ("Nineteen Eighty-Four", 1984),
    "Monolith": ("Monolith", 2022),  # Mike: the 2022 film, not the 2016 one
    "9 to 5": ("Nine to Five", 1980),  # untested; TMDB id 10771 is The Tuxedo, not this film
    "Kingsman : Services secrets": ("Kingsman: The Secret Service", 2014),
    "Tales From The Crypt: Bordello Of Blood": ("Bordello of Blood", 1996),
    "Brian Posehn: 25x2": None,
    "Mystery Science Theater 3000: Santa Claus": None,
    "Blade Runner: The Final Cut": ("Blade Runner", 1982),
    "Evil Bong 2: Devil's Harvest": ("Evil Bong 2: King Bong", None),
    # Mike: the 2001 horror film. A plain search fuzzy-matches "Thirteen Erotic Ghosts" (2002)
    "Thirteen Ghosts": ("Thir13en Ghosts", 2001),
    "Thir13en Ghosts": ("Thir13en Ghosts", 2001),
}
YEAR = re.compile(r"\s*\((19|20)(\d\d)\)\s*$")
NOT_A_MOVIE = re.compile(r"\btrailer\b|^episode \d+\b|\bbonus\b|\bbehind the scenes\b", re.I)


def get(path, **params):
    params["api_key"] = KEY
    url = f"{API}{path}?{urllib.parse.urlencode(params)}"
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2 ** attempt)
                continue
            if e.code == 404:
                return None
            raise
    raise RuntimeError(f"rate limited on {path}")


def norm(s):
    s = re.sub(r"['\u2019]", "", s)  # "I'm" -> "im" on both sides, not "i m"
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = s.replace("&", "and")
    s = re.sub(r"(?<=[a-z])(?=\d)|(?<=\d)(?=[a-z])", " ", s)  # "Alien³" -> "alien3" -> "alien 3"
    s = re.sub(r"\b(ii|iii|iv)\b", lambda m: str({"ii": 2, "iii": 3, "iv": 4}[m.group(1)]), s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def clean_title(raw):
    """Return (query, year or None, skip_reason or None)."""
    t = TRAILING.sub("", NOISE.sub("", raw)).strip()
    year = None
    m = YEAR.search(t)
    if m:
        year = int(m.group(1) + m.group(2))
        t = t[: m.start()].strip()
    if NOT_A_MOVIE.search(t):
        return t, year, "not a feature film"
    return t, year, None


def pick(results, query, year):
    """Prefer exact (normalized) title matches, then the most-voted one."""
    if not results:
        return None, "no results"
    q = norm(query)
    exact = [r for r in results if norm(r.get("title", "")) == q or norm(r.get("original_title", "")) == q]
    if year:
        dated = [r for r in exact if (r.get("release_date") or "")[:4] == str(year)]
        exact = dated or exact
    if exact:
        best = max(exact, key=lambda r: r.get("vote_count", 0))
        return best, "exact" if len(exact) == 1 else f"exact, chose most-voted of {len(exact)}"
    # No exact hit: accept the top result only if the title is close enough
    top = results[0]
    a, b = set(q.split()), set(norm(top.get("title", "")).split())
    if a and len(a & b) / len(a | b) >= 0.6:
        return top, "fuzzy"
    # Amazon often shortens: "Master And Commander" -> "Master and Commander: The Far Side of the World"
    longer = [r for r in results if norm(r.get("title", "")).startswith(q + " ")]
    if longer:
        return max(longer, key=lambda r: r.get("vote_count", 0)), "title prefix"
    return None, "no confident match"


def tv_match(query):
    """The most-voted TMDB show whose name matches the query exactly, or None."""
    q = norm(query)
    res = (get("/search/tv", query=query, include_adult="false") or {}).get("results", [])
    exact = [r for r in res if q in (norm(r.get("name", "")), norm(r.get("original_name", "")))]
    return max(exact, key=lambda r: r.get("vote_count", 0)) if exact else None


def check_tv(query, hit, how):
    """For a title of unknown type: the TMDB show it really is, or None if the movie match stands."""
    strong = hit is not None and (how.startswith("exact") or how == "manual override")
    tv = tv_match(query)
    if not tv and not hit and ":" in query:  # "Mystery Science Theater 3000: Soultaker" is an episode of a show
        tv = tv_match(query.split(":", 1)[0].strip())
    if tv and (not strong or tv.get("vote_count", 0) > hit.get("vote_count", 0)):
        return tv
    return None


def enrich(m):
    query, year, skip = clean_title(m["title"])
    year = year or (int(m["year"]) if str(m.get("year") or "").isdigit() else None)
    override = m["title"] in OVERRIDES
    fixed = OVERRIDES.get(m["title"])
    if isinstance(fixed, tuple):
        query, year = fixed
    out = {"id": m["id"], "title": m["title"], "source_title": m["title"], "query": query, **history(m)}
    verify = m.get("verify_type") == "yes"
    if skip:
        return {**out, "matched": False, "status": skip}
    if override and fixed is None:
        return {**out, "matched": False, "status": "manual override: not on TMDB"}
    if isinstance(fixed, int):
        return details(out, fixed, "manual override")
    params = {"query": query, "include_adult": "false"}
    if year:
        params["year"] = year
    hit, how = pick(get("/search/movie", **params).get("results", []), query, year)
    if not hit and POSSESSIVE.match(query):
        sub = POSSESSIVE.sub("", query)
        hit, how = pick(get("/search/movie", query=sub).get("results", []), sub, year)
    if not hit and ":" in query:
        head, tail = (x.strip() for x in query.split(":", 1))
        # "Series: Special" often lists under the part after the colon, but only keep that hit if its
        # title still names the series, so "Evil Bong 2: Devil's Harvest" can't land on Devil's Harvest.
        hit, how = pick(get("/search/movie", query=tail).get("results", []), tail, year)
        if hit and not set(norm(head).split()) & set(norm(hit.get("title", "")).split()):
            hit, how = None, "no confident match"
        elif hit:
            how = f"after colon, {how}"
        if not hit:  # "Highlander: The Movie" -> "Highlander"; exact only, a fuzzy hit here is usually another film
            hit, how = pick(get("/search/movie", query=head).get("results", []), head, year)
            if hit and not how.startswith("exact"):
                hit, how = None, "no confident match"
            elif hit:
                how = f"before colon, {how}"
    if hit and override:
        how = "manual override"
    if verify and not override:
        tv = check_tv(query, hit, how)
        if tv:
            return {**out, "matched": False, "media_type": "tv", "tmdb_tv_id": tv["id"],
                    "status": f"TV show on TMDB: {tv.get('name')} ({(tv.get('first_air_date') or '')[:4]})"}
    if not hit:
        return {**out, "matched": False, "status": how}
    return details(out, hit["id"], how)


# Viewing history and rating fields from normalize.py, carried through to the graph
HISTORY = ["sources", "type_basis", "watch_count", "first_watched", "last_watched", "minutes_watched",
           "profiles", "rating_label", "rating_score", "ratings"]


def history(m):
    out = {}
    for f in HISTORY:
        v = m.get(f)
        if v in (None, ""):
            continue
        if f in ("sources", "profiles"):
            v = v.split("|") if isinstance(v, str) else v
        elif f in ("rating_score",):
            v = float(v)
        elif f in ("watch_count", "minutes_watched") and str(v).isdigit():
            v = int(v)
        out[f] = v
    return out


def load_cache(path):
    """Earlier enrichment results by title key; only rows worth keeping (matched, or known to be TV)."""
    try:
        rows = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    cache = {}
    for r in rows:
        if r.get("matched") or r.get("media_type") == "tv":
            for t in (r.get("source_title"), r.get("amazon_title")):
                if t:
                    cache[key(t)] = r
    return cache


def from_cache(cache, m):
    variants = [m["title"], *(m.get("title_variants") or "").split("|")]
    for t in variants:
        r = cache.get(key(t)) if t else None
        # Rows from before the TV check carry no media_type; recheck them if this title's type is in doubt
        # An override added after the earlier run must replace whatever that run matched
        if r and m["title"] in OVERRIDES and r.get("status") != "manual override":
            r = None
        if r and (m.get("verify_type") != "yes" or "media_type" in r):
            tmdb = {k: v for k, v in r.items() if k not in HISTORY and k not in ("id", "amazon_title")}
            return {**tmdb, "id": m["id"], "source_title": m["title"], **history(m)}
    return None


def details(out, tmdb_id, how):
    d = get(f"/movie/{tmdb_id}", append_to_response="credits,keywords")
    crew = d["credits"]["crew"]
    # Flat fields match what graph/build_graph.py reads
    return {
        **out,
        "status": how,
        "matched": True,
        "media_type": "movie",
        **{
            "tmdb_id": d["id"],
            "imdb_id": d.get("imdb_id"),
            "title": d["title"],
            "year": (d.get("release_date") or "")[:4] or None,
            "genres": [g["name"] for g in d["genres"]],
            "directors": [c["name"] for c in crew if c["job"] == "Director"],
            "writers": [c["name"] for c in crew if c["department"] == "Writing"],
            "cast": [c["name"] for c in d["credits"]["cast"][:10]],
            "keywords": [k["name"] for k in d["keywords"]["keywords"]],
            "runtime": d.get("runtime"),
            "rating": d.get("vote_average"),
            "votes": d.get("vote_count"),
            "poster_path": d.get("poster_path"),
        },
    }


def main():
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser()
    default_input = root / "data" / "normalized" / "movies.csv"
    if not default_input.exists() and (root / "data" / "movies_clean.csv").exists():
        default_input = root / "data" / "movies_clean.csv"
    ap.add_argument("--input", default=default_input)
    ap.add_argument("--output", default=root / "data" / "enriched_tmdb.json")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--refresh", action="store_true", help="ignore earlier results in --output")
    args = ap.parse_args()

    path = Path(args.input)
    if path.suffix == ".csv":
        movies = [{**r, "id": r.get("id") or r.get("amazon_title_ids") or r["title"]} for r in csv.DictReader(open(path, encoding="utf-8"))]
    else:
        movies = json.load(open(path, encoding="utf-8"))
    movies = movies[: args.limit]
    cache = {} if args.refresh else load_cache(args.output)
    rows, todo = [], []
    for m in movies:
        hit = from_cache(cache, m)
        rows.append(hit)
        if not hit:
            todo.append(len(rows) - 1)
    print(f"{len(movies) - len(todo)} titles reused from {args.output}, {len(todo)} to look up", file=sys.stderr)
    if todo and not KEY:
        sys.exit("Set TMDB_API_KEY")
    for n, i in enumerate(todo, 1):
        m = movies[i]
        try:
            rows[i] = enrich(m)
        except Exception as e:
            rows[i] = {"id": m["id"], "title": m["title"], "source_title": m["title"], "matched": False,
                       "status": f"error: {e}", **history(m)}
        if n % 50 == 0:
            print(f"{n}/{len(todo)}", file=sys.stderr)
        time.sleep(0.05)

    json.dump(rows, open(args.output, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    matched = sum(1 for r in rows if r["matched"])
    tv = sum(1 for r in rows if r.get("media_type") == "tv")
    print(f"Matched {matched}/{len(rows)} ({matched / max(len(rows), 1):.0%}), {tv} turned out to be TV shows "
          f"-> {args.output}")
    for r in rows:
        if not r["matched"] and r.get("media_type") != "tv":
            print(f"  unmatched: {r['title']}  [{r['status']}]")


if __name__ == "__main__":
    main()

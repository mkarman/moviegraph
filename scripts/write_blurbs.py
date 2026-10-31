#!/usr/bin/env python3
"""
write_blurbs.py - Write a one-line "tasting note" for each movie, for the menu builder's preview.

Usage:
    ANTHROPIC_API_KEY=... python scripts/write_blurbs.py [--input data/enriched_tmdb.json]
                          [--output data/blurbs.json] [--limit N] [--refresh] [--model claude-opus-5-5]

Each note describes the film as if it were a dish on a tasting menu, in the voice of the Osteria del Brivido
horror menu ("Seven schoolgirls and a country house with an appetite, served in candy colours."). Claude writes
them from the TMDB title, year, director, genres, keywords, lead cast and overview, twenty movies per request.

Notes are saved to --output as {tmdb_id: note} after every request, and movies that already have one are
skipped, so re-running after a new export only writes notes for the new films and an interrupted run picks up
where it stopped. --refresh rewrites them all. graph/build_graph.py and scripts/export_site.py read this file.

Needs the anthropic package (pip install anthropic) and an API key; the rest of the pipeline does not.
"""

import argparse
import json
import sys
from pathlib import Path

BATCH = 20
SYSTEM = """You write the dish descriptions on a tasting menu where every dish is a movie.

For each movie you get, write one line in that voice: the film described as a plate of food, wry and a little \
glib, naming its real ingredients (setting, premise, tone, a signature image) as if they were what's on the plate. \
Stay true to the actual film: no invented plot, and no ending spoilers or twist reveals.

Rules for every line:
- One sentence, 8 to 18 words, ending with a full stop.
- Don't repeat the title, and don't name the director or cast unless the name is part of the joke.
- Vary the cooking verbs and structure across the batch; don't start every line the same way.
- If you don't recognise a film and the details given are too thin to be accurate, describe only what the \
details support rather than guessing.

Examples of the voice:
- Suspiria (1977): Seven schoolgirls and a country house with an appetite, served in candy colours.
- A Nightmare on Elm Street: A striped sweater, a bladed glove, and dreams best taken before bedtime.
- The Lost Boys: Boardwalk vampires and a saxophone solo, finished with holy water and garlic.
- The Lair of the White Worm: Derbyshire folklore and a serpent goddess, flambéed in Ken Russell camp.

Return one entry per movie, keeping each movie's id exactly as given."""
SCHEMA = {
    "type": "object",
    "properties": {
        "notes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "note": {"type": "string"}},
                "required": ["id", "note"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["notes"],
    "additionalProperties": False,
}


def films(rows):
    """One entry per TMDB film, skipping TV shows and unmatched titles."""
    seen = {}
    for r in rows:
        if r.get("matched") and r.get("media_type") != "tv" and r.get("tmdb_id"):
            seen.setdefault(str(r["tmdb_id"]), r)
    return seen


def describe(tmdb_id, r):
    """The details Claude sees for one film."""
    d = {"id": tmdb_id, "title": r["title"], "year": r.get("year"), "directors": (r.get("directors") or [])[:2],
         "genres": r.get("genres") or [], "keywords": (r.get("keywords") or [])[:12], "cast": (r.get("cast") or [])[:3]}
    if r.get("overview"):
        d["overview"] = r["overview"]
    return {k: v for k, v in d.items() if v}


def request(client, model, batch):
    """Ask Claude for notes on one batch; returns {id: note} for the ids it was given."""
    response = client.beta.messages.create(
        model=model,
        max_tokens=16000,
        system=SYSTEM,
        messages=[{"role": "user", "content": json.dumps(batch, ensure_ascii=False)}],
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        # On a safety decline, rerun the request on Anthropic's recommended fallback model instead of failing
        betas=["server-side-fallback-2026-07-01"],
        extra_body={"fallbacks": "default"},
    )
    if response.stop_reason == "refusal":
        return {}
    text = next(b.text for b in response.content if b.type == "text")
    wanted = {m["id"] for m in batch}
    return {n["id"]: n["note"].strip() for n in json.loads(text)["notes"] if n["id"] in wanted and n["note"].strip()}


def main():
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--input", default=root / "data" / "enriched_tmdb.json")
    ap.add_argument("--output", default=root / "data" / "blurbs.json")
    ap.add_argument("--limit", type=int, help="write at most this many new notes")
    ap.add_argument("--refresh", action="store_true", help="rewrite notes that already exist")
    ap.add_argument("--model", default="claude-opus-5-5")
    args = ap.parse_args()

    out = Path(args.output)
    notes = {} if args.refresh or not out.exists() else json.loads(out.read_text(encoding="utf-8"))
    todo = [describe(i, r) for i, r in films(json.loads(Path(args.input).read_text(encoding="utf-8"))).items()
            if i not in notes]
    todo = todo[: args.limit]
    print(f"{len(notes)} notes already in {out}, {len(todo)} to write", file=sys.stderr)
    if not todo:
        return
    try:
        import anthropic
    except ImportError:
        sys.exit("write_blurbs.py needs the anthropic package: pip install anthropic")
    client = anthropic.Anthropic()  # ANTHROPIC_API_KEY, or an `ant auth login` profile

    missed = []
    for start in range(0, len(todo), BATCH):
        batch = todo[start:start + BATCH]
        try:
            got = request(client, args.model, batch)
        except anthropic.AuthenticationError:
            sys.exit("The Anthropic API rejected the key: set ANTHROPIC_API_KEY")
        except anthropic.APIError as e:  # keep what's written so far; a re-run retries this batch
            print(f"  batch {start // BATCH + 1} failed: {e}", file=sys.stderr)
            got = {}
        notes.update(got)
        missed += [m["title"] for m in batch if m["id"] not in got]
        out.write_text(json.dumps(notes, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"{min(start + BATCH, len(todo))}/{len(todo)}", file=sys.stderr)
    print(f"{len(notes)} notes -> {out}")
    if missed:
        print(f"  no note for {len(missed)} (run again to retry): {', '.join(missed[:10])}{' ...' if len(missed) > 10 else ''}")


if __name__ == "__main__":
    main()

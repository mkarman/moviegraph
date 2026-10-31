"""local_setup.py - The first-run chores run_pipeline.py does for you: API keys and finding your exports.

Keys. Each key is read from the environment first, then from a `.env` file at the repo root (gitignored),
one `NAME=value` per line. run_pipeline.py asks for a missing TMDB key once and offers to save it there, so
there is no environment variable to set again in every new PowerShell window.

Exports. find_exports() looks through a folder (your Downloads, by default) for the newest Amazon and
Netflix exports, recognized by their columns the same way normalize.py does, and copies them into
data/staging/<service>/. An older export it replaces moves to data/staging_replaced/, which the pipeline never reads.
"""

import csv
import hashlib
import io
import os
import shutil
import time
import zipfile
from pathlib import Path

from sources import amazon, amazon_request, netflix

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
ADAPTERS = [amazon, amazon_request, netflix]

HOW_TO_GET = """\
Where to get your exports (click-by-click steps in docs/getting-your-data.md):
  Netflix  https://www.netflix.com/account/getmyinfo  Submit request, confirm the email, then download the
           .zip from the second email (hours to days later)
  Amazon   https://www.amazon.com/hz/privacy-central/data-requests/preview.html  click Prime Video,
           Submit request, confirm the email, then download "Prime Video.zip" when it's ready (days)
Leave the files in your Downloads folder and run this again with --import (run.cmd does that)."""


# --- keys -------------------------------------------------------------------------------------------------

def read_env(path=ENV_FILE):
    """NAME=value pairs from a .env file (blank lines, # comments, `export ` and quotes allowed)."""
    out = {}
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return out
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.removeprefix("export ").split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[name.strip()] = value
    return out


def load_env(path=ENV_FILE):
    """Copy keys from .env into os.environ, without overriding anything already set there."""
    for name, value in read_env(path).items():
        if value and not os.environ.get(name):
            os.environ[name] = value


def save_env(name, value, path=ENV_FILE):
    """Set one key in .env, keeping the file's other lines."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    lines = [ln for ln in lines if ln.strip().removeprefix("export ").split("=", 1)[0].strip() != name]
    lines.append(f"{name}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --- exports ----------------------------------------------------------------------------------------------

def _kinds(header):
    """{(service, kind)} that one CSV header provides, e.g. {("netflix", "views")}."""
    for adapter in ADAPTERS:
        what = adapter.detect(header)
        if what and what != "ignored":
            return {(adapter.NAME, what)}
    return set()


def _header(text):
    return next(csv.reader(io.StringIO(text)), [])


def provides(path):
    """What a .csv or .zip file holds, judged by the first line of each CSV in it. Unreadable files give {}."""
    try:
        if path.suffix.lower() == ".csv":
            with open(path, encoding="utf-8-sig", newline="") as f:
                return _kinds(_header(f.readline()))
        if path.suffix.lower() == ".zip":
            found = set()
            with zipfile.ZipFile(path) as z:
                for name in z.namelist():
                    if name.lower().endswith(".csv"):
                        with z.open(name) as f:
                            found |= _kinds(_header(f.readline().decode("utf-8-sig", "replace")))
            return found
    except (OSError, UnicodeDecodeError, zipfile.BadZipFile):
        pass
    return set()


def staged(staging):
    """{path: provides(path)} for every recognized export already in the staging folder."""
    if not staging.exists():
        return {}
    return {p: k for p in sorted(staging.rglob("*")) if p.is_file() and (k := provides(p))}


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def find_exports(folder, staging, log=print):
    """Copy the newest export per service from `folder` into staging. Returns how many files were copied.

    Only the top level of `folder` is searched, plus one level of subfolders, so a Downloads folder full of
    unrelated files stays quick. Exports are full histories, so the newest one per service is all you need;
    an older copy of the same service in staging is moved aside rather than merged, which would count every
    view twice.
    """
    folder = Path(folder).expanduser()
    if not folder.is_dir():
        log(f"  No folder at {folder}")
        return 0
    candidates = [p for pattern in ("*", "*/*") for p in folder.glob(pattern)
                  if p.is_file() and p.suffix.lower() in (".csv", ".zip")]
    newest = {}
    for p in candidates:
        kinds = provides(p)
        for service in {s for s, _ in kinds}:
            best = newest.get(service)
            if not best or p.stat().st_mtime > best.stat().st_mtime:
                newest[service] = p
    if not newest:
        log(f"  No Amazon or Netflix export found in {folder}")
        return 0

    already = staged(staging)
    home = staging.parent
    copied = 0
    for service, src in sorted(newest.items()):
        new_kinds = provides(src)
        same = [p for p, k in already.items() if p.stat().st_size == src.stat().st_size and _digest(p) == _digest(src)]
        if same:
            log(f"  {service:8} already staged: {same[0].relative_to(home)}")
            continue
        aside = home / "staging_replaced" / time.strftime("%Y%m%d-%H%M%S")
        for old, kinds in already.items():
            if not kinds & new_kinds:
                continue
            if kinds <= new_kinds:
                aside.mkdir(parents=True, exist_ok=True)
                shutil.move(str(old), str(aside / old.name))
                log(f"  {service:8} moved older {old.relative_to(home)} to {aside.relative_to(home)}")
            else:
                # e.g. a staged Netflix .zip (views and ratings) and a new loose ViewingActivity.csv
                log(f"  {service:8} WARNING: {old.relative_to(home)} overlaps the new file and was kept; "
                    "remove it if it is an older copy, or its views count twice")
        dest = staging / service / src.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        copied += 1
        log(f"  {service:8} copied {src} -> {dest.relative_to(home)}")
    return copied

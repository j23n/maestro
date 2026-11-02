#!/usr/bin/env python3
"""Builds what the app bundles: each language's content.sqlite and starter packs (make content).

    python3 tools/build_content.py --mode full|auto|sample --out App/Resources/Content

Each language goes into its own folder, <out>/<lang>/content.sqlite and <out>/<lang>/packs/ (HANDOFF.md
5.3), and --language picks it (Italian by default). The app bundles every language folder it finds;
`make content` runs this once for each language the app ships.

full    downloads the language's kaikki.org dump (tools/content-sources.txt) unless it's cached in
        .build/content-sources, and fails if it can't. TestFlight archives use this.
auto    uses the cached dump when there is one, else the language's small sample in tools/tests/fixtures,
        so a quick build never waits for a 700 MB download.
sample  always the sample.

Skips the build when its inputs haven't changed since the last one (.build/content-<lang>.stamp).
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FIXTURES = os.path.join(ROOT, "tools", "tests", "fixtures")
# The languages this script can build, each from content/<lang>/, with the sample dictionary each falls
# back to, the name its dump is cached under, and the kaikki.org source names it downloads from.
SAMPLES = {"it": os.path.join(FIXTURES, "kaikki-sample.jsonl"), "de": os.path.join(FIXTURES, "kaikki-sample-de.jsonl")}
CACHE_NAMES = {"it": "kaikki-italian", "de": "kaikki-german"}
SOURCE_NAMES = {"it": "kaikki", "de": "kaikki-de"}
LANGUAGES = tuple(SAMPLES)


def sources() -> list[tuple[str, str]]:
    out = []
    with open(os.path.join(ROOT, "tools", "content-sources.txt"), encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#"):
                name, url = line.split(None, 1)
                out.append((name, url.strip()))
    return out


def download(url: str, dest: str) -> None:
    print(f"downloading {url}", flush=True)
    tmp = dest + ".part"
    with urllib.request.urlopen(url, timeout=120) as resp, open(tmp, "wb") as fh:
        shutil.copyfileobj(resp, fh, length=1 << 20)
    os.replace(tmp, dest)


def filter_language(url: str, dest: str, lang: str) -> None:
    """Streams the all-languages wiktextract dump and keeps the language's entries."""
    print(f"streaming {url} ({lang} entries only)", flush=True)
    tmp = dest + ".part"
    kept = 0
    with urllib.request.urlopen(url, timeout=120) as resp, gzip.open(resp, "rt", encoding="utf-8") as src, \
            gzip.open(tmp, "wt", encoding="utf-8") as out:
        for line in src:
            if f'"lang_code": "{lang}"' not in line and f'"lang_code":"{lang}"' not in line:
                continue
            try:
                if json.loads(line).get("lang_code") != lang:
                    continue
            except ValueError:
                continue
            out.write(line)
            kept += 1
    print(f"kept {kept} {lang} entries", flush=True)
    os.replace(tmp, dest)


def cached_dump(cache: str, lang: str) -> str | None:
    for name in (f"{CACHE_NAMES[lang]}.jsonl", f"{CACHE_NAMES[lang]}.jsonl.gz"):
        path = os.path.join(cache, name)
        if os.path.exists(path) and os.path.getsize(path) > 1_000_000:
            return path
    return None


def fetch(cache: str, lang: str) -> str:
    os.makedirs(cache, exist_ok=True)
    found = cached_dump(cache, lang)
    if found:
        return found
    errors = []
    for name, url in sources():
        try:
            if name == SOURCE_NAMES[lang]:
                dest = os.path.join(cache, f"{CACHE_NAMES[lang]}.jsonl")
                download(url, dest)
                return dest
            if name == "kaikki-all":
                dest = os.path.join(cache, f"{CACHE_NAMES[lang]}.jsonl.gz")
                filter_language(url, dest, lang)
                return dest
        except Exception as exc:  # noqa: BLE001 - report and try the next source
            errors.append(f"{url}: {exc}")
            print(f"warning: {url}: {exc}", file=sys.stderr)
    raise SystemExit("could not download the dictionary dump:\n  " + "\n  ".join(errors))


def inputs_hash(dump: str, language: str) -> str:
    h = hashlib.sha256()
    h.update(dump.encode())
    h.update(str(os.path.getsize(dump)).encode())
    for folder in (f"content/{language}", "content/schema", "tools/maestro_content"):
        base = os.path.join(ROOT, folder)
        for dirpath, _, files in sorted(os.walk(base)):
            for f in sorted(files):
                if f.endswith(".pyc"):
                    continue
                path = os.path.join(dirpath, f)
                h.update(os.path.relpath(path, ROOT).encode())
                with open(path, "rb") as fh:
                    h.update(fh.read())
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["full", "auto", "sample"], default="auto")
    ap.add_argument("--out", default=os.path.join(ROOT, "App", "Resources", "Content"))
    ap.add_argument("--cache", default=os.path.join(ROOT, ".build", "content-sources"))
    ap.add_argument("--language", choices=LANGUAGES, default="it")
    args = ap.parse_args()
    lang = args.language

    sample = SAMPLES[lang]
    if args.mode == "full":
        dump = fetch(args.cache, lang)
    elif args.mode == "auto":
        dump = cached_dump(args.cache, lang) or sample
    else:
        dump = sample
    if dump == sample:
        print("warning: building the app's content from the small sample dictionary "
              "(make content CONTENT=full for the real one)", file=sys.stderr)

    bundle = os.path.abspath(args.out)
    # Content built before languages had folders sat at the top of the bundle; it would be bundled too.
    for name in ("content.sqlite", "packs"):
        path = os.path.join(bundle, name)
        if os.path.isdir(path):
            shutil.rmtree(path)
        elif os.path.exists(path):
            os.remove(path)
    out = os.path.join(bundle, lang)
    stamp = os.path.join(ROOT, ".build", f"content-{lang}.stamp")
    digest = inputs_hash(dump, lang)
    if os.path.exists(os.path.join(out, "content.sqlite")) and os.path.exists(stamp):
        with open(stamp, encoding="utf-8") as fh:
            if fh.read().strip() == digest:
                print(f"content is up to date ({os.path.relpath(out, ROOT)})")
                return 0

    for name in ("content.sqlite", "packs"):
        path = os.path.join(out, name)
        if os.path.isdir(path):
            shutil.rmtree(path)
        elif os.path.exists(path):
            os.remove(path)
    os.makedirs(out, exist_ok=True)

    # A scratch copy of the registry: IDs are only written back by a deliberate --save-ids run.
    cmd = [sys.executable, "-m", "maestro_content", "build", "--language", lang, "--kaikki", dump, "--out", out]
    if dump != sample:
        mtime = os.path.getmtime(dump)
        import datetime as _dt
        cmd += ["--dump-date", _dt.date.fromtimestamp(mtime).isoformat()]
    print(" ".join(cmd), flush=True)
    result = subprocess.run(cmd, cwd=os.path.join(ROOT, "tools"))
    if result.returncode != 0:
        return result.returncode
    os.makedirs(os.path.dirname(stamp), exist_ok=True)
    with open(stamp, "w", encoding="utf-8") as fh:
        fh.write(digest)
    return 0


if __name__ == "__main__":
    sys.exit(main())

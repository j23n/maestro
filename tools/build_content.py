#!/usr/bin/env python3
"""Builds what the app bundles: content.sqlite and the starter packs (make content).

    python3 tools/build_content.py --mode full|auto|sample --out App/Resources/Content

full    downloads the kaikki.org Italian dump (tools/content-sources.txt) unless it's cached in
        .build/content-sources, and fails if it can't. TestFlight archives use this.
auto    uses the cached dump when there is one, else the small sample in tools/tests/fixtures,
        so a quick build never waits for a 700 MB download.
sample  always the sample.

Skips the build when its inputs haven't changed since the last one (.build/content.stamp).
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
SAMPLE = os.path.join(ROOT, "tools", "tests", "fixtures", "kaikki-sample.jsonl")


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


def filter_italian(url: str, dest: str) -> None:
    """Streams the all-languages wiktextract dump and keeps the Italian entries."""
    print(f"streaming {url} (Italian entries only)", flush=True)
    tmp = dest + ".part"
    kept = 0
    with urllib.request.urlopen(url, timeout=120) as resp, gzip.open(resp, "rt", encoding="utf-8") as src, \
            gzip.open(tmp, "wt", encoding="utf-8") as out:
        for line in src:
            if '"lang_code": "it"' not in line and '"lang_code":"it"' not in line:
                continue
            try:
                if json.loads(line).get("lang_code") != "it":
                    continue
            except ValueError:
                continue
            out.write(line)
            kept += 1
    print(f"kept {kept} Italian entries", flush=True)
    os.replace(tmp, dest)


def cached_dump(cache: str) -> str | None:
    for name in ("kaikki-italian.jsonl", "kaikki-italian.jsonl.gz"):
        path = os.path.join(cache, name)
        if os.path.exists(path) and os.path.getsize(path) > 1_000_000:
            return path
    return None


def fetch(cache: str) -> str:
    os.makedirs(cache, exist_ok=True)
    found = cached_dump(cache)
    if found:
        return found
    errors = []
    for name, url in sources():
        try:
            if name == "kaikki":
                dest = os.path.join(cache, "kaikki-italian.jsonl")
                download(url, dest)
                return dest
            if name == "kaikki-all":
                dest = os.path.join(cache, "kaikki-italian.jsonl.gz")
                filter_italian(url, dest)
                return dest
        except Exception as exc:  # noqa: BLE001 - report and try the next source
            errors.append(f"{url}: {exc}")
            print(f"warning: {url}: {exc}", file=sys.stderr)
    raise SystemExit("could not download the dictionary dump:\n  " + "\n  ".join(errors))


def inputs_hash(dump: str) -> str:
    h = hashlib.sha256()
    h.update(dump.encode())
    h.update(str(os.path.getsize(dump)).encode())
    for folder in ("content/texts", "content/grammar", "content/ids", "content/schema", "tools/maestro_content"):
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
    args = ap.parse_args()

    if args.mode == "full":
        dump = fetch(args.cache)
    elif args.mode == "auto":
        dump = cached_dump(args.cache) or SAMPLE
    else:
        dump = SAMPLE
    if dump == SAMPLE:
        print("warning: building the app's content from the small sample dictionary "
              "(make content CONTENT=full for the real one)", file=sys.stderr)

    out = os.path.abspath(args.out)
    stamp = os.path.join(ROOT, ".build", "content.stamp")
    digest = inputs_hash(dump)
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
    cmd = [sys.executable, "-m", "maestro_content", "build", "--kaikki", dump, "--out", out]
    if dump != SAMPLE:
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

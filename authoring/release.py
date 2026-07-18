"""`maestro-pack release` — build the bundle and stamp a release manifest.

Output layout (all under build/release/<version>/):
    <lang>.pack.sqlite      the bundle
    release.json            {language, pack_version, sha256, bytes, items}

Publishing = uploading that directory to any static host (a GitHub
release works). The app's pack manager compares release.json against its
installed version and verifies the sha256 after download.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import yaml

from authoring.build_pack import build


def release(pack_dir: Path, spec_dir: Path, out_root: Path) -> int:
    manifest = yaml.safe_load((pack_dir / "pack.yaml").read_text())
    version = manifest["pack_version"]
    lang = manifest["language"]
    out_dir = out_root / version
    out_dir.mkdir(parents=True, exist_ok=True)
    bundle = out_dir / f"{lang}.pack.sqlite"
    if build(pack_dir, spec_dir, bundle) != 0:
        return 1

    digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
    conn = sqlite3.connect(bundle)
    items = conn.execute("SELECT count(*) FROM items").fetchone()[0]
    conn.close()
    info = {
        "language": lang,
        "pack_version": version,
        "sha256": digest,
        "bytes": bundle.stat().st_size,
        "items": items,
    }
    (out_dir / "release.json").write_text(json.dumps(info, indent=2) + "\n")
    print(f"release {version}: {items} items, sha256 {digest[:12]}… -> {out_dir}")
    return 0


def main() -> int:
    pack_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "packs/it")
    lang = yaml.safe_load((pack_dir / "pack.yaml").read_text())["language"]
    return release(pack_dir, Path("spec") / lang, Path("build/release"))


if __name__ == "__main__":
    raise SystemExit(main())

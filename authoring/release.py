"""`maestro-pack release` — build, sign, and stamp a versioned release.

Output layout (all under build/release/):
    <version>/<lang>.pack.sqlite     the bundle
    <version>/release.json           {language, pack_version, sha256,
                                      bytes, items, tombstones}
    <version>/release.json.sig       ed25519 signature of release.json
    <version>/<lang>.pack.coverage.json   per-spec-cell coverage report
    index.json                       version catalog, newest first

Publishing = uploading build/release/ to any static host (a GitHub
release works). The app's pack manager reads index.json (or a pinned
release.json), verifies the sha256 after download, and verifies the
signature against the public key it ships with.

Signing: ``maestro-pack release keygen`` writes
``keys/release_signing.key`` (private — gitignored) and
``keys/release_signing.pub`` (committed; the app bundles it). Release
refuses to overwrite an existing version without --force, and refuses
to release while an item that existed in the previous release is
missing without a tombstone.
"""

from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import yaml

from authoring.build_pack import build, load_pack_sources

KEY_DIR = Path("keys")
PRIVATE_KEY = KEY_DIR / "release_signing.key"
PUBLIC_KEY = KEY_DIR / "release_signing.pub"


# --------------------------------------------------------------------------
# Signing (ed25519 via the `cryptography` package)


def keygen(key_dir: Path = KEY_DIR) -> Path:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key_dir.mkdir(exist_ok=True)
    priv_path = key_dir / PRIVATE_KEY.name
    pub_path = key_dir / PUBLIC_KEY.name
    if priv_path.exists():
        raise SystemExit(f"{priv_path} already exists — refusing to overwrite")
    key = Ed25519PrivateKey.generate()
    priv_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )
    )
    priv_path.chmod(0o600)
    pub_path.write_bytes(
        base64.b64encode(
            key.public_key().public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw
            )
        )
        + b"\n"
    )
    print(f"wrote {priv_path} (keep private!) and {pub_path} (commit; app bundles it)")
    return pub_path


def sign_bytes(data: bytes, priv_path: Path = PRIVATE_KEY) -> str:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.from_private_bytes(priv_path.read_bytes())
    return base64.b64encode(key.sign(data)).decode()


def verify_bytes(data: bytes, sig_b64: str, pub_path: Path = PUBLIC_KEY) -> bool:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    key = Ed25519PublicKey.from_public_bytes(
        base64.b64decode(pub_path.read_bytes().strip())
    )
    try:
        key.verify(base64.b64decode(sig_b64), data)
        return True
    except InvalidSignature:
        return False


# --------------------------------------------------------------------------
# Release diff (backs `maestro-pack review`'s /release-diff and the
# tombstone guard below)


def latest_release(out_root: Path, lang: str) -> Path | None:
    """Newest released bundle, by semver-ish version directory name."""

    def version_key(p: Path):
        core = p.name.split("-", 1)[0]
        try:
            return tuple(int(x) for x in core.split(".")), p.name
        except ValueError:
            return (0, 0, 0), p.name

    candidates = (
        [
            d / f"{lang}.pack.sqlite"
            for d in out_root.iterdir()
            if d.is_dir() and (d / f"{lang}.pack.sqlite").is_file()
        ]
        if out_root.is_dir()
        else []
    )
    if not candidates:
        return None
    return max(candidates, key=lambda b: version_key(b.parent))


def _bundle_items(bundle: Path) -> dict[str, str]:
    """item id -> payload hash for a built bundle (children included)."""
    conn = sqlite3.connect(bundle)
    rows = conn.execute("SELECT id, item_type, payload FROM items").fetchall()
    answers = {}
    for item_id, answer, canonical in conn.execute(
        "SELECT item_id, answer, is_canonical FROM acceptable_answers ORDER BY answer"
    ):
        answers.setdefault(item_id, []).append((answer, canonical))
    conn.close()
    return {
        item_id: hashlib.sha256(
            json.dumps(
                [item_type, payload, answers.get(item_id, [])], sort_keys=True
            ).encode()
        ).hexdigest()
        for item_id, item_type, payload in rows
    }


def release_diff(pack_dir: Path, spec_dir: Path, released_bundle: Path) -> dict:
    """What would ship vs the given release: added/changed/removed/tombstoned.

    Compares *built* bundles (a temp build of the working tree), so the
    diff reflects exactly what the learner would get, question children
    and all.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        tmp_bundle = Path(td) / "tree.sqlite"
        if build(pack_dir, spec_dir, tmp_bundle) != 0:
            raise ValueError("working tree does not build — fix errors first")
        tree = _bundle_items(tmp_bundle)
    old = _bundle_items(released_bundle)
    tombstoned = {t.item_id for t in load_pack_sources(pack_dir).tombstones}
    return {
        "added": sorted(set(tree) - set(old)),
        "changed": sorted(k for k in set(tree) & set(old) if tree[k] != old[k]),
        "removed": sorted(set(old) - set(tree) - tombstoned),
        "tombstoned": sorted((set(old) - set(tree)) & tombstoned),
    }


# --------------------------------------------------------------------------
# Release


def release(
    pack_dir: Path,
    spec_dir: Path,
    out_root: Path,
    force: bool = False,
    key_path: Path = PRIVATE_KEY,
) -> int:
    manifest = yaml.safe_load((pack_dir / "pack.yaml").read_text())
    version = manifest["pack_version"]
    lang = manifest["language"]
    out_dir = out_root / version
    if out_dir.exists() and not force:
        print(f"ERROR: release {version} already exists (use --force to replace)")
        return 1

    # Tombstone guard: nothing may silently vanish vs the last release.
    previous = latest_release(out_root, lang)
    if previous is not None and previous.parent.name != version:
        removed = release_diff(pack_dir, spec_dir, previous)["removed"]
        if removed:
            for item_id in removed:
                print(
                    f"ERROR: {item_id} was in {previous.parent.name} but is "
                    "gone and not tombstoned"
                )
            return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    bundle = out_dir / f"{lang}.pack.sqlite"
    if build(pack_dir, spec_dir, bundle) != 0:
        return 1

    digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
    conn = sqlite3.connect(bundle)
    items = conn.execute("SELECT count(*) FROM items").fetchone()[0]
    tombstones = conn.execute("SELECT count(*) FROM tombstones").fetchone()[0]
    conn.close()
    info = {
        "language": lang,
        "pack_version": version,
        "schema_version": manifest.get("schema_version", "1"),
        "sha256": digest,
        "bytes": bundle.stat().st_size,
        "items": items,
        "tombstones": tombstones,
    }
    release_json = json.dumps(info, indent=2) + "\n"
    (out_dir / "release.json").write_text(release_json)

    signed = ""
    if key_path.exists():
        (out_dir / "release.json.sig").write_text(
            sign_bytes(release_json.encode(), key_path) + "\n"
        )
        signed = ", signed"
    else:
        print(
            f"note: no signing key at {key_path} — release is UNSIGNED "
            "(run `maestro-pack release keygen`)"
        )

    _update_index(out_root, info)
    print(
        f"release {version}: {items} items, sha256 {digest[:12]}…{signed} -> {out_dir}"
    )
    return 0


def _update_index(out_root: Path, info: dict) -> None:
    """Maintain build/release/index.json: newest-first version catalog."""
    index_file = out_root / "index.json"
    index = (
        json.loads(index_file.read_text()) if index_file.exists() else {"releases": []}
    )
    index["releases"] = [
        r for r in index["releases"] if r["pack_version"] != info["pack_version"]
    ]
    index["releases"].insert(0, info)
    index_file.write_text(json.dumps(index, indent=2) + "\n")


def verify_release(out_dir: Path, pub_path: Path = PUBLIC_KEY) -> int:
    """Check a release directory: digest matches, signature verifies."""
    info = json.loads((out_dir / "release.json").read_text())
    bundle = out_dir / f"{info['language']}.pack.sqlite"
    digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
    if digest != info["sha256"]:
        print(f"ERROR: sha256 mismatch: {digest} != {info['sha256']}")
        return 1
    sig = out_dir / "release.json.sig"
    if not sig.exists():
        print("ERROR: release.json.sig missing (unsigned release)")
        return 1
    if not verify_bytes(
        (out_dir / "release.json").read_bytes(), sig.read_text().strip(), pub_path
    ):
        print("ERROR: signature does not verify")
        return 1
    print(f"release {info['pack_version']} OK: digest + signature verify")
    return 0


def main() -> int:
    pack_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "packs/it")
    lang = yaml.safe_load((pack_dir / "pack.yaml").read_text())["language"]
    return release(pack_dir, Path("spec") / lang, Path("build/release"))


if __name__ == "__main__":
    raise SystemExit(main())

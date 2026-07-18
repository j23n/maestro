"""Release: signing, version index, overwrite guard, tombstone guard, diff."""

import json
import shutil
from pathlib import Path

import pytest
import yaml

from authoring.release import (
    keygen,
    latest_release,
    release,
    release_diff,
    verify_release,
)

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
SPEC_DIR = ROOT / "spec" / "it"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """A tmp pack + tmp cwd so keys/ and build/ stay out of the repo."""
    pack = tmp_path / "pack"
    shutil.copytree(ROOT / "packs" / "it", pack)
    monkeypatch.chdir(tmp_path)
    return pack, tmp_path / "build" / "release"


def _set_version(pack: Path, version: str) -> None:
    manifest = yaml.safe_load((pack / "pack.yaml").read_text())
    manifest["pack_version"] = version
    (pack / "pack.yaml").write_text(yaml.dump(manifest))


def test_release_signs_and_verifies(env, tmp_path):
    pack, out_root = env
    keygen(tmp_path / "keys")
    key = tmp_path / "keys" / "release_signing.key"
    pub = tmp_path / "keys" / "release_signing.pub"

    assert release(pack, SPEC_DIR, out_root, key_path=key) == 0
    out_dir = out_root / "0.1.0-seed"
    assert (out_dir / "release.json.sig").exists()
    assert verify_release(out_dir, pub) == 0

    # Tampering breaks verification.
    info = json.loads((out_dir / "release.json").read_text())
    info["items"] = 9999
    (out_dir / "release.json").write_text(json.dumps(info, indent=2) + "\n")
    assert verify_release(out_dir, pub) == 1


def test_release_unsigned_without_key_and_overwrite_guard(env, tmp_path):
    pack, out_root = env
    assert release(pack, SPEC_DIR, out_root, key_path=tmp_path / "nope.key") == 0
    assert not (out_root / "0.1.0-seed" / "release.json.sig").exists()

    # Same version again: refused without --force.
    assert release(pack, SPEC_DIR, out_root, key_path=tmp_path / "nope.key") == 1
    assert (
        release(pack, SPEC_DIR, out_root, force=True, key_path=tmp_path / "nope.key")
        == 0
    )


def test_index_json_is_a_catalog(env, tmp_path):
    pack, out_root = env
    nokey = tmp_path / "nope.key"
    assert release(pack, SPEC_DIR, out_root, key_path=nokey) == 0
    _set_version(pack, "0.2.0")
    assert release(pack, SPEC_DIR, out_root, key_path=nokey) == 0

    index = json.loads((out_root / "index.json").read_text())
    versions = [r["pack_version"] for r in index["releases"]]
    assert versions == ["0.2.0", "0.1.0-seed"]
    assert latest_release(out_root, "it").parent.name == "0.2.0"


def test_removed_item_requires_tombstone(env, tmp_path):
    pack, out_root = env
    nokey = tmp_path / "nope.key"
    assert release(pack, SPEC_DIR, out_root, key_path=nokey) == 0

    # Delete a drill from the sources, bump the version.
    drills_file = pack / "drills" / "a0_basics.yaml"
    drills = yaml.safe_load(drills_file.read_text())
    removed_id = drills[0]["id"]
    drills_file.write_text(yaml.dump(drills[1:], allow_unicode=True, sort_keys=False))
    _set_version(pack, "0.2.0")

    # Refused: the removed id is not tombstoned.
    assert release(pack, SPEC_DIR, out_root, key_path=nokey) == 1

    (pack / "tombstones.yaml").write_text(
        f"- {{ item_id: {removed_id}, removed_in: 0.2.0, reason: test }}\n"
    )
    assert release(pack, SPEC_DIR, out_root, key_path=nokey) == 0

    diff = release_diff(pack, SPEC_DIR, latest_release(out_root, "it"))
    assert diff == {"added": [], "changed": [], "removed": [], "tombstoned": []}


def test_release_diff_sections(env, tmp_path):
    pack, out_root = env
    nokey = tmp_path / "nope.key"
    assert release(pack, SPEC_DIR, out_root, key_path=nokey) == 0
    released = latest_release(out_root, "it")

    # Change one item, add one item.
    drills_file = pack / "drills" / "a0_basics.yaml"
    drills = yaml.safe_load(drills_file.read_text())
    drills[0]["prompt"] = drills[0]["prompt"] + " (rev)"
    changed_id = drills[0]["id"]
    drills.append(
        {
            "id": "drill.essere_pre.098",
            "item_type": "drill_cloze",
            "cefr_level": "A0",
            "prompt": "Io ___ pronto.",
            "answers": [{"text": "sono", "canonical": True}],
            "evidence": [{"axis": "grammar", "id": "essere_pre", "weight": 1.0}],
        }
    )
    drills_file.write_text(yaml.dump(drills, allow_unicode=True, sort_keys=False))

    diff = release_diff(pack, SPEC_DIR, released)
    assert "drill.essere_pre.098" in diff["added"]
    assert changed_id in diff["changed"]
    assert diff["removed"] == []

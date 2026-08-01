"""Learner problem reports: parsing the export, resolving it against the
pack sources, and the opt-in that takes a reported item out of the build."""

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from authoring.build_pack import build
from authoring.flags import (
    FlagFileError,
    apply_flags,
    format_report,
    load_flags,
    resolve,
)

ROOT = Path(__file__).resolve().parents[2]


def _export(tmp_path, *flags, header='{"maestro_flags":1}') -> Path:
    lines = [header]
    for at, item_id, note in flags:
        lines.append(
            json.dumps(
                {
                    "created_at": at,
                    "payload": {
                        "type": "item_flagged",
                        "item_id": item_id,
                        "note": note,
                        "pack_version": "0.1.0-seed",
                    },
                }
            )
        )
    path = tmp_path / "maestro-flags.jsonl"
    path.write_text("\n".join(lines) + "\n")
    return path


def test_load_rejects_a_backup_file(tmp_path):
    """A learner backup and a flag export are both JSONL; the header is
    what stops one being fed to the other."""
    path = _export(tmp_path, (1, "drill.x", "n"), header='{"maestro_export":1}')
    with pytest.raises(FlagFileError, match="full backup"):
        load_flags(path)


def test_load_rejects_non_flag_events(tmp_path):
    path = tmp_path / "f.jsonl"
    path.write_text(
        '{"maestro_flags":1}\n'
        '{"created_at":1,"payload":{"type":"attempt","item_id":"drill.x"}}\n'
    )
    with pytest.raises(FlagFileError, match="not an item_flagged event"):
        load_flags(path)


def test_timestamp_falls_back_to_the_envelope(tmp_path):
    """record_event doesn't stamp `at` into the payload, so the envelope's
    created_at is the only date a report has."""
    flags = load_flags(_export(tmp_path, (1_700_000_000, "drill.saluti.001", "no")))
    assert flags[0].at == 1_700_000_000
    assert flags[0].when == "2023-11-14"


def test_resolve_pairs_reports_with_their_source(tmp_path):
    flags = load_flags(
        _export(
            tmp_path,
            (1, "drill.saluti.008", "«salve» should count"),
            (2, "drill.saluti.008", "options all look right"),
            (3, "drill.gone.999", "crashed"),
        )
    )
    resolved = resolve(flags, ROOT / "packs" / "it")

    # Loudest first.
    assert resolved[0].item_id == "drill.saluti.008"
    assert len(resolved[0].flags) == 2
    assert resolved[0].path is not None
    assert resolved[0].entry["item_type"] == "drill_multiple_choice"

    stale = next(r for r in resolved if r.item_id == "drill.gone.999")
    assert stale.entry is None and stale.status == "not in pack sources"

    report = format_report(resolved)
    assert "«salve» should count" in report
    assert "accepts: buongiorno" in report


def test_question_subitems_point_at_their_parent(tmp_path):
    """`<parent>.q<n>` ids are generated at build time and have no source
    entry — a report against one has to name the passage to edit."""
    flags = load_flags(_export(tmp_path, (1, "listening.al_bar.001.q1", "no audio")))
    resolved = resolve(flags, ROOT / "packs" / "it")
    assert resolved[0].parent_id == "listening.al_bar.001"
    assert "question of listening.al_bar.001" == resolved[0].status
    assert "edit that item's questions" in format_report(resolved)


def test_apply_flags_takes_the_item_out_of_the_build(tmp_path):
    pack = tmp_path / "pack"
    shutil.copytree(ROOT / "packs" / "it", pack)
    flags = load_flags(
        _export(tmp_path, (1, "drill.saluti.008", "«salve» should count"))
    )
    changed = apply_flags(resolve(flags, pack))
    assert changed == ["drill.saluti.008"]

    entry = next(
        e
        for e in __import__("yaml").safe_load(
            (pack / "drills" / "a0_01_in_aereo.yaml").read_text()
        )
        if e["id"] == "drill.saluti.008"
    )
    assert entry["status"] == "flagged"
    assert "«salve» should count" in entry["review_note"]

    # Flagged builds in neither path — that's what stops it shipping.
    out = tmp_path / "b.sqlite"
    assert build(pack, ROOT / "spec" / "it", out, include_draft=True) == 0
    conn = sqlite3.connect(out)
    n = conn.execute(
        "SELECT count(*) FROM items WHERE id = 'drill.saluti.008'"
    ).fetchone()[0]
    conn.close()
    assert n == 0, "a flagged item must not reach the bundle"

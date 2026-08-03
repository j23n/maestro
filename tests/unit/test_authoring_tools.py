"""generate (file mode) and the review tool, end to end over a tmp pack."""

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from authoring.generate import (
    KINDS,
    build_prompt,
    generate_drills,
    generate_items,
    resolve_scope,
)
from authoring.review import create_app
from authoring.validate_spec import load_spec

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
SPEC = load_spec(ROOT / "spec" / "it")

CANNED_RESPONSE = """\
Here are the items:

```yaml
- item_type: drill_cloze
  cefr_level: A1
  prompt: "Noi ___ (parlare) italiano."
  answers:
    - { text: "parliamo", canonical: true }
  distractor_feedback:
    parlano: "«Parlano» is the *loro* form. With «noi», -are verbs end in -iamo."
  explanation: "Regular -are verbs: noi parliamo."
  evidence:
    - { axis: grammar, id: ind_pres, weight: 1.0 }
- item_type: drill_multiple_choice
  cefr_level: A1
  prompt: "Tu ___ (abitare) a Roma?"
  choices: ["abiti", "abita", "abito"]
  answers:
    - { text: "abiti", canonical: true }
  explanation: "With «tu», -are verbs end in -i: abiti."
  evidence:
    - { axis: grammar, id: ind_pres, weight: 1.0 }
```
"""


def make_tmp_pack(tmp_path: Path) -> Path:
    pack = tmp_path / "pack"
    (pack / "drills").mkdir(parents=True)
    (pack / "pack.yaml").write_text(
        "language: it\npack_version: 0.0.1-test\nschema_version: '0'\n"
    )
    return pack


def test_generate_from_file_drafts_items(tmp_path):
    pack = make_tmp_pack(tmp_path)
    resp = tmp_path / "resp.yaml"
    resp.write_text(CANNED_RESPONSE)

    out = generate_drills(pack, SPEC, "ind_pres", count=2, from_file=resp)
    drafted = yaml.safe_load(out.read_text())
    assert [d["id"] for d in drafted] == ["drill.ind_pres.001", "drill.ind_pres.002"]
    assert all(d["status"] == "draft" for d in drafted)

    # A second batch continues the id sequence instead of colliding.
    generate_drills(pack, SPEC, "ind_pres", count=2, from_file=resp)
    drafted = yaml.safe_load(out.read_text())
    assert drafted[-1]["id"] == "drill.ind_pres.004"


def test_generate_rejects_bad_evidence(tmp_path):
    pack = make_tmp_pack(tmp_path)
    resp = tmp_path / "resp.yaml"
    resp.write_text(CANNED_RESPONSE.replace("id: ind_pres", "id: not_a_gp"))
    with pytest.raises(ValueError, match="unknown grammar id|not_a_gp"):
        generate_drills(pack, SPEC, "ind_pres", count=2, from_file=resp)


def test_build_prompt_mentions_gp_and_existing():
    scope = resolve_scope(SPEC, gp="ind_pres")
    prompt = build_prompt(SPEC, scope, KINDS["drill"], 5, ["Io ___ (parlare) bene."])
    assert "ind_pres" in prompt
    assert "Io ___ (parlare) bene." in prompt
    # The allowed-vocabulary constraint is embedded.
    assert "grazie" in prompt


def test_theme_scope_carries_inventories():
    scope = resolve_scope(SPEC, theme="Ferragosto", level="A1")
    assert scope.slug == "ferragosto"
    prompt = build_prompt(SPEC, scope, KINDS["reading"], 2, [])
    assert "Ferragosto" in prompt
    assert "essere_pre" in prompt  # allowed grammar inventory
    assert "a0_ordinare" in prompt  # allowed function inventory


def test_theme_scope_requires_level():
    with pytest.raises(ValueError, match="--level"):
        resolve_scope(SPEC, theme="Ferragosto")


CANNED_READING = """\
```yaml
- cefr_level: A1
  title: "Ferragosto al mare"
  text: "È il quindici agosto. Anna è al mare con la famiglia."
  glossary:
    ferragosto: "mid-August holiday"
  questions:
    - prompt: "Dove è Anna?"
      answers: [{ text: "al mare", canonical: true }]
  evidence:
    - { axis: grammar, id: essere_pre, weight: 1.0 }
```
"""


def test_generate_reading_with_theme_scope(tmp_path):
    pack = make_tmp_pack(tmp_path)
    resp = tmp_path / "resp.yaml"
    resp.write_text(CANNED_READING)
    scope = resolve_scope(SPEC, theme="Ferragosto", level="A1")
    out = generate_items(pack, SPEC, "reading", scope, 1, from_file=resp)
    drafted = yaml.safe_load(out.read_text())
    assert out.name == "ferragosto.draft.yaml"
    assert drafted[0]["id"] == "reading.ferragosto.001"
    assert drafted[0]["status"] == "draft"


CANNED_VOCAB = """\
```yaml
- cefr_level: A0
  lemma: "caffè"
  front: "il caffè"
  back: "coffee"
  example: "Un caffè, per favore."
  example_gloss: "A coffee, please."
  answers: [{ text: "caffè", canonical: true }]
  evidence:
    - { axis: vocab, id: "caffè", weight: 1.0 }
```
"""


def test_generate_vocab_ids_come_from_lemma(tmp_path):
    pack = make_tmp_pack(tmp_path)
    resp = tmp_path / "resp.yaml"
    resp.write_text(CANNED_VOCAB)
    scope = resolve_scope(SPEC, theme="Ferragosto", level="A0")
    out = generate_items(pack, SPEC, "vocab", scope, 1, from_file=resp)
    drafted = yaml.safe_load(out.read_text())
    assert drafted[0]["id"] == "vocab.caffe"  # accent-stripped slug
    assert drafted[0]["lemma"] == "caffè"

    # Drafting the same lemma again is a duplicate, not a new card.
    with pytest.raises(ValueError, match="already exists"):
        generate_items(pack, SPEC, "vocab", scope, 1, from_file=resp)


CANNED_NO = """\
```yaml
- cefr_level: A0
  lemma: "no"
  front: "no"
  back: no
  example: "No, grazie."
  example_gloss: "No, thank you."
  evidence:
    - { axis: vocab, id: "no", weight: 1.0 }
```
"""


def test_a_drafted_no_stays_a_word(tmp_path):
    """YAML 1.1 reads a bare `no` as boolean false. In an Italian pack it
    is a lemma, a card's English side, a distractor key and an accepted
    answer — and the model writes it unquoted."""
    pack = make_tmp_pack(tmp_path)
    resp = tmp_path / "resp.yaml"
    resp.write_text(CANNED_NO)
    scope = resolve_scope(SPEC, theme="Ferragosto", level="A0")
    out = generate_items(pack, SPEC, "vocab", scope, 1, from_file=resp)
    assert yaml.safe_load(out.read_text())[0]["back"] == "no"


CANNED_LISTENING = """\
```yaml
- cefr_level: A0
  title: "Sull'aereo"
  turns:
    - { speaker: "Assistente", text: "Buongiorno! Acqua?" }
    - { speaker: "Marco", text: "Sì, grazie." }
  questions:
    - prompt: "Che cosa vuole Marco?"
      answers: [{ text: "acqua", canonical: true }]
  evidence:
    - { axis: function, id: a0_salutare, weight: 1.0 }
```
"""


def test_generate_listening_with_scenario_scope(tmp_path):
    pack = make_tmp_pack(tmp_path)
    resp = tmp_path / "resp.yaml"
    resp.write_text(CANNED_LISTENING)
    scope = resolve_scope(SPEC, scenario="a0-01-in-aereo")
    prompt = build_prompt(SPEC, scope, KINDS["listening"], 1, [])
    assert "a0_salutare" in prompt  # scenario functions offered for evidence
    out = generate_items(pack, SPEC, "listening", scope, 1, from_file=resp)
    drafted = yaml.safe_load(out.read_text())
    assert drafted[0]["id"] == "listening.a0_01_in_aereo.001"


CANNED_GRAMMAR_REF = """\
```yaml
- cefr_level: A1
  grammar_id: ind_pres
  title: "The present tense of -are verbs"
  body_md: |
    Regular -are verbs swap -are for personal endings: parlo, parli,
    parla, parliamo, parlate, parlano.
  examples: ["Noi parliamo italiano."]
  evidence:
    - { axis: grammar, id: ind_pres, weight: 0.5 }
```
"""


def test_generate_grammar_ref_keyed_by_gp(tmp_path):
    pack = make_tmp_pack(tmp_path)
    resp = tmp_path / "resp.yaml"
    resp.write_text(CANNED_GRAMMAR_REF)
    scope = resolve_scope(SPEC, gp="ind_pres")
    out = generate_items(pack, SPEC, "grammar_ref", scope, 1, from_file=resp)
    drafted = yaml.safe_load(out.read_text())
    assert drafted[0]["id"] == "grammar_ref.ind_pres"


def test_review_flow_accept_and_reject(tmp_path):
    pack = make_tmp_pack(tmp_path)
    resp = tmp_path / "resp.yaml"
    resp.write_text(CANNED_RESPONSE)
    generate_drills(pack, SPEC, "ind_pres", count=2, from_file=resp)

    client = TestClient(create_app(pack, ROOT / "spec" / "it"))

    # Queue shows both drafts.
    page = client.get("/").text
    assert "drill.ind_pres.001" in page and "drill.ind_pres.002" in page

    # Accept the first item as-is.
    item_page = client.get("/item/drill.ind_pres.001").text
    source = item_page.split("<textarea name=source>")[1].split("</textarea>")[0]
    import html as html_mod

    r = client.post(
        "/item/drill.ind_pres.001",
        data={"action": "accept", "source": html_mod.unescape(source)},
        follow_redirects=False,
    )
    assert r.status_code == 303

    # Reject the second.
    client.post(
        "/item/drill.ind_pres.002",
        data={"action": "reject", "source": ""},
        follow_redirects=False,
    )

    drafts = yaml.safe_load((pack / "drills" / "ind_pres.draft.yaml").read_text())
    assert len(drafts) == 1
    assert drafts[0]["id"] == "drill.ind_pres.001"
    assert drafts[0]["status"] == "reviewed"

    # Accepted item now counts toward coverage, queue is empty.
    assert "Queue empty" in client.get("/").text
    assert "ind_pres" in client.get("/coverage").text


def test_review_covers_all_item_families(tmp_path):
    import shutil

    pack = tmp_path / "pack"
    shutil.copytree(ROOT / "packs" / "it", pack)
    # Demote one non-drill item of each family to draft.
    for subdir in ("readings", "vocab", "speaking_prompts", "tasks"):
        f = next((pack / subdir).glob("*.yaml"))
        entries = yaml.safe_load(f.read_text())
        entries[0]["status"] = "draft"
        f.write_text(yaml.dump(entries, allow_unicode=True, sort_keys=False))

    client = TestClient(create_app(pack, ROOT / "spec" / "it"))
    page = client.get("/").text
    assert "reading." in page and "vocab." in page and "speaking." in page
    # Capstones are the only items that can close a can-do, and the build
    # ships only `reviewed` — a family missing from here can never ship.
    assert "task." in page

    # Accepting a vocab card through the tool works like a drill.
    cards = yaml.safe_load((pack / "vocab" / "a0_basics.yaml").read_text())
    card_id = cards[0]["id"]
    source = yaml.dump([cards[0]], allow_unicode=True, sort_keys=False)
    r = client.post(
        f"/item/{card_id}",
        data={"action": "accept", "source": source},
        follow_redirects=False,
    )
    assert r.status_code == 303 and "error" not in r.headers["location"]
    cards = yaml.safe_load((pack / "vocab" / "a0_basics.yaml").read_text())
    assert cards[0]["status"] == "reviewed"

    # And so does accepting a capstone, which carries fields no other
    # family has (`rubric`, `mode`, an authored `demand`).
    tasks_file = next((pack / "tasks").glob("*.yaml"))
    tasks = yaml.safe_load(tasks_file.read_text())
    r = client.post(
        f"/item/{tasks[0]['id']}",
        data={
            "action": "accept",
            "source": yaml.dump([tasks[0]], allow_unicode=True, sort_keys=False),
        },
        follow_redirects=False,
    )
    assert r.status_code == 303, r.headers.get("location")
    assert "error" not in r.headers["location"], r.headers["location"]
    assert yaml.safe_load(tasks_file.read_text())[0]["status"] == "reviewed"


def test_review_context_panel_and_warnings(tmp_path):
    pack = make_tmp_pack(tmp_path)
    resp = tmp_path / "resp.yaml"
    resp.write_text(CANNED_RESPONSE)
    generate_drills(pack, SPEC, "ind_pres", count=2, from_file=resp)
    client = TestClient(create_app(pack, ROOT / "spec" / "it"))

    page = client.get("/item/drill.ind_pres.001").text
    assert "Spec context" in page
    assert "ind_pres" in page  # the grammar point's own material


def test_review_l1_mode_flags_reviewed_items(tmp_path):
    import shutil

    pack = tmp_path / "pack"
    shutil.copytree(ROOT / "packs" / "it", pack)
    client = TestClient(create_app(pack, ROOT / "spec" / "it"))

    # L1 queue lists reviewed items.
    page = client.get("/?mode=l1").text
    assert "drill.essere_pre.001" in page

    r = client.post(
        "/flag/drill.essere_pre.001",
        data={"note": "sounds unnatural"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    drills = yaml.safe_load((pack / "drills" / "a0_basics.yaml").read_text())
    flagged = next(d for d in drills if d["id"] == "drill.essere_pre.001")
    assert flagged["status"] == "flagged"
    assert flagged["review_note"] == "sounds unnatural"

    # ... which puts it back in the maintainer's queue.
    assert "drill.essere_pre.001" in client.get("/").text


def test_review_coverage_matrix(tmp_path):
    import shutil

    pack = tmp_path / "pack"
    shutil.copytree(ROOT / "packs" / "it", pack)
    client = TestClient(create_app(pack, ROOT / "spec" / "it"))
    page = client.get("/coverage").text
    assert "vocab_card" in page  # family columns
    assert "generate --gp" in page  # thin cells carry the command


def test_review_media_route_serves_and_guards(tmp_path):
    import shutil

    from authoring.audio import generate_audio

    pack = tmp_path / "pack"
    shutil.copytree(ROOT / "packs" / "it", pack)
    generate_audio(pack, "mock")
    client = TestClient(create_app(pack, ROOT / "spec" / "it"))

    ok = client.get("/media/audio/speaking.a0_ordinare.001.wav")
    assert ok.status_code == 200 and ok.content[:4] == b"RIFF"
    assert client.get("/media/../../etc/passwd").status_code == 404

    # The item page embeds the player.
    page = client.get("/item/speaking.a0_ordinare.001?mode=l1").text
    assert "<audio" in page


def test_review_rejects_invalid_edit(tmp_path):
    pack = make_tmp_pack(tmp_path)
    resp = tmp_path / "resp.yaml"
    resp.write_text(CANNED_RESPONSE)
    generate_drills(pack, SPEC, "ind_pres", count=2, from_file=resp)
    client = TestClient(create_app(pack, ROOT / "spec" / "it"))

    bad = "- id: drill.ind_pres.001\n  item_type: drill_cloze\n"  # missing fields
    r = client.post(
        "/item/drill.ind_pres.001",
        data={"action": "accept", "source": bad},
        follow_redirects=False,
    )
    assert r.status_code == 303 and "error=" in r.headers["location"]
    # Item unchanged on disk.
    drafts = yaml.safe_load((pack / "drills" / "ind_pres.draft.yaml").read_text())
    assert drafts[0]["status"] == "draft"

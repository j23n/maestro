"""generate (file mode) and the review tool, end to end over a tmp pack."""

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from authoring.generate import build_prompt, generate_drills
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
    prompt = build_prompt(SPEC, "ind_pres", 5, ["Io ___ (parlare) bene."])
    assert "ind_pres" in prompt
    assert "Io ___ (parlare) bene." in prompt


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
    page = client.get("/").text
    assert "Queue empty" in page
    assert "ind_pres" in page  # coverage row


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

"""Audio + image generation: providers, caching, write-back, embedding."""

import json
import shutil
import sqlite3
from pathlib import Path

import httpx
import pytest
import yaml

from authoring.audio import AzureTts, MockTts, OpenAiTts, generate_audio
from authoring.build_pack import build
from authoring.images import OpenAiImages, generate_images

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def pack(tmp_path):
    dst = tmp_path / "pack"
    shutil.copytree(ROOT / "packs" / "it", dst)
    return dst


# ------------------------------------------------------------------- audio


def test_generate_audio_mock_renders_and_wires_refs(pack):
    n = generate_audio(pack, "mock")
    # 4 dialogue turns + 2 speaking targets + 4 vocab fronts (seed pack).
    assert n >= 8

    # Files exist and are valid RIFF WAVs.
    listening = yaml.safe_load((pack / "listenings" / "a1_basics.yaml").read_text())[0]
    for turn in listening["turns"]:
        assert turn["audio"], turn
        assert (pack / turn["audio"]).read_bytes()[:4] == b"RIFF"

    speaking = yaml.safe_load(
        (pack / "speaking_prompts" / "a0_basics.yaml").read_text()
    )[0]
    assert speaking["audio"] == f"audio/{speaking['id']}.wav"

    # The index makes the second run a no-op.
    assert generate_audio(pack, "mock") == 0
    # ... unless forced.
    assert generate_audio(pack, "mock", force=True) == n


def test_generate_audio_rerenders_on_text_change(pack):
    generate_audio(pack, "mock")
    f = pack / "speaking_prompts" / "a0_basics.yaml"
    entries = yaml.safe_load(f.read_text())
    entries[0]["target_text"] = "Vorrei un tè, per favore."
    f.write_text(yaml.dump(entries, allow_unicode=True, sort_keys=False))

    assert generate_audio(pack, "mock") == 1  # only the changed script


def test_rendered_audio_is_embedded_by_build(pack, tmp_path):
    generate_audio(pack, "mock")
    out = tmp_path / "bundle.sqlite"
    assert build(pack, ROOT / "spec" / "it", out) == 0
    conn = sqlite3.connect(out)
    kinds = dict(
        conn.execute("SELECT kind, count(*) FROM media GROUP BY kind").fetchall()
    )
    # Turn audio is only embedded via reviewed items; all seed items are
    # reviewed, so every rendered file lands.
    assert kinds["audio"] >= 8
    # Payloads point at embedded paths.
    payload = json.loads(
        conn.execute(
            "SELECT payload FROM items WHERE id = 'speaking.a0_ordinare.001'"
        ).fetchone()[0]
    )
    row = conn.execute(
        "SELECT kind FROM media WHERE path = ?", (payload["audio"],)
    ).fetchone()
    conn.close()
    assert row == ("audio",)


def test_openai_tts_request_shape():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["json"] = json.loads(request.content)
        return httpx.Response(200, content=b"ID3fake-mp3")

    client = httpx.Client(
        base_url="https://api.openai.com", transport=httpx.MockTransport(handler)
    )
    tts = OpenAiTts(client=client)
    data = tts.synthesize("Ciao!", "alloy")
    assert data == b"ID3fake-mp3"
    assert captured["url"].endswith("/v1/audio/speech")
    assert captured["json"]["voice"] == "alloy"
    assert captured["json"]["input"] == "Ciao!"


def test_azure_tts_request_shape():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content.decode()
        return httpx.Response(200, content=b"fake-mp3")

    client = httpx.Client(
        base_url="https://westeurope.tts.speech.microsoft.com",
        transport=httpx.MockTransport(handler),
    )
    tts = AzureTts(client=client)
    tts.synthesize("C'è <un> caffè", "it-IT-ElsaNeural")
    assert 'voice name="it-IT-ElsaNeural"' in captured["body"]
    assert "&lt;un&gt;" in captured["body"]  # XML-escaped


def test_mock_wav_is_valid():
    data = MockTts().synthesize("qualsiasi", "mock-a")
    assert data[:4] == b"RIFF" and data[8:12] == b"WAVE"


# ------------------------------------------------------------------ images


def test_generate_images_mock_scenarios_and_writeback(pack):
    n = generate_images(pack, ROOT / "spec" / "it", "mock", targets={"scenarios"})
    assert n == 37  # one per spec scenario
    assert (pack / "images" / "scenarios" / "a0-01-in-aereo.png").read_bytes()[
        :8
    ] == b"\x89PNG\r\n\x1a\n"
    # Cached second run.
    assert (
        generate_images(pack, ROOT / "spec" / "it", "mock", targets={"scenarios"}) == 0
    )


def test_generate_images_vocab_writeback_and_build_embedding(pack, tmp_path):
    generate_images(pack, ROOT / "spec" / "it", "mock", targets={"vocab", "scenarios"})
    cards = yaml.safe_load((pack / "vocab" / "a0_basics.yaml").read_text())
    assert cards[0]["image"] == f"images/vocab/{cards[0]['id']}.png"

    out = tmp_path / "bundle.sqlite"
    assert build(pack, ROOT / "spec" / "it", out) == 0
    conn = sqlite3.connect(out)
    images = [
        r[0]
        for r in conn.execute("SELECT path FROM media WHERE kind = 'image'").fetchall()
    ]
    conn.close()
    # Vocab images via item refs AND scenario art via the conventional path.
    assert f"images/vocab/{cards[0]['id']}.png" in images
    assert "images/scenarios/a0-01-in-aereo.png" in images


def test_openai_images_request_shape():
    import base64

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "gpt-image-1"
        assert "no text" in body["prompt"]
        return httpx.Response(
            200,
            json={"data": [{"b64_json": base64.b64encode(b"fake-png").decode()}]},
        )

    client = httpx.Client(
        base_url="https://api.openai.com", transport=httpx.MockTransport(handler)
    )
    gen = OpenAiImages(client=client)
    assert (
        gen.generate("Simple warm flat illustration, no text: a coffee") == b"fake-png"
    )

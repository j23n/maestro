"""Pre-rendered TTS audio for pack content (`maestro-pack generate-audio`).

The plan's audio pillar (§3: "pack audio pre-rendered at authoring
time"), previously unbuilt. What gets audio:

- listening dialogues: one file per turn (voices alternate by speaker)
- speaking prompts: the model pronunciation of ``target_text``
- vocab cards: the Italian side (``front``)

Files land under ``packs/<lang>/audio/`` and the item YAML is rewritten
to reference them; ``build`` then embeds the bytes into the bundle's
media table. An index (``audio/index.yaml``) records the sha256 of the
rendered text per file, so re-runs only render what changed — flagging
a file for re-render is deleting its index entry (or ``--force``).

Providers (``--provider``):

- ``mock``    valid silent WAVs, offline — tests, demos, plumbing
- ``azure``   Azure neural TTS (env AZURE_SPEECH_KEY + AZURE_SPEECH_REGION)
- ``openai``  OpenAI TTS (env OPENAI_API_KEY)

All providers speak through the same two-voice interface; dialogue
speakers alternate voice A / voice B in order of first appearance.
"""

from __future__ import annotations

import hashlib
import os
import struct
from dataclasses import dataclass
from pathlib import Path

import yaml

_INDEX_NAME = "index.yaml"


# --------------------------------------------------------------------------
# Providers


class MockTts:
    """Writes valid, silent WAV files. Offline; proves the whole pipe."""

    name = "mock"
    ext = "wav"
    voices = ("mock-a", "mock-b")

    def synthesize(self, text: str, voice: str) -> bytes:
        rate, seconds = 8000, 0.2
        n = int(rate * seconds)
        data = b"\x00\x00" * n
        header = struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF",
            36 + len(data),
            b"WAVE",
            b"fmt ",
            16,
            1,  # PCM
            1,  # mono
            rate,
            rate * 2,
            2,
            16,
            b"data",
            len(data),
        )
        return header + data


class OpenAiTts:
    """OpenAI text-to-speech. Needs OPENAI_API_KEY."""

    name = "openai"
    ext = "mp3"
    voices = ("alloy", "onyx")

    def __init__(self, client=None, model: str = "gpt-4o-mini-tts"):
        self.model = model
        if client is None:
            import httpx

            client = httpx.Client(
                base_url="https://api.openai.com",
                headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
                timeout=60,
            )
        self.client = client

    def synthesize(self, text: str, voice: str) -> bytes:
        r = self.client.post(
            "/v1/audio/speech",
            json={
                "model": self.model,
                "voice": voice,
                "input": text,
                "response_format": "mp3",
            },
        )
        r.raise_for_status()
        return r.content


class AzureTts:
    """Azure neural TTS (the plan's pick for bulk it-IT rendering).

    Needs AZURE_SPEECH_KEY + AZURE_SPEECH_REGION.
    """

    name = "azure"
    ext = "mp3"
    voices = ("it-IT-ElsaNeural", "it-IT-DiegoNeural")

    def __init__(self, client=None):
        if client is None:
            import httpx

            region = os.environ["AZURE_SPEECH_REGION"]
            client = httpx.Client(
                base_url=f"https://{region}.tts.speech.microsoft.com",
                headers={
                    "Ocp-Apim-Subscription-Key": os.environ["AZURE_SPEECH_KEY"],
                    "Content-Type": "application/ssml+xml",
                    "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3",
                },
                timeout=60,
            )
        self.client = client

    def synthesize(self, text: str, voice: str) -> bytes:
        ssml = (
            '<speak version="1.0" xml:lang="it-IT">'
            f'<voice name="{voice}">{_xml_escape(text)}</voice></speak>'
        )
        r = self.client.post("/cognitiveservices/v1", content=ssml.encode())
        r.raise_for_status()
        return r.content


def _xml_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


PROVIDERS = {"mock": MockTts, "openai": OpenAiTts, "azure": AzureTts}


# --------------------------------------------------------------------------
# Render planning


@dataclass
class Job:
    """One file to render: which item/field it lands in + the script."""

    path: str  # media path relative to pack_dir (audio/...)
    text: str
    voice_slot: int  # 0 = voice A, 1 = voice B
    subdir: str  # item source dir
    item_id: str
    field: str  # "audio" | "turns[<n>].audio"


def plan_jobs(pack_dir: Path, provider_ext: str) -> list[Job]:
    jobs: list[Job] = []

    def raw_items(subdir: str):
        for f in sorted((pack_dir / subdir).glob("*.yaml")):
            for entry in yaml.safe_load(f.read_text()) or []:
                yield entry

    for entry in raw_items("listenings"):
        speakers: list[str] = []
        for n, turn in enumerate(entry.get("turns", [])):
            if turn["speaker"] not in speakers:
                speakers.append(turn["speaker"])
            jobs.append(
                Job(
                    path=f"audio/{entry['id']}.t{n + 1}.{provider_ext}",
                    text=turn["text"],
                    voice_slot=min(speakers.index(turn["speaker"]), 1),
                    subdir="listenings",
                    item_id=entry["id"],
                    field=f"turns[{n}].audio",
                )
            )
    for entry in raw_items("speaking_prompts"):
        jobs.append(
            Job(
                path=f"audio/{entry['id']}.{provider_ext}",
                text=entry["target_text"],
                voice_slot=0,
                subdir="speaking_prompts",
                item_id=entry["id"],
                field="audio",
            )
        )
    for entry in raw_items("vocab"):
        jobs.append(
            Job(
                path=f"audio/{entry['id']}.{provider_ext}",
                text=entry["front"],
                voice_slot=0,
                subdir="vocab",
                item_id=entry["id"],
                field="audio",
            )
        )
    return jobs


def _load_index(audio_dir: Path) -> dict:
    f = audio_dir / _INDEX_NAME
    return yaml.safe_load(f.read_text()) or {} if f.exists() else {}


def _apply_field(entry: dict, field: str, value: str) -> None:
    if field == "audio":
        entry["audio"] = value
    elif field.startswith("turns["):
        n = int(field[len("turns[") : field.index("]")])
        entry["turns"][n]["audio"] = value
    else:  # pragma: no cover
        raise ValueError(f"unknown field: {field}")


def _write_back(pack_dir: Path, rendered: list[Job]) -> None:
    """Point the item YAML at the rendered files (grouped per file)."""
    by_subdir: dict[str, list[Job]] = {}
    for job in rendered:
        by_subdir.setdefault(job.subdir, []).append(job)
    for subdir, jobs in by_subdir.items():
        for f in sorted((pack_dir / subdir).glob("*.yaml")):
            entries = yaml.safe_load(f.read_text()) or []
            changed = False
            for entry in entries:
                for job in jobs:
                    if entry.get("id") == job.item_id:
                        _apply_field(entry, job.field, job.path)
                        changed = True
            if changed:
                f.write_text(
                    yaml.dump(entries, allow_unicode=True, sort_keys=False, width=88),
                    encoding="utf-8",
                )


def generate_audio(
    pack_dir: Path,
    provider_name: str = "mock",
    force: bool = False,
    voices: tuple[str, str] | None = None,
    client=None,
) -> int:
    """Render all missing/stale audio; returns the number rendered."""
    provider_cls = PROVIDERS[provider_name]
    provider = provider_cls(client=client) if client is not None else provider_cls()
    voice_a, voice_b = voices or provider.voices

    audio_dir = pack_dir / "audio"
    audio_dir.mkdir(exist_ok=True)
    index = _load_index(audio_dir)

    rendered: list[Job] = []
    for job in plan_jobs(pack_dir, provider.ext):
        text_sha = hashlib.sha256(job.text.encode()).hexdigest()
        entry = index.get(job.path)
        up_to_date = (
            not force
            and entry
            and entry.get("text_sha256") == text_sha
            and (pack_dir / job.path).is_file()
        )
        if up_to_date:
            continue
        voice = (voice_a, voice_b)[job.voice_slot]
        data = provider.synthesize(job.text, voice)
        (pack_dir / job.path).write_bytes(data)
        index[job.path] = {
            "text_sha256": text_sha,
            "provider": provider.name,
            "voice": voice,
        }
        rendered.append(job)

    if rendered:
        _write_back(pack_dir, rendered)
        (audio_dir / _INDEX_NAME).write_text(
            yaml.dump(index, allow_unicode=True, sort_keys=True), encoding="utf-8"
        )
    print(f"rendered {len(rendered)} audio file(s) ({provider.name})")
    return len(rendered)

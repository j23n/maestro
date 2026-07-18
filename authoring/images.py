"""Generated illustrations for pack content (`maestro-pack generate-images`).

The audit found images existed only as two dangling ``image:`` refs in
the scenario spec. This is the missing vertical: prompt-built
illustrations for

- scenarios: a scene-setting image per scenario (used by the app's
  narrative framing), path ``images/scenarios/<id>.png``
- vocab cards: a simple illustration per card, ``images/vocab/<id>.png``
- readings: an optional header image, ``images/readings/<id>.png``

Files land under ``packs/<lang>/images/``; vocab/reading item YAML is
rewritten to reference them, while scenario art is picked up purely by
its conventional path (the spec file is never rewritten). ``build``
embeds the bytes into the bundle's media table. ``images/index.yaml``
records the sha256 of each generation prompt so re-runs only render
what changed.

Providers (``--provider``):

- ``mock``    valid 1x1 PNGs, offline — tests, demos, plumbing
- ``openai``  gpt-image-1 (env OPENAI_API_KEY)

Generated images are content like any other draft: they appear in the
review tool next to their item and a human decides if they ship.
"""

from __future__ import annotations

import base64
import hashlib
import os
import zlib
from dataclasses import dataclass
from pathlib import Path

import yaml

_INDEX_NAME = "index.yaml"

STYLE = (
    "Simple warm flat illustration, mediterranean palette, no text, "
    "no letters, no captions. "
)


# --------------------------------------------------------------------------
# Providers


def _minimal_png(rgb: tuple[int, int, int] = (240, 220, 180)) -> bytes:
    """A valid 1x1 PNG, no dependencies."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            len(data).to_bytes(4, "big")
            + tag
            + data
            + zlib.crc32(tag + data).to_bytes(4, "big")
        )

    ihdr = (1).to_bytes(4, "big") + (1).to_bytes(4, "big") + bytes([8, 2, 0, 0, 0])
    idat = zlib.compress(b"\x00" + bytes(rgb))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", idat)
        + chunk(b"IEND", b"")
    )


class MockImages:
    """Valid tiny PNGs, offline; proves the whole pipe."""

    name = "mock"

    def generate(self, prompt: str) -> bytes:
        # Vary the pixel by prompt so re-renders are distinguishable.
        h = hashlib.sha256(prompt.encode()).digest()
        return _minimal_png((h[0], h[1], h[2]))


class OpenAiImages:
    """gpt-image-1. Needs OPENAI_API_KEY."""

    name = "openai"

    def __init__(
        self, client=None, model: str = "gpt-image-1", size: str = "1024x1024"
    ):
        self.model = model
        self.size = size
        if client is None:
            import httpx

            client = httpx.Client(
                base_url="https://api.openai.com",
                headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
                timeout=180,
            )
        self.client = client

    def generate(self, prompt: str) -> bytes:
        r = self.client.post(
            "/v1/images/generations",
            json={"model": self.model, "prompt": prompt, "size": self.size, "n": 1},
        )
        r.raise_for_status()
        return base64.b64decode(r.json()["data"][0]["b64_json"])


PROVIDERS = {"mock": MockImages, "openai": OpenAiImages}


# --------------------------------------------------------------------------
# Generation planning


@dataclass
class Job:
    path: str  # relative to pack_dir (images/...)
    prompt: str
    target: str  # scenario | vocab | reading
    ref_id: str  # scenario id or item id


def plan_jobs(pack_dir: Path, spec_dir: Path, targets: set[str]) -> list[Job]:
    jobs: list[Job] = []

    if "scenarios" in targets:
        scenarios = yaml.safe_load((spec_dir / "scenarios.yaml").read_text()) or []
        for s in scenarios:
            setting = s.get("scene_setting") or s.get("description") or s["label"]
            jobs.append(
                Job(
                    path=f"images/scenarios/{s['id']}.png",
                    prompt=f"{STYLE}Scene: {setting}",
                    target="scenario",
                    ref_id=s["id"],
                )
            )

    def raw_items(subdir: str):
        for f in sorted((pack_dir / subdir).glob("*.yaml")):
            for entry in yaml.safe_load(f.read_text()) or []:
                yield entry

    if "vocab" in targets:
        for entry in raw_items("vocab"):
            jobs.append(
                Job(
                    path=f"images/vocab/{entry['id']}.png",
                    prompt=(
                        f"{STYLE}A single clear object or action: "
                        f"{entry['back']} ({entry['front']})."
                    ),
                    target="vocab",
                    ref_id=entry["id"],
                )
            )
    if "readings" in targets:
        for entry in raw_items("readings"):
            jobs.append(
                Job(
                    path=f"images/readings/{entry['id']}.png",
                    prompt=f"{STYLE}Illustration for: {entry['title']}.",
                    target="reading",
                    ref_id=entry["id"],
                )
            )
    return jobs


def _write_back(pack_dir: Path, spec_dir: Path, rendered: list[Job]) -> None:
    # Scenario art is convention-addressed (images/scenarios/<id>.png,
    # picked up by build when present) — the spec file is never rewritten.
    for target, subdir in (("vocab", "vocab"), ("reading", "readings")):
        jobs = {j.ref_id: j for j in rendered if j.target == target}
        if not jobs:
            continue
        for f in sorted((pack_dir / subdir).glob("*.yaml")):
            entries = yaml.safe_load(f.read_text()) or []
            changed = False
            for entry in entries:
                if entry.get("id") in jobs:
                    entry["image"] = jobs[entry["id"]].path
                    changed = True
            if changed:
                f.write_text(
                    yaml.dump(entries, allow_unicode=True, sort_keys=False, width=88),
                    encoding="utf-8",
                )


def generate_images(
    pack_dir: Path,
    spec_dir: Path,
    provider_name: str = "mock",
    targets: set[str] | None = None,
    force: bool = False,
    client=None,
) -> int:
    """Generate all missing/stale images; returns the number generated."""
    provider_cls = PROVIDERS[provider_name]
    provider = provider_cls(client=client) if client is not None else provider_cls()
    targets = targets or {"scenarios", "vocab", "readings"}

    images_dir = pack_dir / "images"
    images_dir.mkdir(exist_ok=True)
    index_file = images_dir / _INDEX_NAME
    index = yaml.safe_load(index_file.read_text()) or {} if index_file.exists() else {}

    rendered: list[Job] = []
    for job in plan_jobs(pack_dir, spec_dir, targets):
        prompt_sha = hashlib.sha256(job.prompt.encode()).hexdigest()
        entry = index.get(job.path)
        up_to_date = (
            not force
            and entry
            and entry.get("prompt_sha256") == prompt_sha
            and (pack_dir / job.path).is_file()
        )
        if up_to_date:
            continue
        data = provider.generate(job.prompt)
        out = pack_dir / job.path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        index[job.path] = {"prompt_sha256": prompt_sha, "provider": provider.name}
        rendered.append(job)

    if rendered:
        _write_back(pack_dir, spec_dir, rendered)
        index_file.write_text(
            yaml.dump(index, allow_unicode=True, sort_keys=True), encoding="utf-8"
        )
    print(f"generated {len(rendered)} image(s) ({provider.name})")
    return len(rendered)

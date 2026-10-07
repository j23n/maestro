"""`make data`: download the build-time reference data with pinned SHA-256s (docs/04 § Reference data).

The pins live in `pipeline/data/SOURCES.md` between the `pins` markers, so the CI cache key (a hash of that file)
changes whenever a pin does. Sources are tried in order; a source is accepted only if its bytes match the pin.
"""

from __future__ import annotations

import hashlib
import io
import re
import sys
import tarfile
from dataclasses import dataclass
from pathlib import Path

import requests

from itcontent.paths import DATA

PIN_ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*`([0-9a-f]{64})`\s*\|(.*)\|\s*$")

MORPHIT_NOTICE = """Morph-it! — a free morphological lexicon for the Italian language
Eros Zanchetta and Marco Baroni, SSLMIT, University of Bologna. Version 0.4.8 (2009-02-23).
https://docs.sslmit.unibo.it/doku.php?id=resources:morph-it

Morph-it! is dual-licensed: Creative Commons Attribution-ShareAlike 2.0 (CC BY-SA 2.0)
https://creativecommons.org/licenses/by-sa/2.0/legalcode and the GNU Lesser General Public License.
The licence notice in the original distribution is internally inconsistent (headed LGPL, text says GPL);
Italiano relies on CC BY-SA 2.0 (docs/13 § Licences).

Use in Italiano: build-time lemma and morphology lookup only. Never shipped in the app; nothing derived from it
ships apart from facts such as lemma names. Credited in the app's Acknowledgements.
"""

FREQUENCY_NOTICE = """FrequencyWords by Hermit Dave — OpenSubtitles 2018 frequency lists.
https://github.com/hermitdave/FrequencyWords
Word lists: Creative Commons Attribution-ShareAlike 4.0 (CC BY-SA 4.0)
https://creativecommons.org/licenses/by-sa/4.0/legalcode ; code: MIT (LICENSE).

Use in Italiano: build-time word ordering only (content freq, content suggest). Ranks are not shipped.
"""

FREQUENCY_LICENSE_URL = "https://raw.githubusercontent.com/hermitdave/FrequencyWords/master/LICENSE"


@dataclass(frozen=True)
class Pin:
    path: str
    sha256: str
    sources: list[str]


def read_pins(sources_md: Path) -> list[Pin]:
    text = sources_md.read_text(encoding="utf-8")
    try:
        block = text.split("<!-- pins:start -->", 1)[1].split("<!-- pins:end -->", 1)[0]
    except IndexError as exc:
        raise SystemExit(f"{sources_md}: no pins block") from exc
    pins = []
    for line in block.splitlines():
        m = PIN_ROW.match(line.strip())
        if m:
            urls = re.findall(r"`([^`]+)`", m.group(3))
            pins.append(Pin(m.group(1), m.group(2), urls))
    if not pins:
        raise SystemExit(f"{sources_md}: the pins block has no rows")
    return pins


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _download(url: str) -> bytes:
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    return resp.content


def _from_tgz(data: bytes) -> bytes:
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for member in tar.getmembers():
            if member.isfile() and member.name.endswith(".txt") and "morph-it" in member.name.lower():
                f = tar.extractfile(member)
                if f is not None:
                    return f.read()
    raise ValueError("no morph-it .txt member in the archive")


def fetch(pin: Pin, data_dir: Path, *, log=print) -> Path:
    dest = data_dir / pin.path
    if dest.is_file() and sha256(dest.read_bytes()) == pin.sha256:
        log(f"ok      {pin.path} (cached)")
        return dest
    errors = []
    for src in pin.sources:
        url = src.removeprefix("tgz:")
        try:
            data = _download(url)
            if src.startswith("tgz:"):
                data = _from_tgz(data)
        except Exception as exc:  # network errors, bad archives: try the next source
            errors.append(f"{url}: {exc}")
            continue
        got = sha256(data)
        if got != pin.sha256:
            errors.append(f"{url}: sha256 {got} does not match the pin")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        log(f"fetched {pin.path} from {url}")
        return dest
    raise SystemExit(f"could not fetch {pin.path}:\n  " + "\n  ".join(errors))


def write_notices(data_dir: Path, *, log=print) -> None:
    (data_dir / "morph-it").mkdir(parents=True, exist_ok=True)
    (data_dir / "frequency").mkdir(parents=True, exist_ok=True)
    (data_dir / "morph-it" / "LICENSE-NOTICE.txt").write_text(MORPHIT_NOTICE, encoding="utf-8")
    (data_dir / "frequency" / "LICENSE-NOTICE.txt").write_text(FREQUENCY_NOTICE, encoding="utf-8")
    try:
        (data_dir / "frequency" / "LICENSE-code-MIT.txt").write_bytes(_download(FREQUENCY_LICENSE_URL))
    except Exception as exc:
        log(f"note    FrequencyWords LICENSE not fetched ({exc}); the notice names it")


def main(argv: list[str] | None = None) -> int:
    data_dir = DATA
    pins = read_pins(data_dir / "SOURCES.md")
    for pin in pins:
        fetch(pin, data_dir)
    write_notices(data_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

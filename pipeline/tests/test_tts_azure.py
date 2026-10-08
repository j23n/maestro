"""The Azure batch synthesis client against recorded responses (docs/04 § Audio step 4; fixtures/azure/README.md).

A `Replay` session answers each request with the next scripted response and records what was sent, so the tests check
the exact exchange: create (PUT), poll (GET) until Succeeded, download the result ZIP from the SAS URL without the
key, check `summary.json`, delete the job. No network.
"""

from __future__ import annotations

import io
import json
import wave
import zipfile
from pathlib import Path

import pytest

from itcontent.tts_azure import AzureBatchClient, AzureError, parse_result_zip

AZURE = Path(__file__).parent / "fixtures" / "azure"
ENDPOINT = "https://westeurope.api.cognitive.microsoft.com"
KEY = "test-key-not-a-secret"
JOB = "italiano-3f9c0e1a2b4d-0a1b2c3d"
JOB_URL = f"{ENDPOINT}/texttospeech/batchsyntheses/{JOB}?api-version=2024-04-01"


def recorded(name: str) -> object:
    return json.loads((AZURE / name).read_text(encoding="utf-8"))


def wav_bytes(ms: int, rate: int = 24_000, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x01\x00" * (rate // 1000 * ms * channels))
    return buf.getvalue()


def result_zip(summary: str | None = "summary.json", wavs: tuple[str, ...] = ("0001.wav", "0002.wav")) -> bytes:
    """The result ZIP as Azure serves it: NNNN.wav (generated), NNNN.word.json and summary.json (recorded)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name in wavs:
            zf.writestr(name, wav_bytes(1700 if name == "0001.wav" else 1500))
        for name in ("0001.word.json", "0002.word.json"):
            zf.writestr(name, (AZURE / "result" / name).read_bytes())
        if summary:
            zf.writestr("summary.json", (AZURE / "result" / summary).read_bytes())
    return buf.getvalue()


class Resp:
    def __init__(self, status: int, body: object = None, content: bytes = b"", headers: dict | None = None) -> None:
        self.status_code = status
        self._body = body
        self.content = content
        self.headers = headers or {}
        self.text = json.dumps(body) if body is not None else ""

    def json(self) -> object:
        if self._body is None:
            raise ValueError("no JSON body")
        return self._body


class Replay:
    def __init__(self, responses: list[Resp]) -> None:
        self.responses = list(responses)
        self.sent: list[tuple[str, str, dict, object]] = []

    def _next(self, method: str, url: str, headers: dict | None, data: object = None) -> Resp:
        self.sent.append((method, url, dict(headers or {}), data))
        return self.responses.pop(0)

    def put(self, url, headers=None, data=None):
        return self._next("PUT", url, headers, json.loads(data))

    def get(self, url, headers=None):
        return self._next("GET", url, headers)

    def delete(self, url, headers=None):
        return self._next("DELETE", url, headers)


SSML = [
    '<speak version="1.0" xml:lang="it-IT"><voice name="it-IT-IsabellaNeural">Buongiorno! Cosa prende?</voice></speak>',
    '<speak version="1.0" xml:lang="it-IT"><voice name="it-IT-DiegoNeural">Scusi, quant\'è?</voice></speak>',
]


def client(session: Replay, sleeps: list[float]) -> AzureBatchClient:
    return AzureBatchClient(session, endpoint=ENDPOINT + "/", key=KEY, sleep=sleeps.append, poll_seconds=5)


def happy_path() -> list[Resp]:
    succeeded = recorded("job-succeeded.json")
    return [
        Resp(201, recorded("job-created.json")),
        Resp(200, recorded("job-created.json")),
        Resp(200, recorded("job-running.json")),
        Resp(200, succeeded),
        Resp(200, content=result_zip()),
        Resp(204),
    ]


def test_a_job_is_created_polled_downloaded_and_deleted():
    session = Replay(happy_path())
    sleeps: list[float] = []
    results = client(session, sleeps).synthesize(JOB, SSML)

    methods = [(m, u) for m, u, _, _ in session.sent]
    result_url = recorded("job-succeeded.json")["outputs"]["result"]  # type: ignore[index]
    assert methods == [
        ("PUT", JOB_URL),
        ("GET", JOB_URL),
        ("GET", JOB_URL),
        ("GET", JOB_URL),
        ("GET", result_url),
        ("DELETE", JOB_URL),
    ]
    _, _, headers, body = session.sent[0]
    assert headers == {"Ocp-Apim-Subscription-Key": KEY, "Content-Type": "application/json"}
    assert body == {
        "description": "Italiano course audio",
        "inputKind": "SSML",
        "inputs": [{"content": SSML[0]}, {"content": SSML[1]}],
        "properties": {
            "outputFormat": "riff-24khz-16bit-mono-pcm",
            "wordBoundaryEnabled": True,
            "sentenceBoundaryEnabled": True,
            "concatenateResult": False,
            "decompressOutputFiles": False,
        },
    }
    assert "Ocp-Apim-Subscription-Key" not in session.sent[4][2]  # the key never goes to the blob's SAS URL
    assert sleeps == [5, 5]
    assert len(results) == 2
    assert [b.text for b in results[0].boundaries] == ["Buongiorno", "!", "Cosa", "prende", "?"]
    assert (results[0].boundaries[2].offset_ms, results[0].boundaries[2].duration_ms) == (1012, 287)
    assert [b.text for b in results[1].boundaries][2] == "quant'è"  # read despite the UTF-8 BOM
    with wave.open(io.BytesIO(results[1].wav)) as w:
        assert (w.getframerate(), w.getnchannels(), w.getnframes()) == (24_000, 1, 36_000)


def test_throttling_and_server_errors_are_retried_after_retry_after():
    responses = happy_path()
    responses.insert(0, Resp(429, recorded("error-429.json"), headers={"Retry-After": "30"}))
    responses.insert(3, Resp(503, {"error": {"code": "ServiceUnavailable", "message": "try later"}}))
    sleeps: list[float] = []
    results = client(Replay(responses), sleeps).synthesize(JOB, SSML)
    assert len(results) == 2
    assert sleeps == [30.0, 5, 5, 5]


def test_errors_carry_azures_code_and_message():
    session = Replay([Resp(400, recorded("error-400.json"))])
    with pytest.raises(AzureError, match=r"create job .*HTTP 400 InvalidRequest: SSML is invalid"):
        client(session, []).synthesize(JOB, SSML)
    retries = [Resp(429, recorded("error-429.json")) for _ in range(6)]
    with pytest.raises(AzureError, match="HTTP 429 TooManyRequests"):
        client(Replay(retries), []).synthesize(JOB, SSML)


def test_a_failed_job_names_the_error():
    session = Replay([Resp(201, recorded("job-created.json")), Resp(200, recorded("job-failed.json"))])
    with pytest.raises(AzureError, match=r"failed: .*it-IT-NobodyNeural"):
        client(session, []).synthesize(JOB, SSML)


def test_a_failed_input_names_its_ssml():
    responses = happy_path()
    responses[4] = Resp(200, content=result_zip("summary-partial.json", ("0001.wav",)))
    with pytest.raises(AzureError, match=r"input 2 .*Unsupported phoneme"):
        client(Replay(responses), []).synthesize(JOB, SSML)


def test_a_job_that_never_finishes_times_out():
    running = recorded("job-running.json")
    session = Replay([Resp(201, recorded("job-created.json"))] + [Resp(200, running) for _ in range(5)])
    c = AzureBatchClient(session, endpoint=ENDPOINT, key=KEY, sleep=lambda _: None, poll_seconds=10, timeout_s=30)
    with pytest.raises(AzureError, match="timed out after 30 s"):
        c.synthesize(JOB, SSML)


def test_result_zip_checks():
    with pytest.raises(AzureError, match=r"lacks 0002\.wav"):
        parse_result_zip(result_zip(None, ("0001.wav",)), 2)
    with pytest.raises(AzureError, match="lists 2 results for 3 inputs"):
        parse_result_zip(result_zip(), 3)
    results = parse_result_zip(result_zip(None), 2)  # no summary.json: NNNN.wav by position
    assert [len(r.boundaries) for r in results] == [5, 4]


def test_the_client_refuses_more_than_a_thousand_inputs_and_needs_credentials(monkeypatch):
    with pytest.raises(AzureError, match="at most 1000"):
        client(Replay([]), []).synthesize(JOB, ["<speak/>"] * 1001)
    assert client(Replay([]), []).synthesize(JOB, []) == []
    monkeypatch.delenv("AZURE_SPEECH_KEY", raising=False)
    monkeypatch.setenv("AZURE_SPEECH_ENDPOINT", ENDPOINT)
    with pytest.raises(AzureError, match="AZURE_SPEECH_KEY"):
        AzureBatchClient(Replay([]))

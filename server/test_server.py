"""Contract tests for the reference endpoint (docs/12 § The endpoint contract, § Review comments; task M6.6)."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from server import Store, make_server

INSTALL = "6f1c0a2b-1c2d-4e5f-8a9b-0c1d2e3f4a5b"
TOKENS = {"study": "s3cret", "review": "r3view", "owner": "0wner"}


def event(i: int, t: str = "attempt") -> dict:
    return {
        "id": f"00000000-0000-4000-8000-{i:012d}",
        "at": 1_791_360_000_000 + i,
        "tzOffsetMin": 120,
        "type": t,
        "schema": 1,
        "payload": {"exerciseId": "u02.l1.ex01"},
    }


def batch(events: list[dict], install: str = INSTALL) -> dict:
    return {
        "installId": install,
        "events": events,
        "app": {
            "version": "0.9.0",
            "build": "57",
            "pack": "0.6.0",
            "platform": "iOS",
            "os": "26.1",
            "deviceClass": "phone",
        },
    }


def review(ids: list[str]) -> dict:
    return {
        "format": 1,
        "reviewer": "T",
        "channel": "app",
        "scope": "u02",
        "created": "2026-10-20T09:12:00Z",
        "files": {},
        "signoff": None,
        "comments": [
            {
                "id": i,
                "target": "u02.l1.ex07",
                "verdict": "change",
                "category": "answer key",
                "comment": "…",
                "suggestion": None,
                "response": "quanto costa?",
                "at": "2026-10-20T09:15:00Z",
            }
            for i in ids
        ],
    }


class ContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.server = make_server(0, self.dir, TOKENS)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def call(self, method: str, path: str, body: object | None = None, token: str | None = "s3cret"):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req) as r:
                raw = r.read().decode()
                return r.status, raw
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    # ---------------------------------------------------------------- study batches

    def test_batch_is_accepted_and_idempotent(self) -> None:
        status, body = self.call("POST", "/v1/batches", batch([event(1), event(2)]))
        self.assertEqual((status, json.loads(body)), (200, {"accepted": 2}))
        status, body = self.call("POST", "/v1/batches", batch([event(2), event(3)]))
        self.assertEqual((status, json.loads(body)), (200, {"accepted": 2}))
        stored = (self.dir / "installs" / f"{INSTALL}.jsonl").read_text().splitlines()
        self.assertEqual([json.loads(x)["event"]["id"][-1] for x in stored], ["1", "2", "3"])  # no duplicates

    def test_wrong_or_missing_token_is_401_and_stores_nothing(self) -> None:
        self.assertEqual(self.call("POST", "/v1/batches", batch([event(1)]), token="nope")[0], 401)
        self.assertEqual(self.call("POST", "/v1/batches", batch([event(1)]), token=None)[0], 401)
        self.assertEqual(self.call("POST", "/v1/batches", batch([event(1)]), token="r3view")[0], 401)
        self.assertFalse(any((self.dir / "installs").iterdir()))

    def test_malformed_batches_are_4xx(self) -> None:
        self.assertEqual(self.call("POST", "/v1/batches", {"installId": INSTALL})[0], 400)
        self.assertEqual(self.call("POST", "/v1/batches", batch([event(1)], install="ABC"))[0], 400)
        self.assertEqual(self.call("POST", "/v1/batches", batch([{"id": "x"}]))[0], 400)
        self.assertEqual(self.call("POST", "/v1/batches", batch([event(i) for i in range(501)]))[0], 413)

    def test_delete_removes_everything_for_the_install(self) -> None:
        self.call("POST", "/v1/batches", batch([event(1), event(2)]))
        status, body = self.call("DELETE", f"/v1/installs/{INSTALL}")
        self.assertEqual((status, json.loads(body)), (200, {"deleted": 2}))
        self.assertFalse((self.dir / "installs" / f"{INSTALL}.jsonl").exists())
        # after deletion the same events are new again (a participant who re-consents)
        self.assertEqual(json.loads(self.call("POST", "/v1/batches", batch([event(1)]))[1]), {"accepted": 1})

    def test_export_is_owner_only_jsonl(self) -> None:
        self.call("POST", "/v1/batches", batch([event(1), event(2, "session")]))
        self.assertEqual(self.call("GET", "/v1/export/events", token="s3cret")[0], 401)
        status, body = self.call("GET", "/v1/export/events", token="0wner")
        self.assertEqual(status, 200)
        lines = [json.loads(x) for x in body.splitlines()]
        self.assertEqual([x["event"]["type"] for x in lines], ["attempt", "session"])
        self.assertEqual(lines[0]["installId"], INSTALL)
        self.assertEqual(lines[0]["app"]["platform"], "iOS")
        self.assertNotIn("ip", json.dumps(lines))

    def test_no_ip_addresses_in_storage(self) -> None:
        self.call("POST", "/v1/batches", batch([event(1)]))
        text = "".join(p.read_text() for p in self.dir.rglob("*.jsonl"))
        self.assertNotIn("127.0.0.1", text)

    # ---------------------------------------------------------------- review comments

    def test_review_comments_are_idempotent_by_comment_id(self) -> None:
        status, body = self.call("POST", "/v1/review-comments", review(["c1", "c2"]), token="r3view")
        self.assertEqual((status, json.loads(body)), (200, {"accepted": 2}))
        self.call("POST", "/v1/review-comments", review(["c1", "c2"]), token="r3view")
        status, body = self.call("GET", "/v1/review-comments?since=2000-01-01", token="0wner")
        self.assertEqual(status, 200)
        files = [json.loads(x) for x in body.splitlines()]
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0]["review"]["comments"][0]["response"], "quanto costa?")

    def test_review_route_needs_the_review_token_and_never_mixes_with_study_data(self) -> None:
        self.assertEqual(self.call("POST", "/v1/review-comments", review(["c1"]), token="s3cret")[0], 401)
        self.assertEqual(self.call("POST", "/v1/review-comments", {"format": 2}, token="r3view")[0], 400)
        self.call("POST", "/v1/review-comments", review(["c9"]), token="r3view")
        self.assertEqual(self.call("GET", "/v1/export/events", token="0wner")[1], "")

    def test_store_reloads_ids_after_restart(self) -> None:
        self.call("POST", "/v1/batches", batch([event(1)]))
        self.call("POST", "/v1/review-comments", review(["c1"]), token="r3view")
        store = Store(self.dir)
        self.assertEqual(store.add_batch(INSTALL, {}, [event(1)], "2026-10-20T00:00:00Z"), 1)
        self.assertEqual(len((self.dir / "installs" / f"{INSTALL}.jsonl").read_text().splitlines()), 1)
        store.add_review(review(["c1"]), "2026-10-20T00:00:00Z")
        self.assertEqual(len(store.export_reviews(None)), 1)

    def test_unknown_routes_are_404(self) -> None:
        self.assertEqual(self.call("GET", "/v1/batches", token="0wner")[0], 404)
        self.assertEqual(self.call("POST", "/admin", {})[0], 404)


if __name__ == "__main__":
    unittest.main()

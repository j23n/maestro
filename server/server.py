#!/usr/bin/env python3
"""Reference endpoint for study telemetry and the content lead's review comments (docs/12, task M6.6).

Standard library only, so it runs on any small host (Q9). It never logs IP addresses and never handles anything but
these routes. Storage is append-only JSONL under DATA_DIR; the owner exports it for `content beta-import` and
`content review-import`.

    POST   /v1/batches                study batches        Bearer STUDY_TOKEN   → 200 {"accepted": n}
    DELETE /v1/installs/{installId}   delete a participant Bearer STUDY_TOKEN   → 200 {"deleted": n}
    POST   /v1/review-comments        review file          Bearer REVIEW_TOKEN  → 200 {"accepted": n}
    GET    /v1/review-comments?since= review files         Bearer OWNER_TOKEN   → 200 JSONL
    GET    /v1/export/events?since=   study events         Bearer OWNER_TOKEN   → 200 JSONL (for content beta-import)

Run:  STUDY_TOKEN=… REVIEW_TOKEN=… OWNER_TOKEN=… DATA_DIR=./data python3 server.py serve --port 8787
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import re
import sys
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

MAX_BODY = 5 * 1024 * 1024
MAX_EVENTS = 500  # docs/12: batches of ≤ 500 events
INSTALL_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class Store:
    """Append-only JSONL files plus in-memory ID sets for idempotence. One lock serialises writes."""

    def __init__(self, data_dir: Path) -> None:
        self.dir = data_dir
        (self.dir / "installs").mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.event_ids: dict[str, set[str]] = {}
        self.comment_ids: set[str] = set()
        self.reviews = self.dir / "review-comments.jsonl"
        if self.reviews.exists():
            for line in self.reviews.read_text(encoding="utf-8").splitlines():
                for c in json.loads(line)["review"].get("comments") or []:
                    self.comment_ids.add(str(c.get("id")))

    def _install_file(self, install_id: str) -> Path:
        return self.dir / "installs" / f"{install_id}.jsonl"

    def _ids(self, install_id: str) -> set[str]:
        if install_id not in self.event_ids:
            ids = set()
            f = self._install_file(install_id)
            if f.exists():
                ids = {json.loads(line)["event"]["id"] for line in f.read_text(encoding="utf-8").splitlines()}
            self.event_ids[install_id] = ids
        return self.event_ids[install_id]

    def add_batch(self, install_id: str, app: dict, events: list[dict], now: str) -> int:
        with self.lock:
            seen = self._ids(install_id)
            new = [e for e in events if e["id"] not in seen]
            if new:
                with self._install_file(install_id).open("a", encoding="utf-8") as f:
                    for e in new:
                        line = {"installId": install_id, "app": app, "receivedAt": now, "event": e}
                        f.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n")
                        seen.add(e["id"])
            return len(events)  # idempotent: re-sent events count as accepted

    def delete_install(self, install_id: str) -> int:
        with self.lock:
            f = self._install_file(install_id)
            n = len(f.read_text(encoding="utf-8").splitlines()) if f.exists() else 0
            f.unlink(missing_ok=True)
            self.event_ids.pop(install_id, None)
            return n

    def add_review(self, review: dict, now: str) -> int:
        with self.lock:
            comments = review.get("comments") or []
            new = [c for c in comments if str(c.get("id")) not in self.comment_ids]
            if new:
                with self.reviews.open("a", encoding="utf-8") as f:
                    f.write(
                        json.dumps({"receivedAt": now, "review": review}, ensure_ascii=False, sort_keys=True) + "\n"
                    )
                self.comment_ids.update(str(c.get("id")) for c in comments)
            return len(comments)

    def export_events(self, since: str | None) -> list[str]:
        out = []
        for f in sorted((self.dir / "installs").glob("*.jsonl")):
            for line in f.read_text(encoding="utf-8").splitlines():
                if since is None or json.loads(line)["receivedAt"] >= since:
                    out.append(line)
        return out

    def export_reviews(self, since: str | None) -> list[str]:
        if not self.reviews.exists():
            return []
        lines = self.reviews.read_text(encoding="utf-8").splitlines()
        return [ln for ln in lines if since is None or json.loads(ln)["receivedAt"] >= since]


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def valid_event(e: object) -> bool:
    return (
        isinstance(e, dict)
        and isinstance(e.get("id"), str)
        and isinstance(e.get("at"), int)
        and isinstance(e.get("type"), str)
        and isinstance(e.get("payload"), dict)
    )


class Handler(BaseHTTPRequestHandler):
    server_version = "italiano-study/1"
    store: Store
    tokens: dict[str, str]
    clock = staticmethod(utc_now)

    def log_message(self, format: str, *args: object) -> None:
        # No IP logging (docs/12): log the request line and status only.
        sys.stderr.write(f"{self.log_date_time_string()} {format % args}\n")

    def _authorised(self, role: str) -> bool:
        expected = self.tokens.get(role) or ""
        got = self.headers.get("Authorization", "")
        return bool(expected) and hmac.compare_digest(got, f"Bearer {expected}")

    def _reply(self, status: int, body: dict | None = None, *, jsonl: list[str] | None = None) -> None:
        if jsonl is not None:
            data = ("\n".join(jsonl) + ("\n" if jsonl else "")).encode()
            ctype = "application/x-ndjson"
        else:
            data = json.dumps(body or {}).encode()
            ctype = "application/json"
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json_body(self) -> object | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None
        if length <= 0 or length > MAX_BODY:
            return None
        try:
            return json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/v1/batches":
            if not self._authorised("study"):
                return self._reply(401, {"error": "unauthorised"})
            body = self._json_body()
            if not isinstance(body, dict):
                return self._reply(400, {"error": "malformed JSON"})
            install_id, app, events = body.get("installId"), body.get("app"), body.get("events")
            if not isinstance(install_id, str) or not INSTALL_ID.match(install_id):
                return self._reply(400, {"error": "installId must be a lowercase UUID"})
            if not isinstance(app, dict) or not isinstance(events, list) or not all(map(valid_event, events)):
                return self._reply(400, {"error": "app and events are required"})
            if len(events) > MAX_EVENTS:
                return self._reply(413, {"error": f"at most {MAX_EVENTS} events per batch"})
            return self._reply(200, {"accepted": self.store.add_batch(install_id, app, events, self.clock())})
        if path == "/v1/review-comments":
            if not self._authorised("review"):
                return self._reply(401, {"error": "unauthorised"})
            body = self._json_body()
            if not isinstance(body, dict) or body.get("format") != 1 or not isinstance(body.get("comments"), list):
                return self._reply(400, {"error": "a review file (docs/04) is required"})
            return self._reply(200, {"accepted": self.store.add_review(body, self.clock())})
        return self._reply(404, {"error": "not found"})

    def do_DELETE(self) -> None:
        m = re.fullmatch(r"/v1/installs/([^/]+)", urlparse(self.path).path)
        if not m:
            return self._reply(404, {"error": "not found"})
        if not self._authorised("study"):
            return self._reply(401, {"error": "unauthorised"})
        if not INSTALL_ID.match(m.group(1)):
            return self._reply(400, {"error": "installId must be a lowercase UUID"})
        return self._reply(200, {"deleted": self.store.delete_install(m.group(1))})

    def do_GET(self) -> None:
        url = urlparse(self.path)
        since = (parse_qs(url.query).get("since") or [None])[0]
        if url.path in ("/v1/review-comments", "/v1/export/events"):
            if not self._authorised("owner"):
                return self._reply(401, {"error": "unauthorised"})
            lines = (
                self.store.export_reviews(since)
                if url.path == "/v1/review-comments"
                else self.store.export_events(since)
            )
            return self._reply(200, jsonl=lines)
        return self._reply(404, {"error": "not found"})


def make_server(port: int, data_dir: Path, tokens: dict[str, str], host: str = "127.0.0.1") -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"store": Store(data_dir), "tokens": tokens})
    return ThreadingHTTPServer((host, port), handler)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=8787)
    s.add_argument("--host", default="127.0.0.1")
    e = sub.add_parser("export", help="print stored study events as JSONL (for content beta-import)")
    e.add_argument("--since", default=None)
    args = ap.parse_args(argv)
    data_dir = Path(os.environ.get("DATA_DIR", "data"))
    if args.cmd == "export":
        for line in Store(data_dir).export_events(args.since):
            print(line)
        return 0
    tokens = {k: os.environ.get(f"{k.upper()}_TOKEN", "") for k in ("study", "review", "owner")}
    server = make_server(args.port, data_dir, tokens, args.host)
    print(f"listening on {args.host}:{args.port}, data in {data_dir}", file=sys.stderr)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

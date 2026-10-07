# Study and review endpoint (reference)

A small reference endpoint for `docs/12` (task M6.6), standard library only. Put it behind any TLS-terminating
host (Q9). It never logs IP addresses and handles only these routes:

| Route | Token | What |
|---|---|---|
| `POST /v1/batches` | `STUDY_TOKEN` | study batches (≤ 500 events), idempotent by event ID → `{"accepted": n}`; 4xx is final for the client |
| `DELETE /v1/installs/{installId}` | `STUDY_TOKEN` | "Delete my study data": removes everything for the install |
| `POST /v1/review-comments` | `REVIEW_TOKEN` | a review file from the app's review mode (`docs/04`), idempotent by comment ID |
| `GET /v1/review-comments?since=` | `OWNER_TOKEN` | the stored review files as JSONL, one per line: `{receivedAt, review}` |
| `GET /v1/export/events?since=` | `OWNER_TOKEN` | the stored study events as JSONL, one per line: `{installId, app, receivedAt, event}` — the input of `content beta-import` |

Storage is append-only JSONL under `DATA_DIR` (`installs/<installId>.jsonl`, `review-comments.jsonl`). Review
comments are never mixed with study data.

```bash
STUDY_TOKEN=… REVIEW_TOKEN=… OWNER_TOKEN=… DATA_DIR=./data python3 server.py serve --port 8787
DATA_DIR=./data python3 server.py export --since 2026-11-01 > events.jsonl
make -C server test
```

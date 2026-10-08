# 12 · Study support, telemetry and privacy

The MVP exists to answer two questions: do people learn A1 Italian with it, and do they keep coming back? The study (40–60 beginners, weeks 21–39) is run by the owner. The app supports it in four ways: consented telemetry, an in-app final check, an examiner export, and the item data that feeds content fixes.

## Consent

- **Study builds** (`ITA_STUDY_BUILD = YES`, TestFlight) show a consent screen after onboarding:
  - What's collected (below), the pseudonymous install ID, who sees it (the research team) and how to stop.
  - Buttons: **Share learning data** and **Not now**.
  - The text version is stored with the consent (`study.consent = {version, date, granted}`).
- Settings → Research → "Share anonymous learning data" turns it on or off at any time (`Settings.png`). Turning it off stops uploads immediately. Turning it on again uploads only events from the new consent date.
- Non-study builds never show the consent screen and never upload.
- The owner writes the participant information sheet and consent text, which need human sign-off (the agent leaves `TODO(owner)` markers).

## What is uploaded (only with consent)

| Data | Included | Excluded |
|---|---|---|
| Install ID | a random UUID created once, when consent is first granted, and stored as the synced setting `study.installId` (last writer wins), so one participant has one ID on all their devices; shown in Settings → Research so a participant can quote it | Apple ID, name, email, device name |
| Events | events with `at` ≥ the consent date only: `attempt` (typed `response` only for closed formats, ≤ 200 chars), `introduced`, `stepStarted`/`stepCompleted`, `glossTapped`, `audioPlayed`, `session`, `checkCompleted`, `placementCompleted`, `onboardingCompleted` (reason, beginner flag; **not** name or country) | `talk` and `writing` responses, speech transcripts, recordings, `profile.name` |
| Context | app version, pack version, platform (iOS, iPadOS, macOS), OS major version, device class (phone, tablet, mac) | precise model, locale, IP-derived data (the endpoint must not log IPs) |

## The endpoint contract

```
POST {ITA_TELEMETRY_URL}/v1/batches
Authorization: Bearer <study token baked into study builds>
Content-Type: application/json
{
  "installId": "6f1c…",
  "app": {"version": "0.9.0", "build": "57", "pack": "0.6.0", "platform": "iOS", "os": "26.1", "deviceClass": "phone"},
  "events": [ { "id": "…", "at": 1791360000000, "tzOffsetMin": 120, "type": "attempt", "schema": 1, "payload": { … } } ]
}
→ 200 {"accepted": 123}     (idempotent: the server ignores event IDs it already has)
→ 4xx: log it and mark the batch's events as sent (never retried);   5xx / network: retry with exponential backoff (max 6 h)
```

- **Client:**
  - Batches of ≤ 500 events.
  - Uploads after launch, when the app goes to the background, after each session and every 15 minutes while active, on any network (`StudyTelemetry`; each upload reads the consent at that moment, and uploads queue behind each other so no event is in two requests at once).
  - After a 200 (or a 4xx), inserts a `telemetry_sent` row per event (`docs/03`); events themselves are never updated.
  - Uploads only events not in `telemetry_sent`, with `at` ≥ the consent date.
  - Only uploads events created on this device (`origin = 'local'`), so synced events aren't uploaded twice.
- **Server (any small host, Q9):** append the raw JSON to storage keyed by `installId`, with no IP logging and an export to JSONL for `content beta-import`. A 50-line reference server (Python or a Cloudflare Worker) in `server/` is task M6.6; it is outside the app and never handles anything but this endpoint.

- **Study token:** `Authorization: Bearer` uses `ITA_STUDY_TOKEN` from the gitignored `App/Config/Secrets-Study.xcconfig`, included only by `Study.xcconfig` with `#include?` (`docs/02`). Builds without it never upload.

### Review comments (Review builds only)

The same server takes the content lead's comments from the in-app review mode (`docs/04` § Content review loop):

```
POST {ITA_REVIEW_URL}/v1/review-comments
Authorization: Bearer <review token, only in Review builds>
Content-Type: application/json
{ …the review file (docs/04 § The review file)… }
→ 200 {"accepted": 12}     (idempotent by comment id)
```

The app posts one review file per scope with the comments not sent yet (`docs/04` § Review mode in the app); a comment is marked sent after a 2xx and kept for a retry otherwise. The server appends each file to storage; the owner downloads them (`GET /v1/review-comments?since=<date>` with the owner's token, or the JSONL export) and runs `content review-import` on each. Review comments are never mixed with study data, and Review builds never send telemetry.

## Final check export (examiner rating)

- After the final A1 check, **Export for examiner** creates `final-check-<installId>-<date>-<time>.zip` containing:
  - `responses.json`: every item with the learner's answer, auto score and section totals;
  - `writing/*.txt`;
  - `speaking/*.m4a`: the recordings of the speaking section (`docs/09` § Transcription), kept on the recording device only until export or 30 days (their folders are excluded from iCloud Backup and Time Machine);
  - `README.txt`: what it is, and the install ID.
- The zip opens in the share sheet; the participant sends it however the study protocol says. Nothing uploads automatically.
- No third-party zip library: the app's own `StoredZip` writes a standard ZIP with every file stored (no compression: the m4a files are already compressed and the text is small), UTF-8 names and the check's local time as every entry's date, so the same sitting always gives the same bytes (`fixtures/export/stored-zip-golden.zip`, read back by Python's `zipfile` in the pipeline tests). This replaces the earlier plan of `NSFileCoordinator` `.forUploading`, pending the owner's decision (`docs/13` § Proposed changes).
- **Exact layout** (`ExaminerExport`, built from the sitting's own `attempt` events):
  - `README.txt`: what the archive is, the install ID (or "none (this device hasn't joined the study)"), when the check was taken, the pack and app versions, each section's automatic score, and the line "This is a practice check, not an official certificate.";
  - `responses.json` (below);
  - `writing/<exerciseId>.txt`: each writing task's text (a form as `Label: value` lines);
  - `speaking/<exerciseId>-<attemptId>.m4a`: one recording per spoken answer (a conversation has one per turn), named as on the device.
- **Name:** `final-check-<installId>-<YYYY-MM-DD>-<HHMM>.zip`, the date and time the check was taken in the learner's time zone, so every sitting has its own name (a retake on the same day too); without an install ID (no consent ever given) `final-check-<YYYY-MM-DD>-<HHMM>.zip`. No name, country or other profile data goes into the archive.
- **When:** as the check ends, the app keeps the sitting's record (`sitting.json`: the `responses.json` contents and when the check was taken) in the sitting's folder with its recordings, `Application Support/Italiano/final-check/<sittingId>/`; nothing is zipped yet. **Export for examiner**, on the result and in the final review unit while the sitting is kept, builds the zip in a folder of its own under `exports/` and opens the share sheet with it (`ExportSharing`; Copy, Print and similar activities are not offered, since they hand the export to no one). When the share completes (the successful export, `docs/09` § Transcription), the zip, the recordings and the record are deleted. When it is cancelled or fails, only the zip is deleted, so the learner can export again until the 30 days are up.
- **Whose files:** a sitting belongs to the learner database that holds its `checkCompleted` event. Resetting progress or an iCloud account switch (a new database) deletes every sitting and zip; a sitting whose event is gone (progress reset on another device) is never offered and is deleted when it is found or at the next launch.
- `responses.json` (schema 1; keys sorted; an absent key means "none"):

```json
{
  "schema": 1, "kind": "final-check", "installId": "6f1c…", "takenAt": "2026-10-06T09:30:00+02:00",
  "app": {"version": "1.0 (57)", "pack": "0.9.0"},
  "indicativePass": false, "passMarkPerSection": 7,
  "sections": [{"id": "listening", "title": "Listening", "points": 6, "max": 12, "passed": false, "excluded": false}],
  "items": [
    {"exerciseId": "final.s01", "section": "speaking", "format": "talk", "score": 1, "earned": 1,
     "answers": [{"attemptId": "…", "outcome": "correct", "mode": "spoken", "response": "Buongiorno! Quant'è?",
                  "latencyMs": 8200, "recording": "speaking/final.s01-….m4a"}]},
    {"exerciseId": "final.w01", "section": "writing", "format": "writing", "score": 2, "earned": 1,
     "answers": [{"attemptId": "…", "outcome": "wrong", "mode": "typed", "response": "Cara Anna, …", "latencyMs": 300000}],
     "writingFile": "writing/final.w01.txt"}
  ]
}
```

  Every item of every section is listed in order (an item in an excluded section, or never answered, has `"answers": []`); `answers[].turnId` names a conversation's node; `earned` is the item's raw points (`score` × credit), `sections[].points` is the section scaled to its 12 points, and `passMarkPerSection` is the pack's `indicativePassPerSection` (the README and the result screen quote the same number). An answer whose recording can't be read when the zip is built names no `recording`.

## Beta and study data loop

- Weekly: the owner exports the server's JSONL and runs `content beta-import`. That produces item statistics (first-try error rate, median latency, gloss taps per token, skips) and rejected typed answers grouped by exercise.
- The content lead adjudicates rejected answers. Accepted variants go into the patterns (reopen, fix, approve).
- Outlier items are reviewed before the content freeze.

## Privacy and App Store

- **Privacy manifest** (`PrivacyInfo.xcprivacy`, one file for all builds of the single target; it declares the study data types, which non-study builds never collect, so it is accurate for study builds and conservative otherwise):
  - No tracking and no tracking domains.
  - Required-reason APIs: exactly what the code uses — `UserDefaults` (CA92.1: the Debug menu's switches). The 30-day retention reads each sitting's `takenAt` from its record, not file timestamps. No file-timestamp, disk-space, boot-time or keyboard APIs.
  - Collected data types for study builds, all linked to the install ID (pseudonymous), not used for tracking, purpose Analytics: "Product Interaction" (the events), "Other Usage Data" (the batch's context, onboarding's reason and beginner flag), "Other User Content" (typed answers to closed formats, ≤ 200 characters) and "User ID" (the install ID itself, an assigned user-level ID).
- **App Store privacy label:** filled by the owner from the manifest; `docs/appstore-metadata.md` has the draft answers.
- **Microphone:** used only while the learner holds or taps the mic; recognition runs on device.
- **iCloud:** learner data lives in the user's own private database; we can't read it.
- **Children:** not in the Kids category; the study recruits adults (18+).
- **Data deletion:** Settings → Research → "Delete my study data" turns consent off first (so nothing uploads after the deletion), waits for an upload in flight, then sends `DELETE {url}/v1/installs/{installId}` (server deletes everything). If the server can't be reached, sharing stays off and the button can be used again. Settings → Research also shows the install ID. Local and iCloud data are the learner's: "Reset progress" (debug only in the MVP) deletes them.

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
  - Uploads when the app goes to the background and every 15 minutes while active, on any network.
  - After a 200 (or a 4xx), inserts a `telemetry_sent` row per event (`docs/03`); events themselves are never updated.
  - Uploads only events not in `telemetry_sent`, with `at` ≥ the consent date.
  - Only uploads events created on this device (`origin = 'local'`), so synced events aren't uploaded twice.
- **Server (any small host, Q9):** append the raw JSON to storage keyed by `installId`, with no IP logging and an export to JSONL for `content beta-import`. A 50-line reference server (Python or a Cloudflare Worker) in `server/` is task M6.6; it is outside the app and never handles anything but this endpoint.

- **Study token:** `Authorization: Bearer` uses `ITA_STUDY_TOKEN` from the gitignored `App/Config/Secrets.xcconfig`, included by `Study.xcconfig` with `#include?` (`docs/02`). Builds without it never upload.

### Review comments (Review builds only)

The same server takes the content lead's comments from the in-app review mode (`docs/04` § Content review loop):

```
POST {ITA_REVIEW_URL}/v1/review-comments
Authorization: Bearer <review token, only in Review builds>
Content-Type: application/json
{ …the review file (docs/04 § The review file)… }
→ 200 {"accepted": 12}     (idempotent by comment id)
```

The server appends each file to storage; the owner downloads them (`GET /v1/review-comments?since=<date>` with the owner's token, or the JSONL export) and runs `content review-import` on each. Review comments are never mixed with study data, and Review builds never send telemetry.

## Final check export (examiner rating)

- After the final A1 check, **Export for examiner** creates `final-check-<installId>-<date>.zip` containing:
  - `responses.json`: every item with the learner's answer, auto score and section totals;
  - `writing/*.txt`;
  - `speaking/*.m4a`: the recordings of the speaking section (`docs/09` § Transcription), kept on the recording device only until export or 30 days;
  - `README.txt`: what it is, and the install ID.
- The zip opens in the share sheet; the participant sends it however the study protocol says. Nothing uploads automatically.
- No third-party zip library: write the files to a temporary folder and read it through `NSFileCoordinator` with the `.forUploading` option, which hands back a zipped copy (verify on macOS and iOS in M8.2).

## Beta and study data loop

- Weekly: the owner exports the server's JSONL and runs `content beta-import`. That produces item statistics (first-try error rate, median latency, gloss taps per token, skips) and rejected typed answers grouped by exercise.
- The content lead adjudicates rejected answers. Accepted variants go into the patterns (reopen, fix, approve).
- Outlier items are reviewed before the content freeze.

## Privacy and App Store

- **Privacy manifest** (`PrivacyInfo.xcprivacy`, one file for all builds of the single target; it declares the study data types, which non-study builds never collect, so it is accurate for study builds and conservative otherwise):
  - No tracking and no tracking domains.
  - Required-reason APIs: `UserDefaults` (CA92.1) and file timestamps if used — declare exactly what the code uses.
  - Collected data types for study builds: "Product Interaction" and "Other Usage Data", linked to the install ID (pseudonymous), not used for tracking.
- **App Store privacy label:** filled by the owner from the manifest.
- **Microphone:** used only while the learner holds or taps the mic; recognition runs on device.
- **iCloud:** learner data lives in the user's own private database; we can't read it.
- **Children:** not in the Kids category; the study recruits adults (18+).
- **Data deletion:** Settings → Research → "Delete my study data" sends `DELETE {url}/v1/installs/{installId}` (server deletes everything) and turns consent off. Local and iCloud data are the learner's: "Reset progress" (debug only in the MVP) deletes them.

# 08 · iCloud sync

Progress follows the learner across iPhone, iPad and Mac through their **private** CloudKit database. Only two kinds of data sync: immutable **events** and per-key **settings**. Memory states, introductions and progress are derived by replay on each device, so they never conflict (ADR-04).

## CloudKit layout

- Container: `iCloud.com.j23n.italian` (ADR-18). It is created by the owner's first signed CloudKit build and can never be deleted. Entitlements, signing and the `ITA_SYNC_ENABLED` switch: `docs/02` § Project, signing and entitlements. Agents build without iCloud; sync is tested with the in-memory simulator until the owner signs a build.
- Database: **private**. One custom zone: `Learner`.

| Record type | `recordName` | Fields | Mutability |
|---|---|---|---|
| `Event` | the event UUID (lowercase) | `type` String, `at` Int64 (ms), `tzOffsetMin` Int64, `deviceId` String, `schema` Int64, `packVersion` String, `payload` Bytes (UTF-8 JSON) | immutable; never modified, never deleted (except Reset) |
| `Setting` | `setting.<key>` | `value` Bytes (JSON), `updatedAt` Int64 (ms), `deviceId` String | last-writer-wins per key |

No queries are needed (the sync engine fetches zone changes), so no indexes beyond CloudKit's defaults. Production schema changes are additive only, so add fields rather than reshaping them.

**Before the first TestFlight build with sync** (TestFlight uses the production environment): deploy the schema from Development to Production in the CloudKit Console (CloudKit Database → container → Deploy Schema Changes). The record types exist only after the owner has run a signed development build that saved them (after M7.2). This is a human step on the M7 checklist; until then TestFlight builds ship with `ITA_SYNC_ENABLED = NO`.

## Settings

| Key | Scope | Default |
|---|---|---|
| `profile.name` | synced | empty |
| `profile.forms` | synced | `both` |
| `profile.country` | synced | — |
| `profile.reason` | synced | — |
| `goal.daysPerWeek` | synced | 5 |
| `review.dailyLimit` | synced | 60 |
| `display.englishUnderStories` | synced | false |
| `display.textScale` | device (a phone and a Mac need different sizes) | 1.0 (0.85–1.6; the `Aa` control and ⌘+ / ⌘−, `docs/07`) |
| `display.speakerLabels` | synced | true until Unit 5 |
| `audio.storyRate` | synced | 1.0 |
| `mascot.hints` | synced | true |
| `answers.strictForms` | synced | false |
| `study.consent` | synced (value includes consent version and date) | not set |
| `study.installId` | synced (created once, on first consent; last writer wins) | not set |
| `speech.enabled` | device | true if available |
| `reminder.enabled`, `reminder.time` | device | off |
| `sync.paused` | device | false |

Device-scoped settings never sync. For synced settings, the newest `updatedAt` wins; ties go to the lexically larger `deviceId`.

## The sync engine (App target, `Platform/CloudSync/`)

Use `CKSyncEngine` (iOS 17+ / macOS 14+, so fine with our 26 target).

```swift
actor CloudSync: CKSyncEngineDelegate {   // the protocol requires AnyObject & Sendable; an actor holds mutable state safely
  func handleEvent(_ event: CKSyncEngine.Event, syncEngine: CKSyncEngine) async
  func nextRecordZoneChangeBatch(_ context: CKSyncEngine.SendChangesContext,
                                 syncEngine: CKSyncEngine) async -> CKSyncEngine.RecordZoneChangeBatch?
}
```

- **Startup:** load `sync_engine_state.data` (a `CKSyncEngine.State.Serialization`, Codable) and create `CKSyncEngine(.init(database: container.privateCloudDatabase, stateSerialization: saved, delegate: self))`. On the very first run, add `.saveZone(Learner)` as a pending database change.
- **`.stateUpdate`:** persist the serialization immediately (in the same database, its own small transaction).
- **New local events:** `LearnerStore` inserts the `sync_pending` row **in the same transaction** as the event append. After the commit, `CloudSync` calls `syncEngine.state.add(pendingRecordZoneChanges: [.saveRecord(recordID)])`. Crash safety: on launch, re-add anything in `sync_pending` that the engine doesn't list as pending.
- **`nextRecordZoneChangeBatch`:**
  - Filter pending changes to `context.options.scope`.
  - Build records with `await CKSyncEngine.RecordZoneChangeBatch(pendingChanges:recordProvider:)`, which sizes the batch to CloudKit's limits for you.
  - The provider loads the event or setting by record name. If the event row is gone (it shouldn't be), remove the pending change.
- **`.sentRecordZoneChanges`:**
  - Remove saved records from `sync_pending`.
  - For each failed save, branch on the error:
    - `.serverRecordChanged` on an `Event`: the same UUID already exists remotely; treat it as success.
    - `.serverRecordChanged` on a `Setting`: merge last-writer-wins, store the server record's system fields, and re-add the save only if the local value wins.
    - `.zoneNotFound`: add `.saveZone`, then re-add the save.
    - `.unknownItem`: clear the cached system fields and re-add.
    - Other errors: CKSyncEngine retries transient errors itself; anything else is logged and surfaced as "Sync paused" in Settings.
- **`.fetchedRecordZoneChanges`:**
  - For each modified `Event`, insert it if the ID is new (`origin = 'remote'`).
  - For each `Setting`, merge last-writer-wins and store the system fields.
  - Then ask Storage to replay the new events (`docs/05` § Replay) in one background task.
  - Deletions happen only through Reset (below).
- **`.fetchedDatabaseChanges` with our zone deleted:**
  - reason `.deleted` (Reset on another device) or `.purged` (the learner deleted the app's iCloud data in Settings): delete local events, derived state and synced settings (keep device settings), clear `sync_pending` and `cloud_system_fields`, recreate the zone, and say once "Your progress was reset on another device".
  - reason `.encryptedDataReset`: recreate the zone and mark every local event and setting pending, so this device uploads everything again.
- **`.accountChange`:**
  - `signIn` with no previous account: keep local data and add every local event as a pending save (first upload).
  - `signOut`: pause sync; keep everything local so the app works offline.
  - `switchAccounts`: show an alert ("This device has progress from another iCloud account"). On confirm, move `learner.sqlite` to `learner-<date>.archive.sqlite`, start a fresh database and fetch the new account's data. On cancel, pause sync.
- **Don't call** `fetchChanges` or `sendChanges` from inside `handleEvent`. Call `sendChanges()` when the app goes to the background and after a lesson step completes.
- **Reset progress** (Debug menu only in the MVP): delete the zone, clear local events and derived state, then recreate the zone.
- **Pause sync** (`sync.paused`, Settings → Sync): persist the state serialization, then release the engine (no fetches or sends). Unpausing creates the engine again from the saved state. New events keep collecting in `sync_pending` meanwhile.

## Merge rules (LearningCore `Sync/MergeRules.swift`, unit-tested)

- An event is identified by its ID: insert if absent, ignore if present. Never update.
- Replay order is `(at, id)` on every device, so states converge regardless of arrival order.
- Clock skew: no correction. A device with a wrong clock produces events at the wrong times, but every device computes the same state from them.
- Settings: last-writer-wins by `(updatedAt, deviceId)`: a tie on `updatedAt` goes to the lexically larger `deviceId` (UTF-8 bytes), and a full tie (never expected) to the larger canonical value JSON, so the merge is commutative and every device keeps the same value. Device-scoped settings never sync.

## Status UI

Settings → Sync (`Settings.png`) shows an iCloud row with one of these states:

- "Synced 2 minutes ago · iPhone, iPad, Mac" — device names come from the `deviceId`s seen in events, mapped to the `platform` field of their `session` events (`docs/05`).
- "Syncing…"
- "Waiting for network"
- "iCloud is off — progress stays on this device"
- "Sync paused" (with a short reason, or "Paused in Settings")
- "Sync off in this build" (no entitlement or `ITA_SYNC_ENABLED = NO`)

There are no modal alerts except the account switch.

## Tests

1. **Unit (Linux, LearningCore):** a two- and three-device simulator. Devices create events offline, then exchange them in random orders and with duplicates. Assert that derived states (memory, introductions, unit progress, daily activity) are byte-identical, for 1,000 seeded runs.
2. **Integration (macOS, Storage):** append events, apply remote batches out of order, assert that the incremental replay equals a full rebuild; kill the process between append and `state.add` and assert the event is still uploaded after relaunch.
3. **Manual (M7 checklist, real devices on one iCloud account):**
   - Answer on the iPhone in airplane mode, answer on the iPad, reconnect both, and confirm the Words screen matches on all three.
   - Settings change on two devices within a minute: the last write wins.
   - Sign out and in.
   - Switch accounts.
   - Fresh install restores progress.
   - 10,000 events first sync completes and the app stays responsive.

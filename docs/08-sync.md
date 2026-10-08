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

Device-scoped settings never sync. For synced settings, the newest `updatedAt` wins; ties go to the lexically larger `deviceId`. A change made on this device is stamped `max(now, stored updatedAt + 1)`, so it wins even when another device's clock ran ahead; a synced key also gets a `sync_pending` row (`setting.<key>`) in the same transaction.

## The sync engine (App target, `Platform/CloudSync/`)

Use `CKSyncEngine` (iOS 17+ / macOS 14+, so fine with our 26 target). The work is split so that every decision is tested on any platform:

- **`SyncDriver`** (actor, `SyncDriver.swift`; platform-neutral, imports only Foundation, LearningCore and Storage) holds all the logic below. It sees the engine through the `SyncEngine` protocol (pending saves, `.saveZone`/`.deleteZone`, `fetchChanges`, `sendChanges`) and its events as `SyncEngineEvent` (`SyncEngine.swift`), with records as LearningCore's `SyncRecord` plus opaque system fields. Its entry points: `handle(_:from:)` (one engine event), `recordsToSend(_:from:)` (the record provider), and the App's `SyncControlling` (`start`, `syncNow`, `setPaused`, `resolveAccountSwitch(confirm:)`, `dismissNotice`, `resetProgress`, and a stream of `SyncSnapshot`s for Settings). Events from an engine the driver has let go are ignored.
- **`CloudSync`** (actor, `CloudSync.swift`; Apple only) is the `CKSyncEngineDelegate` and the `SyncEngineFactory`: it creates the CKSyncEngine, maps `CKSyncEngine.Event`, `CKRecord` (field by field through `RecordMapping`) and `CKError` onto the driver's types, builds each batch, and reports the network path (`NWPathMonitor`). It makes no decisions.

```swift
actor CloudSync: CKSyncEngineDelegate, SyncEngineFactory {   // the delegate protocol requires AnyObject & Sendable
  func handleEvent(_ event: CKSyncEngine.Event, syncEngine: CKSyncEngine) async         // → driver.handle(_:from:)
  func nextRecordZoneChangeBatch(_ context: CKSyncEngine.SendChangesContext,
                                 syncEngine: CKSyncEngine) async -> CKSyncEngine.RecordZoneChangeBatch?
}
```

- **Startup:** unless `sync.paused`, check the account first (below), then load `sync_engine_state.data` (a `CKSyncEngine.State.Serialization`, Codable, stored as JSON) and create `CKSyncEngine(.init(database: container.privateCloudDatabase, stateSerialization: saved, delegate: self))`. On the very first run (no saved state, which includes a fresh database), add `.saveZone(Learner)` as a pending database change.
- **`.stateUpdate`:** persist the serialization immediately (in the same database, its own small transaction), except while fetched events wait to be stored (below).
- **New local events:** `LearnerStore` inserts the `sync_pending` row **in the same transaction** as the event append. After the commit, `pendingAdditions()` yields the record names and the driver calls `syncEngine.state.add(pendingRecordZoneChanges: [.saveRecord(recordID)])`. A synced setting is yielded on every change, even when already pending, since its upload may be in flight with the old value. Crash safety: whenever an engine starts (launch, unpause, account switch), re-add every `sync_pending` row the engine doesn't list as pending (subscribing to `pendingAdditions()` before reading the table, so nothing falls between). The store is the source of truth for what is pending.
- **What Storage provides** (`LearnerStore`, CloudKit-agnostic; records are LearningCore's `SyncRecord`, system fields opaque bytes): `pendingChanges()`, `pendingAdditions()`, `addPending(recordNames:)`, `removePending(recordNames:)`, `markEverythingPending()` (first sign-in, `.encryptedDataReset`), `syncRecord(named:)` (the record provider; nil when the row is gone or the setting is device-scoped), `insertRemote(records:)` (stores each event's payload bytes as received, skips records that aren't valid events), `applyRemote(_:)` for settings (returns `.keepLocal` or `.takeRemote`), `syncEngineState()` / `saveSyncEngineState(_:)`, `systemFields(recordName:)` / `saveSystemFields(_:recordName:)` / `removeSystemFields(recordNames:)` / `removeAllSystemFields()`, `syncAccount()` / `setSyncAccount(_:)` (the iCloud account the database belongs to, in `local_meta`), `devicePlatforms()` (the status line's device list), `eraseProgress()` for zone deletion and Reset, and `moveAside(_:as: .archive, clock:)` for the account switch.
- **System fields** are cached for settings only. An event is immutable, so it is always saved as a new record; when the server already has that ID it answers `.serverRecordChanged`, which counts as saved.
- **`nextRecordZoneChangeBatch`:**
  - Filter pending saves to `context.options.scope`, and take at most 400 at a time (CloudKit's per-operation limit).
  - Load their records from the driver first, then build the batch with `await CKSyncEngine.RecordZoneChangeBatch(pendingChanges:recordProvider:)`, which sizes it to CloudKit's limits; the provider only looks the loaded records up.
  - A pending record whose row is gone (it shouldn't be), or a device-scoped setting, is removed from the engine and from `sync_pending`.
- **`.sentRecordZoneChanges`:**
  - Remove saved records from `sync_pending` and store a saved setting's new system fields. A setting whose stored value changed while its upload was in flight stays pending and is added again.
  - For each failed save, branch on the error:
    - `.serverRecordChanged` on an `Event`: the same UUID already exists remotely; treat it as success.
    - `.serverRecordChanged` on a `Setting`: store the server record's system fields, merge last-writer-wins, and re-add the save only if the local value wins (otherwise it is no longer pending). A server record that can't be read is replaced by the local value.
    - `.zoneNotFound`: add `.saveZone`, clear the record's cached system fields, then re-add the save.
    - `.unknownItem`: clear the cached system fields and re-add.
    - Network and transient errors (busy, rate-limited, cancelled, a lost response): CKSyncEngine retries; the save goes back to the engine in case it dropped it, and a network error shows "Waiting for network".
    - `.quotaExceeded` and anything else: logged and surfaced as "Sync paused" with a reason in Settings. The record stays in `sync_pending` but isn't re-added to the engine (no retry loop); the next engine start sends it again. The reason clears after a later batch saves records with no such failure.
- **`.fetchedRecordZoneChanges`:**
  - Modified `Event` records wait in memory and are inserted with **one** `insertRemote(records:)` call when the zone's fetch ends (`.didFetchRecordZoneChanges` or `.didFetchChanges`), or every 2,000 records: one transaction and at most one full replay per insert (`docs/05` § Replay), however the server ordered them. IDs already stored are ignored (`origin = 'remote'`). The state serializations of those batches are held back and saved only after the insert commits, so a crash never moves the change token past events that weren't stored; if the insert fails, no later state is saved, and the next launch fetches them again.
  - For each `Setting`, store the system fields and merge last-writer-wins. When this device holds a synced value that beats the server's, mark it pending again, so the server converges on the winner too.
  - Deletions happen only through Reset (below), which deletes the zone; record deletions are logged and ignored.
- **`.fetchedDatabaseChanges` with our zone deleted:**
  - reason `.deleted` (Reset on another device) or `.purged` (the learner deleted the app's iCloud data in Settings): delete local events, derived state and synced settings (keep device settings), clear `sync_pending` and `cloud_system_fields`, recreate the zone, and say once "Your progress was reset on another device" (a notice under the iCloud row until dismissed). The deletion of this device's own Reset is skipped.
  - reason `.encryptedDataReset`: clear every cached system field, recreate the zone and mark every local event and setting pending, so this device uploads everything again.
- **`.accountChange`** (task M7.4). The database belongs to the first iCloud account it syncs with (`setSyncAccount`, kept in `local_meta`, so a sign-out in between doesn't hide a change of account):
  - `signIn` to that account, or with no account recorded yet: record it, keep local data and mark every local event and synced setting pending (first upload; events the server already has count as saved).
  - `signOut`: keep everything local so the app works offline; the status says "iCloud is off — progress stays on this device". The engine stays, to report the next sign-in.
  - `switchAccounts`, or `signIn` to a different account than the recorded one: release the engine at once (nothing of this device reaches the new account), pause, and show the alert "This device has progress from another iCloud account". On confirm, move `learner.sqlite` to `learner-<date>.archive.sqlite`, open a fresh database bound to the new account (the App replaces its store), and start a new engine from no state, which fetches the new account's data. On cancel, set `sync.paused` (status "Sync paused · Another iCloud account is signed in"); unpausing checks the account again and asks again. If the signed-in account changed again while the alert was up, confirming archives nothing and checks the account afresh.
  - **At launch** the driver compares the signed-in account (`CKContainer.accountStatus()` and `userRecordID()`) with the recorded one before creating an engine, so a switch made while the app wasn't running asks first too.
- **Don't call** `fetchChanges` or `sendChanges` from inside `handleEvent` (nor release an engine there: the driver drops its reference and discards it afterwards). The App calls `syncNow()` (fetch, then send) when the app goes to the background and after a lesson step completes.
- **Reset progress** (Debug menu only in the MVP): clear local events and derived state, drop the engine's pending saves and delete the zone; when the deletion is sent, recreate the zone and re-add whatever was done since. While sync is paused, Reset clears only this device.
- **Pause sync** (`sync.paused`, Settings → Sync): store the fetched events still waiting (which persists the state serialization), then release the engine (no fetches or sends). Unpausing creates the engine again from the saved state. New events keep collecting in `sync_pending` meanwhile.
- **Build switch:** `CloudSync` exists only when `ITA_SYNC_ENABLED` and `ITA_ICLOUD_ENTITLEMENT` are YES (`AppConfig.syncAllowed`); otherwise `DisabledSync` reports "Sync off in this build". `ITA_ICLOUD_ENTITLEMENT` is set by the owner's Signing.xcconfig together with `CODE_SIGN_ENTITLEMENTS = Config/Italiano.entitlements` (iOS has no public API to read the app's own entitlements, and `CKContainer` crashes without them).

## Merge rules (LearningCore `Sync/MergeRules.swift`, unit-tested)

- An event is identified by its ID: insert if absent, ignore if present. Never update.
- Replay order is `(at, id)` on every device, so states converge regardless of arrival order.
- Clock skew: no correction. A device with a wrong clock produces events at the wrong times, but every device computes the same state from them.
- Settings: last-writer-wins by `(updatedAt, deviceId)`: a tie on `updatedAt` goes to the lexically larger `deviceId` (UTF-8 bytes), and a full tie (never expected) to the larger canonical value JSON, so the merge is commutative and every device keeps the same value. Device-scoped settings never sync.

## Status UI

Settings → Sync (`Settings.png`) shows an iCloud row with one of these states (`SyncStatusText`):

- "Synced 2 minutes ago · iPhone, iPad, Mac" — device names come from the `deviceId`s seen in events, mapped to the `platform` field of their latest `session` event (`docs/05`; `LearnerStore.devicePlatforms()`), plus this device's own, listed iPhone, iPad, Mac. The time reads "just now" under a minute, then "1 minute ago", "N minutes ago", "N hours ago", "N days ago", refreshed every minute.
- "Syncing…" (a fetch or a send is running, or nothing has finished yet)
- "Waiting for network"
- "iCloud is off — progress stays on this device" (no account, restricted, or the account needs attention)
- "Sync paused · <reason>": "Paused in Settings", "Another iCloud account is signed in", "iCloud storage is full", "iCloud refused a change"
- "Sync off in this build" (no entitlement, `ITA_SYNC_ENABLED = NO`, or a review build)

When several apply, the first in this order wins: paused, iCloud off, a refusal or full storage, waiting for network, syncing, synced. Under the row: the "Pause sync" switch (not in a build without sync) and the one-time notice. There are no modal alerts except the account switch, whose buttons are "Use This Account" and "Pause Sync".

## Tests

1. **Unit (Linux, LearningCore):** a two- and three-device simulator. Devices create events offline, then exchange them in random orders and with duplicates. Assert that derived states (memory, introductions, unit progress, daily activity) are byte-identical, for 1,000 seeded runs.
2. **Integration (macOS, Storage):** append events, apply remote batches out of order, assert that the incremental replay equals a full rebuild.
3. **Driver (any platform, App tests through `scripts/check-app-logic.sh --test`):** `SyncDriver` against a fake engine with CKSyncEngine's semantics (pending changes, a change token, batches, account announcements, retryable failures kept) over in-memory private databases with CloudKit's save rules (change tags, `.serverRecordChanged`, `.zoneNotFound`, `.unknownItem`, zone deletion with a reason). Every handler has a test, including killing the app between the append and `state.add` (the event is still uploaded after relaunch), the account changes with the archive, and a seeded two-device simulation (offline work, the same settings changed on both, partial syncs, crashes, pauses, skewed clocks, random batch sizes) that ends with identical events, derived state equal to a full rebuild, the last writer's settings and nothing pending.
4. **Adapter:** `CloudSync` is only syntax-checked on Linux; the owner's first signed build type-checks it and runs the manual checklist.
5. **Manual (M7 checklist, real devices on one iCloud account):**
   - Answer on the iPhone in airplane mode, answer on the iPad, reconnect both, and confirm the Words screen matches on all three.
   - Settings change on two devices within a minute: the last write wins.
   - Sign out and in.
   - Switch accounts: confirm (an archive appears beside `learner.sqlite`, the other account's progress arrives) and cancel (sync paused, nothing reaches the other account).
   - Fresh install restores progress.
   - 10,000 events first sync completes and the app stays responsive.
   - Reset progress from the Debug menu on one device: the others erase once and show the notice.

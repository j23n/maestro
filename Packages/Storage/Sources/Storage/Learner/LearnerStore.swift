import Foundation
import GRDB
import LearningCore

/// The learner database, `learner.sqlite` in Application Support (docs/02 § Storage, docs/03 § The learner database).
///
/// - **Events** are the source of truth: appended, never updated (docs/05 § Events). `append` inserts this
///   device's events with their `sync_pending` rows and applies them to the derived state, all in one transaction;
///   `insertRemote` inserts synced events (ignoring IDs it already has) and applies them the same way.
/// - **Derived state** is LearningCore's `LearnerState`, kept in memory and persisted as the docs/03 tables plus a
///   checkpoint (see `DerivedStore`). New events go through `Replay.applyIncremental(to:)`; when one sorts before
///   the last applied event (a late sync), the whole log is replayed instead (docs/05 § Replay). At open, a changed
///   `derived_version` or pack `content_hash`, or a missing checkpoint, triggers that full rebuild.
/// - **Settings** (docs/08 § Settings), **sync bookkeeping** (docs/08) and **telemetry bookkeeping** (docs/12) live
///   in the same file; see the extensions.
///
/// Writes are serialised on GRDB's writer queue and the in-memory state changes there, in commit order, after the
/// commit. A failed transaction changes nothing, in the file or in memory. Queries are `async` and never run on the
/// caller's actor; `state` and `settings` are synchronous snapshots of the last commit.
public final class LearnerStore: Sendable {
    public struct Options: Sendable, Equatable {
        /// Write the derived-state checkpoint after this many incrementally applied events (rebuilds always write
        /// one). Opening replays at most this many events on top of the checkpoint.
        public var checkpointInterval: Int

        public init(checkpointInterval: Int = 250) {
            self.checkpointInterval = max(1, checkpointInterval)
        }
    }

    /// The outcome of `append` and `insertRemote`.
    public struct AppendResult: Sendable, Equatable {
        /// The events that were new, in input order (events whose ID was already stored are ignored).
        public var inserted: [Event]
        /// True when an event sorted before the last applied one and the whole log was replayed.
        public var rebuilt: Bool
        /// The derived state after the commit.
        public var state: LearnerState
    }

    /// `Italiano/learner.sqlite` under Application Support (docs/02).
    public static let directoryName = "Italiano"
    public static let fileName = "learner.sqlite"

    public let url: URL
    /// This install's device ID (lowercase UUID), created with the database (`local_meta`).
    public let deviceId: String
    /// The content the derived state is computed against (the pack's `ContentIndex`).
    public let content: ContentIndex
    /// Why the derived state was rebuilt from the whole log when the store opened; nil when the checkpoint was
    /// current.
    public let launchRebuild: RebuildReason?
    public let options: Options

    let pool: DatabasePool
    let clock: any LearningCore.Clock
    let logger: any CoreLogger
    let live: Locked<Live>

    /// What the store keeps in memory: changed only on the writer queue, after a commit.
    struct Live: Sendable {
        var state: LearnerState
        var settings: LearnerSettings
        /// Events applied since the last checkpoint was written.
        var sinceCheckpoint: Int
        var nextObserver = 0
        var stateObservers: [Int: AsyncStream<LearnerState>.Continuation] = [:]
        var settingsObservers: [Int: AsyncStream<LearnerSettings>.Continuation] = [:]
    }

    // MARK: Opening

    /// Opens (or creates) the database at `url`, runs the migrations and loads the derived state, rebuilding it
    /// from the events when needed. Blocking (a rebuild of a long log takes a while): call it off the main actor,
    /// or use `open(url:content:clock:ids:options:)`.
    ///
    /// Throws `StorageError.corrupt` when the file isn't a usable learner database (task M3.9 recovers with
    /// `openRecovering`).
    public init(
        url: URL, content: ContentIndex, clock: any LearningCore.Clock, ids: any UUIDSource,
        options: Options = Options(), logger: (any CoreLogger)? = nil
    ) throws(StorageError) {
        let path = url.path
        let logger = logger ?? StorageLog.ReplayLogger()
        let pool = try Self.openPool(url)
        do {
            try LearnerSchema.migrator().migrate(pool)
        } catch {
            let wrapped = StorageError.wrap(error, path: path)
            if case .file = wrapped { throw Self.failed(wrapped) }
            throw Self.failed(.corrupt(path: path, reason: "migration failed: \(error)"))
        }
        let opened: Opened
        do {
            opened = try pool.write { db in try Self.prepare(db, content: content, ids: ids, logger: logger) }
        } catch {
            throw Self.failed(StorageError.wrap(error, path: path))
        }
        self.url = url
        self.pool = pool
        self.content = content
        self.clock = clock
        self.options = options
        self.logger = logger
        self.deviceId = opened.deviceId
        self.launchRebuild = opened.rebuild
        self.live = Locked(Live(state: opened.state, settings: opened.settings, sinceCheckpoint: 0))
        if let reason = opened.rebuild { StorageLog.rebuilt(reason: reason.rawValue, events: opened.eventCount) }
    }

    /// Opens the store off the caller's actor.
    @concurrent
    public static func open(
        url: URL, content: ContentIndex, clock: any LearningCore.Clock, ids: any UUIDSource,
        options: Options = Options()
    ) async throws(StorageError) -> LearnerStore {
        try LearnerStore(url: url, content: content, clock: clock, ids: ids, options: options)
    }

    private struct Opened {
        var deviceId: String
        var state: LearnerState
        var settings: LearnerSettings
        var rebuild: RebuildReason?
        var eventCount: Int
    }

    private static func openPool(_ url: URL) throws(StorageError) -> DatabasePool {
        let path = url.path
        do {
            try FileManager.default.createDirectory(
                at: url.deletingLastPathComponent(),
                withIntermediateDirectories: true)
        } catch {
            throw failed(.file(path: path, reason: "can't create its folder: \(error)"))
        }
        var config = Configuration()
        config.label = "learner"
        do {
            return try DatabasePool(path: path, configuration: config)
        } catch {
            throw failed(StorageError.wrap(error, path: path))
        }
    }

    private static func failed(_ error: StorageError) -> StorageError {
        StorageLog.learnerFailed(error)
        return error
    }

    /// The device ID, the settings and the derived state (loaded from the checkpoint, or rebuilt).
    private static func prepare(
        _ db: Database, content: ContentIndex, ids: any UUIDSource,
        logger: any CoreLogger
    ) throws -> Opened {
        let deviceId: String
        if let stored = try String.fetchOne(db, sql: "SELECT value FROM local_meta WHERE key = 'device_id'") {
            deviceId = stored
        } else {
            deviceId = ids.next().lowercased()
            try db.execute(sql: "INSERT INTO local_meta (key, value) VALUES ('device_id', ?)", arguments: [deviceId])
        }
        let settings = LearnerSettings(records: try SettingsTable.all(db, logger: logger))
        let meta = try DerivedMeta.read(db)
        var reason = Replay.rebuildReason(
            storedDerivedVersion: meta.derivedVersion,
            storedContentHash: meta.contentHash, content: content)
        if reason == nil {
            if let loaded = try DerivedStore.load(db, meta: meta, content: content, logger: logger) {
                // Save the caught-up state so the next launch replays nothing.
                if loaded.caughtUp > 0 { try DerivedStore.writeCheckpoint(db, loaded.state) }
                return Opened(
                    deviceId: deviceId, state: loaded.state, settings: settings, rebuild: nil,
                    eventCount: meta.eventCount ?? 0)
            }
            reason = .noDerivedState
        }
        let state = try DerivedStore.rebuild(db, content: content, logger: logger)
        let count = try DerivedMeta.read(db).eventCount ?? 0
        return Opened(deviceId: deviceId, state: state, settings: settings, rebuild: reason, eventCount: count)
    }

    /// Closes the database (GRDB finishes pending writes first) and ends the observation streams.
    public func close() throws(StorageError) {
        live.withLock { live in
            for continuation in live.stateObservers.values { continuation.finish() }
            for continuation in live.settingsObservers.values { continuation.finish() }
            live.stateObservers = [:]
            live.settingsObservers = [:]
        }
        do {
            try pool.close()
        } catch {
            throw StorageError.wrap(error, path: url.path)
        }
    }

    // MARK: Derived state

    /// The derived state after the last commit.
    public var state: LearnerState { live.current.state }

    /// The current state, then the state after every commit that changes it (the newest only, for a slow reader).
    public func states() -> AsyncStream<LearnerState> {
        let (stream, continuation) = AsyncStream.makeStream(of: LearnerState.self, bufferingPolicy: .bufferingNewest(1))
        let id = live.withLock { live -> Int in
            let id = live.nextObserver
            live.nextObserver += 1
            live.stateObservers[id] = continuation
            continuation.yield(live.state)
            return id
        }
        continuation.onTermination = { [weak self] _ in
            self?.live.withLock { live in live.stateObservers[id] = nil }
        }
        return stream
    }

    // MARK: Appending

    /// Appends this device's events (`origin = 'local'`) with their `sync_pending` rows and applies them, in one
    /// transaction. An event whose ID is already stored is ignored, so appending is idempotent.
    @discardableResult
    public func append(_ events: [Event]) async throws(StorageError) -> AppendResult {
        let entries = try Self.entries(events, origin: .local)
        return try await write { db in try self.commit(db, entries, pending: true) }
    }

    @discardableResult
    public func append(_ event: Event) async throws(StorageError) -> AppendResult {
        try await append([event])
    }

    /// Appends an event without waiting, for synchronous callers such as the App's `EventAttemptSink`. Calls are
    /// written in the order they are made (GRDB's writer queue is serial), so a device's events never arrive out
    /// of order and never trigger a rebuild. `completion` runs on a background queue; failures are also logged.
    public func enqueueAppend(
        _ event: Event,
        completion: (@Sendable (Result<AppendResult, StorageError>) -> Void)? = nil
    ) {
        let entries: [Entry]
        do {
            entries = try Self.entries([event], origin: .local)
        } catch {
            StorageLog.writeFailed(error)
            completion?(.failure(error))
            return
        }
        let path = url.path
        pool.asyncWriteWithoutTransaction { db in
            let result: Result<AppendResult, StorageError>
            do {
                result = .success(try self.commit(db, entries, pending: true))
            } catch {
                let wrapped = StorageError.wrap(error, path: path)
                StorageLog.writeFailed(wrapped)
                result = .failure(wrapped)
            }
            completion?(result)
        }
    }

    /// Inserts events from other devices (`origin = 'remote'`), ignoring IDs already stored (docs/08 § Merge
    /// rules), and applies the new ones, in one transaction. No `sync_pending` rows: they came from iCloud.
    @discardableResult
    public func insertRemote(_ events: [Event]) async throws(StorageError) -> AppendResult {
        let entries = try Self.entries(events, origin: .remote)
        return try await write { db in try self.commit(db, entries, pending: false) }
    }

    /// Inserts `Event` records fetched from CloudKit. The payload bytes are stored exactly as received, so fields a
    /// newer client added survive (the reducer reads what it knows). Records that aren't valid events are skipped
    /// and logged.
    @discardableResult
    public func insertRemote(records: [SyncRecord]) async throws(StorageError) -> AppendResult {
        var entries: [Entry] = []
        for record in records {
            guard let event = try? RecordMapping.event(from: record),
                case .bytes(let payload)? = record.fields[RecordMapping.EventField.payload]
            else {
                StorageLog.skippedRecord(record.recordName)
                continue
            }
            let row = EventRow(
                id: event.id, at: event.at, tzOffsetMin: event.tzOffsetMin, type: event.type,
                deviceId: event.deviceId, schema: event.schema, packVersion: event.packVersion,
                payload: String(decoding: payload, as: UTF8.self), origin: .remote)
            entries.append(Entry(row: row, event: event))
        }
        let batch = entries
        return try await write { db in try self.commit(db, batch, pending: false) }
    }

    /// Replays the whole log and rewrites every derived table and the checkpoint (the Debug menu's "rebuild state
    /// from events"; also what `append` does when an event sorts before the last applied one).
    @discardableResult
    public func rebuildAll() async throws(StorageError) -> LearnerState {
        try await write { db in
            var state = LearnerState()
            try db.inTransaction(.immediate) {
                state = try DerivedStore.rebuild(db, content: self.content, logger: self.logger)
                return .commit
            }
            self.publish(state: state, sinceCheckpoint: 0)
            return state
        }
    }

    /// Writes the checkpoint now if events were applied since the last one (call it when the app goes to the
    /// background, so the next launch replays nothing).
    public func checkpoint() async throws(StorageError) {
        try await write { db in
            let live = self.live.current
            guard live.sinceCheckpoint > 0 else { return }
            try db.inTransaction(.immediate) {
                try DerivedStore.writeCheckpoint(db, live.state)
                return .commit
            }
            self.live.withLock { $0.sinceCheckpoint = 0 }
        }
    }

    // MARK: Internals

    /// An event to insert: its row (what is stored) and its typed form (what replay applies).
    struct Entry: Sendable {
        var row: EventRow
        var event: Event
    }

    static func entries(_ events: [Event], origin: EventOrigin) throws(StorageError) -> [Entry] {
        var entries: [Entry] = []
        entries.reserveCapacity(events.count)
        for event in events {
            var typed = event
            typed.origin = origin
            entries.append(Entry(row: try EventRow(typed), event: typed))
        }
        return entries
    }

    /// Runs `body` on the writer queue, outside a transaction (it opens its own), mapping errors to `StorageError`.
    func write<T: Sendable>(_ body: @escaping @Sendable (Database) throws -> T) async throws(StorageError) -> T {
        do {
            return try await pool.writeWithoutTransaction(body)
        } catch {
            let wrapped = StorageError.wrap(error, path: url.path)
            StorageLog.writeFailed(wrapped)
            throw wrapped
        }
    }

    /// Runs `body` on a reader, mapping errors to `StorageError`.
    func read<T: Sendable>(_ body: @escaping @Sendable (Database) throws -> T) async throws(StorageError) -> T {
        do {
            return try await pool.read(body)
        } catch {
            throw StorageError.wrap(error, path: url.path)
        }
    }

    /// Inserts the events, their `sync_pending` rows (`pending`) and the derived changes in one transaction, then
    /// publishes the new state. Runs on the writer queue, so `live` holds the state of the previous commit.
    func commit(_ db: Database, _ entries: [Entry], pending: Bool) throws -> AppendResult {
        let before = live.current
        var next = before.state
        var inserted: [Event] = []
        var rebuilt = false
        var sinceCheckpoint = before.sinceCheckpoint
        let now = clock.nowMs()
        try db.inTransaction(.immediate) {
            let insert = try db.cachedStatement(
                sql: """
                    INSERT INTO events (\(EventRow.columns)) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO NOTHING
                    """)
            for entry in entries {
                try insert.execute(arguments: entry.row.arguments)
                guard db.changesCount > 0 else { continue }
                inserted.append(entry.event)
                if pending {
                    try SyncTables.addPending(
                        db, recordName: RecordMapping.recordName(for: entry.event), type: .event,
                        at: now)
                }
            }
            guard !inserted.isEmpty else { return .commit }
            if Replay.applyIncremental(to: &next, events: inserted, content: content, logger: logger) {
                try DerivedStore.writeChanges(db, from: before.state, to: next)
                sinceCheckpoint += inserted.count
                if sinceCheckpoint >= options.checkpointInterval {
                    try DerivedStore.writeCheckpoint(db, next)
                    sinceCheckpoint = 0
                }
                var meta = try DerivedMeta.read(db)
                meta.lastApplied = next.lastApplied
                meta.eventCount = (meta.eventCount ?? 0) + inserted.count
                try meta.write(db)
            } else {
                next = try DerivedStore.rebuild(db, content: content, logger: logger)
                rebuilt = true
                sinceCheckpoint = 0
            }
            return .commit
        }
        if !inserted.isEmpty { publish(state: next, sinceCheckpoint: sinceCheckpoint) }
        return AppendResult(inserted: inserted, rebuilt: rebuilt, state: next)
    }

    /// Stores the committed state in memory and tells the observers. Called on the writer queue after a commit.
    func publish(state: LearnerState, sinceCheckpoint: Int) {
        live.withLock { live in
            live.state = state
            live.sinceCheckpoint = sinceCheckpoint
            for continuation in live.stateObservers.values { continuation.yield(state) }
        }
    }
}

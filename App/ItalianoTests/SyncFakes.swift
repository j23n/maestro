import Foundation
import LearningCore
import Storage

@testable import Italiano

// The in-memory sync world of the App tests (docs/08 § Tests; task M7.2's proxy): a private database per iCloud
// account (`FakeCloud`), a fake CKSyncEngine (`FakeEngine`) that keeps pending changes and a change token, sends in
// batches through `SyncDriver.recordsToSend` with CloudKit's save rules, and fetches in batches; and a device's
// iCloud (`FakeICloud`, the `SyncEngineFactory`). Every class guards its state with a lock, hence
// `@unchecked Sendable`.

/// One iCloud account's private database with the `Learner` zone: records with change tags, a sequence number per
/// change for fetches, and zone deletions with their reason.
final class FakeCloud: @unchecked Sendable {
    struct Stored {
        var record: SyncRecord
        var tag: Int
        var seq: Int
    }

    enum SaveOutcome {
        case saved(ServerRecord)
        case failed(FailedSave)
    }

    struct Changes {
        var deletions: [ZoneDeletionReason]
        var records: [(seq: Int, record: ServerRecord)]
        var token: Int
    }

    private let lock = NSLock()
    private var zoneExists = false
    private var records: [String: Stored] = [:]
    private var deletions: [(seq: Int, reason: ZoneDeletionReason)] = []
    private var seq = 0
    private var _networkUp = true
    private var _quotaExceeded = false
    private var _refused: Set<String> = []
    private var _transient: Set<String> = []
    private var _savedCount = 0

    var networkUp: Bool {
        get { lock.withLock { _networkUp } }
        set { lock.withLock { _networkUp = newValue } }
    }
    var quotaExceeded: Bool {
        get { lock.withLock { _quotaExceeded } }
        set { lock.withLock { _quotaExceeded = newValue } }
    }
    /// Record names refused for good (`.other`).
    var refused: Set<String> {
        get { lock.withLock { _refused } }
        set { lock.withLock { _refused = newValue } }
    }
    /// Record names that fail once with a retryable error.
    var transientOnce: Set<String> {
        get { lock.withLock { _transient } }
        set { lock.withLock { _transient = newValue } }
    }
    var savedCount: Int { lock.withLock { _savedCount } }
    var hasZone: Bool { lock.withLock { zoneExists } }
    var recordNames: Set<String> { lock.withLock { Set(records.keys) } }
    var eventIDs: Set<String> {
        lock.withLock { Set(records.values.filter { $0.record.recordType == .event }.map(\.record.recordName)) }
    }

    func record(named name: String) -> SyncRecord? { lock.withLock { records[name]?.record } }

    func setting(_ key: SettingKey) -> SettingRecord? {
        record(named: RecordMapping.recordName(forSettingKey: key.rawValue)).flatMap {
            try? RecordMapping.setting(from: $0)
        }
    }

    static func systemFields(_ name: String, tag: Int) -> Data { Data("\(name)#\(tag)".utf8) }

    static func tag(_ data: Data?) -> Int? {
        guard let data, let text = String(data: data, encoding: .utf8), let hash = text.lastIndex(of: "#") else {
            return nil
        }
        return Int(text[text.index(after: hash)...])
    }

    func saveZone() { lock.withLock { zoneExists = true } }

    /// Deletes the zone and its records (Reset elsewhere, a purge in iCloud settings, an encrypted-data reset).
    func deleteZone(reason: ZoneDeletionReason) {
        lock.withLock {
            zoneExists = false
            records = [:]
            seq += 1
            deletions.append((seq, reason))
        }
    }

    /// Loses the zone without telling anyone (so the next save meets `.zoneNotFound`).
    func dropZoneSilently() {
        lock.withLock {
            zoneExists = false
            records = [:]
        }
    }

    /// Another client writes a record, whatever its change tag.
    func overwrite(_ record: SyncRecord) {
        lock.withLock {
            seq += 1
            let tag = (records[record.recordName]?.tag ?? 0) + 1
            records[record.recordName] = Stored(record: record, tag: tag, seq: seq)
        }
    }

    /// Loses one record without telling anyone (so a save with its old change tag meets `.unknownItem`).
    func dropRecordSilently(_ name: String) { _ = lock.withLock { records.removeValue(forKey: name) } }

    /// CloudKit's save with `ifServerRecordUnchanged`: a record that exists needs its current change tag; one that
    /// doesn't must come without a tag.
    func save(_ outgoing: OutgoingRecord) -> SaveOutcome {
        lock.withLock {
            let name = outgoing.record.recordName
            func fail(_ kind: SyncErrorKind, _ server: ServerRecord? = nil) -> SaveOutcome {
                .failed(FailedSave(recordName: name, error: kind, serverRecord: server))
            }
            guard _networkUp else { return fail(.network) }
            guard zoneExists else { return fail(.zoneNotFound) }
            if _transient.remove(name) != nil { return fail(.transient) }
            if _refused.contains(name) { return fail(.other) }
            if _quotaExceeded { return fail(.quotaExceeded) }
            let sentTag = Self.tag(outgoing.systemFields)
            if let stored = records[name] {
                guard sentTag == stored.tag else {
                    let server = ServerRecord(
                        record: stored.record, systemFields: Self.systemFields(name, tag: stored.tag))
                    return fail(.serverRecordChanged, server)
                }
            } else if sentTag != nil {
                return fail(.unknownItem)
            }
            seq += 1
            let tag = (records[name]?.tag ?? 0) + 1
            records[name] = Stored(record: outgoing.record, tag: tag, seq: seq)
            _savedCount += 1
            return .saved(ServerRecord(record: outgoing.record, systemFields: Self.systemFields(name, tag: tag)))
        }
    }

    /// Everything after `token`: zone deletions, then the records changed since, in the order they were saved.
    func changes(since token: Int) -> Changes {
        lock.withLock {
            let changed = records.values.filter { $0.seq > token }.sorted { $0.seq < $1.seq }
            return Changes(
                deletions: deletions.filter { $0.seq > token }.map(\.reason),
                records: changed.map {
                    (
                        $0.seq,
                        ServerRecord(
                            record: $0.record, systemFields: Self.systemFields($0.record.recordName, tag: $0.tag))
                    )
                },
                token: seq)
        }
    }
}

/// A device's iCloud: the signed-in account (and its database) and the engines it made.
final class FakeICloud: SyncEngineFactory, @unchecked Sendable {
    struct Account {
        var user: String
        var cloud: FakeCloud
    }

    private let lock = NSLock()
    private var _account: Account?
    private var _networkUp = true
    private var _engines: [FakeEngine] = []
    let fetchBatch: Int
    let sendBatch: Int
    let seed: String

    init(account: Account?, fetchBatch: Int = 3, sendBatch: Int = 4, seed: String = "icloud") {
        _account = account
        self.fetchBatch = fetchBatch
        self.sendBatch = sendBatch
        self.seed = seed
    }

    var account: Account? {
        get { lock.withLock { _account } }
        set { lock.withLock { _account = newValue } }
    }
    /// This device's network (the database's own switch fails every device).
    var networkUp: Bool {
        get { lock.withLock { _networkUp } }
        set { lock.withLock { _networkUp = newValue } }
    }
    var engines: [FakeEngine] { lock.withLock { _engines } }
    /// The engine in use (the last one made, unless it was discarded).
    var engine: FakeEngine? { lock.withLock { _engines.last.flatMap { $0.isDiscarded ? nil : $0 } } }

    func accountStatus() async -> SyncAccountStatus { account.map { .available(userID: $0.user) } ?? .noAccount }

    func makeEngine(stateSerialization: Data?, driver: SyncDriver) async -> any SyncEngine {
        let state = stateSerialization.flatMap { try? JSONDecoder().decode(FakeEngine.State.self, from: $0) }
        let engine = FakeEngine(
            state: state ?? FakeEngine.State(), icloud: self, driver: driver,
            seed: "\(seed)/\(lock.withLock { _engines.count })")
        lock.withLock { _engines.append(engine) }
        return engine
    }

    func discard(_ engine: any SyncEngine) async { (engine as? FakeEngine)?.discard() }
}

/// CKSyncEngine's behaviour as docs/08 relies on it: pending saves and database changes, a change token, the
/// account it last saw (a different one is announced as a switch), batches sized by the engine, retryable failures
/// kept pending and the others dropped (the driver re-adds what it wants), and a state serialization after every
/// change.
final class FakeEngine: SyncEngine, @unchecked Sendable {
    struct State: Codable, Equatable {
        var token = 0
        var saves: [String] = []
        var zoneSave = false
        var zoneDelete = false
        var user: String?
    }

    private let lock = NSLock()
    private var state: State
    private var discarded = false
    private var rng: SplitMix64
    private weak var icloud: FakeICloud?
    private weak var driver: SyncDriver?
    /// Called after each fetched batch is delivered, and before each batch is saved.
    private var _afterFetchedBatch: (@Sendable () async -> Void)?
    private var _beforeSave: (@Sendable () async -> Void)?

    init(state: State, icloud: FakeICloud, driver: SyncDriver, seed: String) {
        self.state = state
        self.icloud = icloud
        self.driver = driver
        rng = SplitMix64(seedString: seed)
    }

    var isDiscarded: Bool { lock.withLock { discarded } }
    var currentState: State { lock.withLock { state } }
    var afterFetchedBatch: (@Sendable () async -> Void)? {
        get { lock.withLock { _afterFetchedBatch } }
        set { lock.withLock { _afterFetchedBatch = newValue } }
    }
    var beforeSave: (@Sendable () async -> Void)? {
        get { lock.withLock { _beforeSave } }
        set { lock.withLock { _beforeSave = newValue } }
    }

    func discard() { lock.withLock { discarded = true } }

    // MARK: SyncEngine

    var pendingSaves: [String] { lock.withLock { state.saves } }

    func addPendingSaves(_ recordNames: [String]) {
        lock.withLock {
            var seen = Set(state.saves)
            for name in recordNames where seen.insert(name).inserted { state.saves.append(name) }
        }
    }

    func removePendingSaves(_ recordNames: [String]) {
        let gone = Set(recordNames)
        lock.withLock { state.saves.removeAll { gone.contains($0) } }
    }

    func addPendingZoneSave() {
        lock.withLock {
            state.zoneSave = true
            state.zoneDelete = false
        }
    }

    func addPendingZoneDelete() {
        lock.withLock {
            state.zoneDelete = true
            state.zoneSave = false
        }
    }

    func fetchChanges() async throws(SyncFailure) {
        let cloud = try await ready()
        await emit(.willFetchChanges)
        let changes = cloud.changes(since: lock.withLock { state.token })
        if !changes.deletions.isEmpty { await emit(.fetchedDatabaseChanges(zoneDeletions: changes.deletions)) }
        var start = 0
        while start < changes.records.count {
            let batch = Array(changes.records[start..<min(start + batchSize(\.fetchBatch), changes.records.count)])
            start += batch.count
            // CloudKit promises no order within a batch.
            let shuffled = lock.withLock { batch.map(\.record).seededShuffle(using: &rng) }
            await emit(.fetchedRecordZoneChanges(modified: shuffled, deletedRecordNames: []))
            lock.withLock { state.token = batch.last?.seq ?? state.token }
            await emitState()
            await afterFetchedBatch?()
        }
        lock.withLock { state.token = max(state.token, changes.token) }
        await emitState()
        await emit(.didFetchRecordZoneChanges)
        await emit(.didFetchChanges)
    }

    func sendChanges() async throws(SyncFailure) {
        let cloud = try await ready()
        await emit(.willSendChanges)
        for _ in 0..<1_000 {
            if let zone = takeDatabaseChange() {
                switch zone {
                case .delete:
                    cloud.deleteZone(reason: .deleted)
                    await emit(.sentDatabaseChanges(savedZone: false, deletedZone: true, failedZoneChange: nil))
                case .save:
                    cloud.saveZone()
                    await emit(.sentDatabaseChanges(savedZone: true, deletedZone: false, failedZoneChange: nil))
                }
                await emitState()
                continue
            }
            let names = lock.withLock { Array(state.saves.prefix(batchSize(\.sendBatch))) }
            guard !names.isEmpty, let driver, !isDiscarded else { break }
            let outgoing = await driver.recordsToSend(names, from: self)
            guard !outgoing.isEmpty else { break }  // `nextRecordZoneChangeBatch` returned nil
            await beforeSave?()
            removePendingSaves(outgoing.map(\.record.recordName))
            var saved: [ServerRecord] = []
            var failed: [FailedSave] = []
            for record in outgoing {
                switch cloud.save(record) {
                case .saved(let server): saved.append(server)
                case .failed(let failure):
                    failed.append(failure)
                    if [.network, .transient].contains(failure.error) { addPendingSaves([failure.recordName]) }
                }
            }
            await emit(.sentRecordZoneChanges(saved: saved, failed: failed))
            await emitState()
            if failed.contains(where: { $0.error == .network }) { break }
        }
        await emit(.didSendChanges)
    }

    // MARK: Helpers

    private enum ZoneChange { case save, delete }

    private func takeDatabaseChange() -> ZoneChange? {
        lock.withLock {
            if state.zoneDelete {
                state.zoneDelete = false
                return .delete
            }
            if state.zoneSave {
                state.zoneSave = false
                return .save
            }
            return nil
        }
    }

    private func batchSize(_ key: KeyPath<FakeICloud, Int>) -> Int { icloud?[keyPath: key] ?? 1 }

    /// The account check CKSyncEngine makes before an operation: a first sign-in or a different account is
    /// announced, no account or no network fails.
    private func ready() async throws(SyncFailure) -> FakeCloud {
        guard !isDiscarded, let icloud else { throw SyncFailure(.transient) }
        guard let account = icloud.account else { throw SyncFailure(.accountUnavailable) }
        let previous = lock.withLock { () -> String? in
            defer { state.user = account.user }
            return state.user
        }
        if previous == nil {
            await emit(.accountChange(.signIn(currentUser: account.user)))
        } else if let previous, previous != account.user {
            await emit(.accountChange(.switchAccounts(previousUser: previous, currentUser: account.user)))
        }
        guard !isDiscarded else { throw SyncFailure(.transient) }
        guard icloud.networkUp, account.cloud.networkUp else { throw SyncFailure(.network) }
        return account.cloud
    }

    func emit(_ event: SyncEngineEvent) async {
        guard !isDiscarded, let driver else { return }
        await driver.handle(event, from: self)
    }

    private func emitState() async {
        guard let data = try? JSONEncoder().encode(currentState) else { return }
        await emit(.stateUpdate(data))
    }
}

/// A store reference the driver's `onStoreReplaced` can update from any task.
final class StoreBox: @unchecked Sendable {
    private let lock = NSLock()
    private var _store: LearnerStore
    private var _replacements = 0

    init(_ store: LearnerStore) { _store = store }

    var store: LearnerStore { lock.withLock { _store } }
    var replacements: Int { lock.withLock { _replacements } }

    func replace(_ store: LearnerStore) {
        lock.withLock {
            _store = store
            _replacements += 1
        }
    }
}

/// Collects the driver's log lines (record names and error kinds only).
final class LogLines: CoreLogger, @unchecked Sendable {
    private let lock = NSLock()
    private var _lines: [String] = []
    var lines: [String] { lock.withLock { _lines } }
    func log(_ message: String) { lock.withLock { _lines.append(message) } }
}

/// Waits (yielding, then sleeping a little) until `condition` holds, for work the driver does on its own tasks.
func eventually(_ condition: () async -> Bool) async -> Bool {
    for attempt in 0..<400 {
        if await condition() { return true }
        if attempt < 50 { await Task.yield() } else { try? await Task.sleep(nanoseconds: 5_000_000) }
    }
    return await condition()
}

/// `eventually` for main-actor state (view models).
@MainActor
func eventuallyOnMain(_ condition: () -> Bool) async -> Bool {
    for attempt in 0..<400 {
        if condition() { return true }
        if attempt < 50 { await Task.yield() } else { try? await Task.sleep(nanoseconds: 5_000_000) }
    }
    return condition()
}

import Foundation
import LearningCore
import Storage

/// Runs iCloud sync (docs/08 § The sync engine, tasks M7.2–M7.4): turns the sync engine's events into
/// `LearnerStore` calls, provides the records to upload, and handles pause, Reset and account changes. The engine is
/// a `SyncEngine` (`CloudSync` wraps CKSyncEngine; the tests use a fake over an in-memory database), so every
/// handler runs and is tested on any platform. The store is the source of truth for what is pending
/// (`sync_pending`); the engine's list is rebuilt from it at every start.
actor SyncDriver: SyncControlling {
    struct Configuration: Sendable {
        /// This device's family (the status line always lists it).
        var platform: Platform
        /// Fetched events are inserted together at the end of the zone's fetch, or when this many are waiting: one
        /// transaction, and at most one full replay per insert (docs/05 § Replay).
        var insertBatchLimit: Int

        init(platform: Platform, insertBatchLimit: Int = 2_000) {
            self.platform = platform
            self.insertBatchLimit = max(1, insertBatchLimit)
        }
    }

    /// Opens a learner store at a URL: the fresh database after the account-switch archive.
    typealias StoreOpener = @Sendable (URL) async throws -> LearnerStore

    /// The learner store in use (a new one after an account switch; `onStoreReplaced` tells the App).
    private(set) var store: LearnerStore
    private let factory: any SyncEngineFactory
    private let openStore: StoreOpener
    private let onStoreReplaced: @Sendable (LearnerStore) async -> Void
    private let configuration: Configuration
    private let clock: any LearningCore.Clock
    private let logger: any CoreLogger

    private var engine: (any SyncEngine)?
    private var startingEngine = false
    private var started = false
    private var additions: Task<Void, Never>?

    /// Fetched event records waiting for one `insertRemote(records:)` call, and the engine's newest state
    /// serialization, held back until they are stored (so a crash never skips past events it didn't store).
    private var fetchedEvents: [SyncRecord] = []
    private var heldState: Data?
    /// A fetched batch couldn't be stored: keep the last saved state, so the next launch fetches it again.
    private var stateFrozen = false

    private enum ResetPhase: Equatable {
        case none, deletingZone
        case recreatingZone(saved: Bool)
    }
    private var resetPhase = ResetPhase.none

    // What the status line is computed from.
    private var account = SyncAccountStatus.unknown
    private var pausedInSettings = false
    /// The signed-in user the learner hasn't switched to yet (the alert is up).
    private var pendingSwitch: String?
    private var declinedSwitch = false
    private var problem: SyncPauseReason?
    private var fetching = false
    private var sending = false
    private var networkAvailable = true
    private var networkProblem = false
    private var lastSyncedAt: Int64?
    private var platforms: [Platform]
    private var notice: SyncNotice?

    private var observers: [Int: AsyncStream<SyncSnapshot>.Continuation] = [:]
    private var nextObserver = 0
    private var published: SyncSnapshot?

    init(
        store: LearnerStore, factory: any SyncEngineFactory, configuration: Configuration,
        clock: any LearningCore.Clock, logger: any CoreLogger = NoOpLogger(),
        openStore: @escaping StoreOpener,
        onStoreReplaced: @escaping @Sendable (LearnerStore) async -> Void = { _ in }
    ) {
        self.store = store
        self.factory = factory
        self.configuration = configuration
        self.clock = clock
        self.logger = logger
        self.openStore = openStore
        self.onStoreReplaced = onStoreReplaced
        self.platforms = [configuration.platform]
    }

    // MARK: SyncControlling

    func snapshots() -> AsyncStream<SyncSnapshot> {
        let (stream, continuation) = AsyncStream.makeStream(
            of: SyncSnapshot.self, bufferingPolicy: .bufferingNewest(1))
        let id = nextObserver
        nextObserver += 1
        observers[id] = continuation
        continuation.yield(snapshot)
        continuation.onTermination = { [weak self] _ in Task { await self?.removeObserver(id) } }
        return stream
    }

    /// Startup (docs/08): unless paused, check that the signed-in account is the one this database belongs to,
    /// then create the engine from the saved state, adding `.saveZone(Learner)` on the first run and every
    /// `sync_pending` row the engine doesn't list.
    func start() async {
        guard !started else { return }
        started = true
        pausedInSettings = store.settings.syncPaused
        await refreshPlatforms()
        if !pausedInSettings { await startEngineIfTheAccountMatches() }
        publish()
    }

    func syncNow() async {
        guard let engine else { return }
        do {
            try await engine.fetchChanges()
            try await engine.sendChanges()
        } catch {
            note(error.kind, code: error.code, while: "sync")
        }
        publish()
    }

    /// Pause: persist the state serialization, then release the engine; new events keep collecting in
    /// `sync_pending`. Unpause: create the engine again from the saved state (docs/08 § Pause sync).
    func setPaused(_ paused: Bool) async {
        await attempt("store sync.paused") { try await store.set(.syncPaused, to: .bool(paused)) }
        pausedInSettings = paused
        if paused {
            await stopEngine()
        } else {
            declinedSwitch = false
            if started { await startEngineIfTheAccountMatches() }
        }
        publish()
    }

    /// The account-switch alert (docs/08 § `.accountChange`). Confirm: move `learner.sqlite` aside as
    /// `learner-<date>.archive.sqlite`, open a fresh database bound to the new account, and sync it from scratch
    /// (the engine fetches the account's data). Cancel: pause sync (`sync.paused`), keeping this device's progress.
    func resolveAccountSwitch(confirm: Bool) async {
        guard let user = pendingSwitch else { return }
        pendingSwitch = nil
        guard confirm else {
            declinedSwitch = true
            await attempt("store sync.paused") { try await store.set(.syncPaused, to: .bool(true)) }
            pausedInSettings = true
            publish()
            return
        }
        // The account may have changed again while the alert was up (back to this database's, or to a third one):
        // then nothing is archived, and the usual check starts the engine or asks about the new account.
        if case .available(let current) = await factory.accountStatus(), current != user {
            await startEngineIfTheAccountMatches()
            publish()
            return
        }
        await stopEngine()
        let old = store
        do {
            try old.close()
        } catch {
            logger.log("sync: can't close the learner database for the archive: \(error)")
            pendingSwitch = user
            publish()
            return
        }
        var archived = true
        do {
            let archive = try LearnerStore.moveAside(old.url, as: .archive, clock: clock)
            logger.log("sync: archived this device's progress as \(archive.lastPathComponent)")
        } catch {
            logger.log("sync: archiving failed, reopening the database as it is: \(error)")
            archived = false
        }
        do {
            store = try await openStore(old.url)
        } catch {
            logger.log("sync: can't open a learner database after the archive: \(error)")
            problem = .error
            publish()
            return
        }
        guard archived else {
            // The same progress, reopened: never bind it to the other account. The alert asks again.
            pendingSwitch = user
            await onStoreReplaced(store)
            publish()
            return
        }
        fetchedEvents = []
        heldState = nil
        stateFrozen = false
        resetPhase = .none
        problem = nil
        notice = nil
        lastSyncedAt = nil
        declinedSwitch = false
        pausedInSettings = store.settings.syncPaused
        await attempt("bind the account") { try await store.setSyncAccount(user) }
        await onStoreReplaced(store)
        await refreshPlatforms()
        if !pausedInSettings { await startEngine() }
        publish()
    }

    func dismissNotice() async {
        notice = nil
        publish()
    }

    /// Reset progress (Debug menu): this device's progress goes, then the zone is deleted and recreated, which
    /// resets every other device when it fetches (docs/08 § Reset progress). While paused it resets only this
    /// device.
    func resetProgress() async {
        await attempt("erase progress") { try await store.eraseProgress() }
        fetchedEvents = []
        await refreshPlatforms()
        if let engine {
            resetPhase = .deletingZone
            engine.removePendingSaves(engine.pendingSaves)
            engine.addPendingZoneDelete()
        }
        publish()
    }

    // MARK: From the platform

    /// The network path changed (`NWPathMonitor` in `CloudSync`).
    func networkChanged(available: Bool) {
        networkAvailable = available
        if available { networkProblem = false }
        publish()
    }

    /// One engine event (`CKSyncEngineDelegate.handleEvent`). Events of an engine that was discarded are ignored.
    func handle(_ event: SyncEngineEvent, from source: any SyncEngine) async {
        guard let engine, source === engine else { return }
        switch event {
        case .stateUpdate(let data):
            await saveState(data)
        case .accountChange(let change):
            await accountChanged(change, engine: engine)
        case .fetchedDatabaseChanges(let deletions):
            for reason in deletions { await zoneDeleted(reason, engine: engine) }
        case .fetchedRecordZoneChanges(let modified, let deleted):
            await fetched(modified, deletedRecordNames: deleted, engine: engine)
        case .sentDatabaseChanges(let savedZone, let deletedZone, let failure):
            await sentDatabaseChanges(savedZone: savedZone, deletedZone: deletedZone, failure: failure, engine: engine)
        case .sentRecordZoneChanges(let saved, let failed):
            await sent(saved: saved, failed: failed, engine: engine)
        case .willFetchChanges:
            fetching = true
        case .didFetchRecordZoneChanges:
            await storeFetchedEvents()
        case .didFetchChanges:
            await storeFetchedEvents()
            fetching = false
            if resetPhase == .recreatingZone(saved: true) { resetPhase = .none }
            markSynced()
        case .willSendChanges:
            sending = true
        case .didSendChanges:
            sending = false
            markSynced()
        }
        publish()
    }

    /// The records for the next upload batch (`nextRecordZoneChangeBatch`'s record provider). A pending record
    /// whose row is gone (or a device-scoped setting) is dropped from the engine and from `sync_pending`.
    func recordsToSend(_ recordNames: [String], from source: any SyncEngine) async -> [OutgoingRecord] {
        guard let engine, source === engine else { return [] }
        var records: [OutgoingRecord] = []
        var gone: [String] = []
        for name in recordNames {
            let record: SyncRecord?
            do {
                record = try await store.syncRecord(named: name)
            } catch {
                logger.log("sync: can't load \(name) for upload: \(error)")
                continue  // stays pending
            }
            guard let record else {
                gone.append(name)
                continue
            }
            var systemFields: Data?
            if record.recordType == .setting {
                systemFields =
                    await attempt("load system fields") { try await store.systemFields(recordName: name) }
                    ?? nil
            }
            records.append(OutgoingRecord(record: record, systemFields: systemFields))
        }
        if !gone.isEmpty {
            engine.removePendingSaves(gone)
            await attempt("drop pending changes") { try await store.removePending(recordNames: gone) }
        }
        return records
    }

    // MARK: Engine lifecycle

    private func startEngineIfTheAccountMatches() async {
        account = await factory.accountStatus()
        if case .available(let user) = account {
            let bound = await attempt("read the account") { try await store.syncAccount() } ?? nil
            if let bound, bound != user {
                pendingSwitch = user
                return
            }
            if bound == nil { await attempt("bind the account") { try await store.setSyncAccount(user) } }
        }
        await startEngine()
    }

    private func startEngine() async {
        // Actor reentrancy: a second start during `makeEngine` would orphan an engine that keeps syncing.
        guard engine == nil, !startingEngine else { return }
        startingEngine = true
        defer { startingEngine = false }
        let saved = await attempt("load the engine state") { try await store.syncEngineState() } ?? nil
        let engine = await factory.makeEngine(stateSerialization: saved, driver: self)
        self.engine = engine
        stateFrozen = false
        if saved == nil { engine.addPendingZoneSave() }
        // Subscribe before reading `sync_pending`, so a commit in between is in one or the other.
        let stream = store.pendingAdditions()
        await reconcile(engine)
        additions = Task { [weak self] in
            for await names in stream { await self?.addToEngine(names) }
        }
    }

    /// Crash safety (docs/08): every `sync_pending` row the engine doesn't list goes back to it.
    private func reconcile(_ engine: any SyncEngine) async {
        guard let pending = await attempt("read pending changes", { try await store.pendingChanges() }) else {
            return
        }
        let listed = Set(engine.pendingSaves)
        let missing = pending.map(\.recordName).filter { !listed.contains($0) }
        if !missing.isEmpty { engine.addPendingSaves(missing) }
    }

    private func addToEngine(_ names: [String]) { engine?.addPendingSaves(names) }

    /// Releases the engine after storing what was fetched (pause, account switch). Never from a handler.
    private func stopEngine() async {
        guard let engine else { return }
        await storeFetchedEvents()
        detach()
        await factory.discard(engine)
    }

    /// Releases the engine from inside one of its handlers: the discard runs afterwards, and whatever it fetched
    /// for the account being left is dropped.
    private func releaseEngineFromHandler() {
        guard let engine else { return }
        fetchedEvents = []
        heldState = nil
        detach()
        let factory = factory
        Task { await factory.discard(engine) }
    }

    private func detach() {
        engine = nil
        additions?.cancel()
        additions = nil
        fetching = false
        sending = false
    }

    // MARK: Handlers

    private func saveState(_ data: Data) async {
        guard !stateFrozen else { return }
        if !fetchedEvents.isEmpty {
            heldState = data
            return
        }
        await attempt("save the engine state") { try await store.saveSyncEngineState(data) }
    }

    /// `.accountChange` (docs/08): a sign-in to this database's account (or the first one) uploads everything;
    /// any other account is an account switch, even with a sign-out in between; a sign-out keeps everything local.
    private func accountChanged(_ change: SyncAccountChange, engine: any SyncEngine) async {
        switch change {
        case .signIn(let user), .switchAccounts(_, let user):
            account = .available(userID: user)
            let bound = await attempt("read the account") { try await store.syncAccount() } ?? nil
            if let bound, bound != user {
                pendingSwitch = user
                releaseEngineFromHandler()
                return
            }
            if bound == nil { await attempt("bind the account") { try await store.setSyncAccount(user) } }
            await attempt("mark everything pending") { try await store.markEverythingPending() }
            await reconcile(engine)
        case .signOut:
            account = .noAccount
        }
    }

    /// `.fetchedDatabaseChanges` with the `Learner` zone deleted (docs/08).
    private func zoneDeleted(_ reason: ZoneDeletionReason, engine: any SyncEngine) async {
        switch reason {
        case .deleted, .purged:
            guard resetPhase == .none else { return }  // this device's own Reset
            fetchedEvents = []
            await attempt("erase progress") { try await store.eraseProgress() }
            engine.removePendingSaves(engine.pendingSaves)
            engine.addPendingZoneSave()
            notice = .progressResetElsewhere
            await refreshPlatforms()
        case .encryptedDataReset:
            await attempt("forget system fields") { try await store.removeAllSystemFields() }
            engine.addPendingZoneSave()
            await attempt("mark everything pending") { try await store.markEverythingPending() }
            await reconcile(engine)
        }
    }

    /// `.fetchedRecordZoneChanges`: events wait for one insert at the end of the fetch; settings merge now.
    private func fetched(_ modified: [ServerRecord], deletedRecordNames: [String], engine: any SyncEngine) async {
        var again: [String] = []
        for server in modified {
            switch server.record.recordType {
            case .event:
                fetchedEvents.append(server.record)
            case .setting:
                // The server's value merges by last-writer-wins; a local value that beats it goes up again, so the
                // server converges on the winner too.
                if await mergeSetting(server) == .localWins { again.append(server.record.recordName) }
            }
        }
        if !deletedRecordNames.isEmpty {
            logger.log("sync: ignored \(deletedRecordNames.count) record deletions (only Reset deletes, by zone)")
        }
        await markPending(again, engine: engine)
        if fetchedEvents.count >= configuration.insertBatchLimit { await storeFetchedEvents() }
    }

    /// Inserts the fetched events with one `insertRemote(records:)` call, then saves the state held back for them.
    private func storeFetchedEvents() async {
        guard !fetchedEvents.isEmpty else { return }
        let records = fetchedEvents
        fetchedEvents = []
        let result = await attempt("insert fetched events") { try await store.insertRemote(records: records) }
        guard let result else {
            stateFrozen = true
            heldState = nil
            return
        }
        if let held = heldState {
            heldState = nil
            await attempt("save the engine state") { try await store.saveSyncEngineState(held) }
        }
        if !result.inserted.isEmpty { await refreshPlatforms() }
    }

    private enum MergeOutcome { case serverWins, localWins, failed }

    /// Caches a server setting's system fields and merges it into the store by last-writer-wins. `localWins` when
    /// this device holds a synced value that beats it (or the server's record is unreadable): that value should go
    /// up. `failed` when the store couldn't merge (it stays as it is; the next fetch merges again).
    private func mergeSetting(_ server: ServerRecord) async -> MergeOutcome {
        let name = server.record.recordName
        await attempt("save system fields") { try await store.saveSystemFields(server.systemFields, recordName: name) }
        let remote = try? RecordMapping.setting(from: server.record)
        if let remote {
            guard await attempt("merge a setting", { try await store.applyRemote(remote) }) != nil else {
                return .failed
            }
        } else {
            logger.log("sync: an unreadable Setting record \(name); this device's value replaces it")
        }
        guard let key = RecordMapping.settingKey(fromRecordName: name), SettingKey.scope(of: key) == .synced,
            let local = await attempt("read a setting", { try await store.settingRecord(key) }) ?? nil
        else { return .serverWins }
        guard let remote else { return .localWins }
        return MergeRules.wins(local, over: remote) ? .localWins : .serverWins
    }

    /// `.sentRecordZoneChanges` (docs/08).
    private func sent(saved: [ServerRecord], failed: [FailedSave], engine: any SyncEngine) async {
        var done: [String] = []
        var again: [String] = []  // pending again, in the store and the engine
        var retry: [String] = []  // still pending in the store; back to the engine in case it dropped them
        var permanent = false
        for server in saved {
            let name = server.record.recordName
            guard server.record.recordType == .setting else {
                done.append(name)
                continue
            }
            await attempt("save system fields") {
                try await store.saveSystemFields(server.systemFields, recordName: name)
            }
            // A value changed while this upload was in flight stays pending.
            if await isCurrent(server.record) { done.append(name) } else { again.append(name) }
        }
        var zoneMissing = false
        for failure in failed {
            let name = failure.recordName
            switch failure.error {
            case .serverRecordChanged:
                if RecordMapping.recordType(forRecordName: name) == .event {
                    done.append(name)  // the same immutable event is already there
                } else if let server = failure.serverRecord {
                    // Last-writer-wins; the save goes again only if the local value wins.
                    switch await mergeSetting(server) {
                    case .localWins: again.append(name)
                    case .serverWins: done.append(name)
                    case .failed: break  // stays in `sync_pending`; the next start sends it with fresh fields
                    }
                } else {
                    again.append(name)
                }
            case .zoneNotFound:
                zoneMissing = true
                await attempt("forget system fields") { try await store.removeSystemFields(recordNames: [name]) }
                again.append(name)
            case .unknownItem:
                await attempt("forget system fields") { try await store.removeSystemFields(recordNames: [name]) }
                again.append(name)
            case .network:
                networkProblem = true
                retry.append(name)
            case .transient, .accountUnavailable:
                retry.append(name)
            case .quotaExceeded:
                // Stays in `sync_pending` and goes back to the engine at the next start.
                problem = .storageFull
                permanent = true
            case .other:
                logger.log("sync: iCloud refused \(name)")
                problem = .error
                permanent = true
            }
        }
        if zoneMissing { engine.addPendingZoneSave() }
        if !done.isEmpty {
            await attempt("remove pending changes") { try await store.removePending(recordNames: done) }
        }
        await markPending(again, engine: engine)
        if !retry.isEmpty { engine.addPendingSaves(retry) }
        if !saved.isEmpty {
            networkProblem = false
            if !permanent { problem = nil }
        }
    }

    private func sentDatabaseChanges(
        savedZone: Bool, deletedZone: Bool, failure: SyncErrorKind?, engine: any SyncEngine
    ) async {
        if deletedZone, resetPhase == .deletingZone {
            resetPhase = .recreatingZone(saved: false)
            engine.addPendingZoneSave()
            await reconcile(engine)
        }
        if savedZone, resetPhase == .recreatingZone(saved: false) { resetPhase = .recreatingZone(saved: true) }
        if let failure { note(failure, code: 0, while: "a zone change") }
    }

    // MARK: Helpers

    private func markPending(_ names: [String], engine: any SyncEngine) async {
        guard !names.isEmpty else { return }
        await attempt("mark pending") { try await store.addPending(recordNames: names) }
        engine.addPendingSaves(names)
    }

    /// Whether a saved setting record still holds the stored value.
    private func isCurrent(_ saved: SyncRecord) async -> Bool {
        guard let current = await attempt("read a record", { try await store.syncRecord(named: saved.recordName) })
        else { return false }
        guard let current else { return true }  // gone, or device-scoped: nothing left to send
        return current.fields == saved.fields
    }

    private func note(_ kind: SyncErrorKind, code: Int, while operation: String) {
        switch kind {
        case .network: networkProblem = true
        case .quotaExceeded: problem = .storageFull
        case .other: problem = .error
        case .serverRecordChanged, .zoneNotFound, .unknownItem, .transient, .accountUnavailable: break
        }
        logger.log("sync: \(operation) failed: \(kind) (\(code))")
    }

    private func markSynced() {
        guard networkAvailable, !fetching, !sending else { return }
        networkProblem = false
        lastSyncedAt = clock.nowMs()
    }

    private func refreshPlatforms() async {
        let seen = await attempt("read device platforms") { try await store.devicePlatforms() } ?? [:]
        let present = Set(seen.values).union([configuration.platform])
        platforms = SyncStatusText.platformOrder.filter(present.contains)
    }

    @discardableResult
    private func attempt<T: Sendable>(_ what: String, _ body: () async throws -> T) async -> T? {
        do {
            return try await body()
        } catch {
            logger.log("sync: \(what) failed: \(error)")
            return nil
        }
    }

    // MARK: Status

    private var status: SyncStatus {
        if pendingSwitch != nil || (declinedSwitch && pausedInSettings) { return .paused(.otherAccount) }
        if pausedInSettings { return .paused(.inSettings) }
        if account.isOff { return .iCloudOff }
        if let problem { return .paused(problem) }
        if !networkAvailable || networkProblem { return .waitingForNetwork }
        if fetching || sending { return .syncing }
        if let lastSyncedAt { return .synced(atMs: lastSyncedAt) }
        return .syncing
    }

    private var snapshot: SyncSnapshot {
        SyncSnapshot(
            status: status, platforms: platforms, pausedInSettings: pausedInSettings,
            accountSwitchPending: pendingSwitch != nil, notice: notice)
    }

    private func publish() {
        let snapshot = snapshot
        guard snapshot != published else { return }
        published = snapshot
        for continuation in observers.values { continuation.yield(snapshot) }
    }

    private func removeObserver(_ id: Int) { observers[id] = nil }
}

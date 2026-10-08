#if canImport(CloudKit)
    import CloudKit
    import Foundation
    import LearningCore
    import Network
    import Storage
    import os

    #if os(macOS)
        import AppKit
    #else
        import UIKit
    #endif

    // The CKSyncEngine adapter (docs/08 § The sync engine; task M7.2). It maps CloudKit's types onto `SyncEngine` and
    // `SyncEngineEvent` and nothing else: every decision is `SyncDriver`'s, which the App tests run against a fake
    // engine on any platform. Private database, one zone (`Learner`), record types `Event` and `Setting`
    // (`RecordMapping`, field by field).
    //
    // ⚠️ UNEXERCISED: written against the iOS/macOS 26 SDK documentation and Apple's CKSyncEngine sample, and
    // only syntax-checked (`swiftc -parse`) on Linux. The owner's first signed build (M7.2 [owner], then M7.5)
    // type-checks it, exchanges events between two devices, and records every difference in PROGRESS.md.

    private let syncLog = Logger(subsystem: "com.j23n.italian", category: "sync")

    /// `SyncDriver`'s log: record names, setting keys, error kinds and file names, never learner text.
    struct SyncLogger: CoreLogger {
        func log(_ message: String) { syncLog.notice("\(message, privacy: .private)") }
    }

    /// The real `SyncEngineFactory` and `CKSyncEngineDelegate`. Create it only when `AppConfig.syncAllowed`:
    /// `CKContainer(identifier:)` crashes without the iCloud entitlement (docs/02).
    actor CloudSync: CKSyncEngineDelegate, SyncEngineFactory {
        static let containerIdentifier = "iCloud.com.j23n.italian"  // ADR-18: never change
        /// CloudKit's limit per modify operation; the batch initialiser trims the batch further to the size limit.
        static let batchLimit = 400

        private let container: CKContainer
        private weak var driver: SyncDriver?
        private var current: CloudKitEngine?
        private let pathMonitor = NWPathMonitor()
        private var monitoring = false

        init(container: CKContainer = CKContainer(identifier: CloudSync.containerIdentifier)) {
            self.container = container
        }

        // MARK: SyncEngineFactory

        func accountStatus() async -> SyncAccountStatus {
            do {
                switch try await container.accountStatus() {
                case .available: return .available(userID: try await container.userRecordID().recordName)
                case .noAccount: return .noAccount
                case .restricted: return .restricted
                case .temporarilyUnavailable: return .temporarilyUnavailable
                case .couldNotDetermine: return .unknown
                @unknown default: return .unknown
                }
            } catch {
                syncLog.error("account status: \(String(describing: error), privacy: .public)")
                return .unknown
            }
        }

        func makeEngine(stateSerialization: Data?, driver: SyncDriver) async -> any SyncEngine {
            self.driver = driver
            let saved = stateSerialization.flatMap {
                try? JSONDecoder().decode(CKSyncEngine.State.Serialization.self, from: $0)
            }
            var configuration = CKSyncEngine.Configuration(
                database: container.privateCloudDatabase, stateSerialization: saved, delegate: self)
            configuration.automaticallySync = true
            let engine = CloudKitEngine(CKSyncEngine(configuration))
            current = engine
            startMonitoringNetwork()
            return engine
        }

        func discard(_ engine: any SyncEngine) async {
            guard let engine = engine as? CloudKitEngine else { return }
            if current === engine { current = nil }
            await engine.engine.cancelOperations()
        }

        // MARK: CKSyncEngineDelegate

        func handleEvent(_ event: CKSyncEngine.Event, syncEngine: CKSyncEngine) async {
            guard let driver, let engine = current, engine.engine === syncEngine,
                let neutral = CloudKitMapping.event(event)
            else { return }
            await driver.handle(neutral, from: engine)
        }

        /// Pending saves in scope, at most `batchLimit` at a time, built from the driver's records (docs/08
        /// § `nextRecordZoneChangeBatch`). The records are loaded first, so the provider closure is synchronous.
        func nextRecordZoneChangeBatch(
            _ context: CKSyncEngine.SendChangesContext, syncEngine: CKSyncEngine
        ) async -> CKSyncEngine.RecordZoneChangeBatch? {
            guard let driver, let engine = current, engine.engine === syncEngine else { return nil }
            let scope = context.options.scope
            let saves: [CKRecord.ID] = syncEngine.state.pendingRecordZoneChanges.filter { scope.contains($0) }
                .compactMap { change in
                    guard case .saveRecord(let id) = change, id.zoneID.zoneName == RecordMapping.zoneName else {
                        return nil
                    }
                    return id
                }
            var start = 0
            while start < saves.count {
                let slice = Array(saves[start..<min(start + Self.batchLimit, saves.count)])
                start += slice.count
                let outgoing = await driver.recordsToSend(slice.map(\.recordName), from: engine)
                guard !outgoing.isEmpty else { continue }  // every row of this slice was gone
                let byName = Dictionary(
                    outgoing.map { ($0.record.recordName, $0) }, uniquingKeysWith: { first, _ in first })
                let pending = slice.filter { byName[$0.recordName] != nil }
                    .map { CKSyncEngine.PendingRecordZoneChange.saveRecord($0) }
                return await CKSyncEngine.RecordZoneChangeBatch(pendingChanges: pending) { recordID in
                    byName[recordID.recordName].map { CloudKitMapping.record($0, id: recordID) }
                }
            }
            return nil
        }

        // MARK: Network

        private func startMonitoringNetwork() {
            guard !monitoring else { return }
            monitoring = true
            pathMonitor.pathUpdateHandler = { [weak self] path in
                let available = path.status == .satisfied
                Task { await self?.networkChanged(available) }
            }
            pathMonitor.start(queue: DispatchQueue(label: "com.j23n.italian.sync.network"))
        }

        private func networkChanged(_ available: Bool) async { await driver?.networkChanged(available: available) }
    }

    /// `SyncEngine` over one CKSyncEngine: record names are record IDs in the `Learner` zone.
    final class CloudKitEngine: SyncEngine {
        let engine: CKSyncEngine

        init(_ engine: CKSyncEngine) { self.engine = engine }

        var pendingSaves: [String] {
            engine.state.pendingRecordZoneChanges.compactMap { change in
                guard case .saveRecord(let id) = change, id.zoneID.zoneName == RecordMapping.zoneName else {
                    return nil
                }
                return id.recordName
            }
        }

        func addPendingSaves(_ recordNames: [String]) {
            guard !recordNames.isEmpty else { return }
            engine.state.add(pendingRecordZoneChanges: recordNames.map { .saveRecord(CloudKitMapping.recordID($0)) })
        }

        func removePendingSaves(_ recordNames: [String]) {
            guard !recordNames.isEmpty else { return }
            engine.state.remove(pendingRecordZoneChanges: recordNames.map { .saveRecord(CloudKitMapping.recordID($0)) })
        }

        func addPendingZoneSave() {
            engine.state.add(pendingDatabaseChanges: [.saveZone(CKRecordZone(zoneID: CloudKitMapping.zoneID))])
        }

        func addPendingZoneDelete() {
            engine.state.add(pendingDatabaseChanges: [.deleteZone(CloudKitMapping.zoneID)])
        }

        func fetchChanges() async throws(SyncFailure) {
            do {
                try await engine.fetchChanges()
            } catch {
                throw CloudKitMapping.failure(error)
            }
        }

        func sendChanges() async throws(SyncFailure) {
            do {
                try await engine.sendChanges()
            } catch {
                throw CloudKitMapping.failure(error)
            }
        }
    }

    /// CloudKit ↔ the driver's types.
    enum CloudKitMapping {
        static var zoneID: CKRecordZone.ID {
            CKRecordZone.ID(zoneName: RecordMapping.zoneName, ownerName: CKCurrentUserDefaultName)
        }

        static func recordID(_ recordName: String) -> CKRecord.ID {
            CKRecord.ID(recordName: recordName, zoneID: zoneID)
        }

        static func isOurs(_ zone: CKRecordZone.ID) -> Bool { zone.zoneName == RecordMapping.zoneName }

        static func event(_ event: CKSyncEngine.Event) -> SyncEngineEvent? {
            switch event {
            case .stateUpdate(let update):
                guard let data = try? JSONEncoder().encode(update.stateSerialization) else { return nil }
                return .stateUpdate(data)
            case .accountChange(let change):
                switch change.changeType {
                case .signIn(let current): return .accountChange(.signIn(currentUser: current.recordName))
                case .signOut(let previous): return .accountChange(.signOut(previousUser: previous.recordName))
                case .switchAccounts(let previous, let current):
                    return .accountChange(
                        .switchAccounts(previousUser: previous.recordName, currentUser: current.recordName))
                @unknown default: return nil
                }
            case .fetchedDatabaseChanges(let changes):
                let ours = changes.deletions.filter { isOurs($0.zoneID) }
                guard !ours.isEmpty else { return nil }
                return .fetchedDatabaseChanges(zoneDeletions: ours.map { reason($0.reason) })
            case .fetchedRecordZoneChanges(let changes):
                let modified = changes.modifications.compactMap { serverRecord($0.record) }
                let deleted = changes.deletions.filter { isOurs($0.recordID.zoneID) }.map(\.recordID.recordName)
                return .fetchedRecordZoneChanges(modified: modified, deletedRecordNames: deleted)
            case .sentDatabaseChanges(let sent):
                let failure =
                    sent.failedZoneSaves.first { isOurs($0.zone.zoneID) }.map { kind($0.error) }
                    ?? sent.failedZoneDeletes.first { isOurs($0.key) }.map { kind($0.value) }
                return .sentDatabaseChanges(
                    savedZone: sent.savedZones.contains { isOurs($0.zoneID) },
                    deletedZone: sent.deletedZoneIDs.contains { isOurs($0) }, failedZoneChange: failure)
            case .sentRecordZoneChanges(let sent):
                let failed = sent.failedRecordSaves.filter { isOurs($0.record.recordID.zoneID) }.map { failure in
                    FailedSave(
                        recordName: failure.record.recordID.recordName, error: kind(failure.error),
                        serverRecord: failure.error.serverRecord.flatMap { serverRecord($0) })
                }
                return .sentRecordZoneChanges(saved: sent.savedRecords.compactMap { serverRecord($0) }, failed: failed)
            case .willFetchChanges: return .willFetchChanges
            case .didFetchRecordZoneChanges(let done): return isOurs(done.zoneID) ? .didFetchRecordZoneChanges : nil
            case .didFetchChanges: return .didFetchChanges
            case .willSendChanges: return .willSendChanges
            case .didSendChanges: return .didSendChanges
            case .willFetchRecordZoneChanges: return nil
            @unknown default: return nil
            }
        }

        static func reason(_ reason: CKDatabase.DatabaseChange.Deletion.Reason) -> ZoneDeletionReason {
            switch reason {
            case .deleted: .deleted
            case .purged: .purged
            case .encryptedDataReset: .encryptedDataReset
            @unknown default: .deleted
            }
        }

        /// docs/08 § `.sentRecordZoneChanges`.
        static func kind(_ error: CKError) -> SyncErrorKind {
            switch error.code {
            case .serverRecordChanged: .serverRecordChanged
            case .zoneNotFound: .zoneNotFound
            case .unknownItem: .unknownItem
            case .networkFailure, .networkUnavailable: .network
            // `.userDeletedZone`: the learner deleted the app's iCloud data; the next fetch reports the purge, whose
            // handler erases and recreates the zone.
            case .zoneBusy, .serviceUnavailable, .requestRateLimited, .operationCancelled, .batchRequestFailed,
                .serverResponseLost, .userDeletedZone:
                .transient
            case .notAuthenticated, .accountTemporarilyUnavailable: .accountUnavailable
            case .quotaExceeded: .quotaExceeded
            default: .other
            }
        }

        static func failure(_ error: any Error) -> SyncFailure {
            guard let error = error as? CKError else { return SyncFailure(.other) }
            return SyncFailure(kind(error), code: error.code.rawValue)
        }

        // MARK: Records

        /// A record of the `Learner` zone as the driver sees it; nil for another zone or record type.
        static func serverRecord(_ record: CKRecord) -> ServerRecord? {
            guard isOurs(record.recordID.zoneID), let type = SyncRecordType(rawValue: record.recordType) else {
                return nil
            }
            var fields: [String: RecordFieldValue] = [:]
            for key in record.allKeys() {
                guard let value = record[key] else { continue }
                if let text = value as? String {
                    fields[key] = .string(text)
                } else if let data = value as? Data {
                    fields[key] = .bytes(data)
                } else if let number = value as? NSNumber {
                    fields[key] = .int64(number.int64Value)
                }
            }
            let synced = SyncRecord(recordType: type, recordName: record.recordID.recordName, fields: fields)
            return ServerRecord(record: synced, systemFields: systemFields(of: record))
        }

        /// The CKRecord to save: from the cached system fields when there are some (so the change tag matches), else
        /// new; then every field of `RecordMapping`.
        static func record(_ outgoing: OutgoingRecord, id: CKRecord.ID) -> CKRecord {
            let cached = outgoing.systemFields.flatMap(decodeSystemFields).flatMap { $0.recordID == id ? $0 : nil }
            let record = cached ?? CKRecord(recordType: outgoing.record.recordType.rawValue, recordID: id)
            for (key, value) in outgoing.record.fields {
                switch value {
                case .string(let text): record[key] = text as NSString
                case .int64(let number): record[key] = NSNumber(value: number)
                case .bytes(let data): record[key] = data as NSData
                }
            }
            return record
        }

        static func systemFields(of record: CKRecord) -> Data {
            let coder = NSKeyedArchiver(requiringSecureCoding: true)
            record.encodeSystemFields(with: coder)
            coder.finishEncoding()
            return coder.encodedData
        }

        static func decodeSystemFields(_ data: Data) -> CKRecord? {
            guard let coder = try? NSKeyedUnarchiver(forReadingFrom: data) else { return nil }
            coder.requiresSecureCoding = true
            defer { coder.finishDecoding() }
            return CKRecord(coder: coder)
        }
    }

    /// How the App container (task M3.3) sets sync up: `CloudSync` when the build allows it, `DisabledSync` otherwise.
    /// The container also calls `syncNow()` when the scene goes to the background and after a lesson step completes,
    /// and replaces its `LearnerStore` when `onStoreReplaced` reports the fresh database of an account switch.
    enum SyncSetup {
        static func controller(
            config: AppConfig, store: LearnerStore, platform: Platform, clock: any LearningCore.Clock,
            openStore: @escaping SyncDriver.StoreOpener,
            onStoreReplaced: @escaping @Sendable (LearnerStore) async -> Void
        ) -> any SyncControlling {
            guard config.syncAllowed else { return DisabledSync() }
            return SyncDriver(
                store: store, factory: CloudSync(), configuration: .init(platform: platform), clock: clock,
                logger: SyncLogger(), openStore: openStore, onStoreReplaced: onStoreReplaced)
        }

        /// This device's family (the status line and `session` events).
        @MainActor static var currentPlatform: Platform {
            #if os(macOS)
                return .Mac
            #else
                return UIDevice.current.userInterfaceIdiom == .pad ? .iPad : .iPhone
            #endif
        }

        /// CKSyncEngine fetches when CloudKit pushes a change (Remote notifications background mode,
        /// `aps-environment`): register at launch in signed builds with sync.
        @MainActor static func registerForPushes() {
            #if os(macOS)
                NSApplication.shared.registerForRemoteNotifications()
            #else
                UIApplication.shared.registerForRemoteNotifications()
            #endif
        }
    }
#endif

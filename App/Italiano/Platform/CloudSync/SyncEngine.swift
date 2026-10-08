import Foundation
import LearningCore

// The sync engine as `SyncDriver` sees it (docs/08 § The sync engine): CKSyncEngine's events, pending changes and
// errors without CloudKit, so the driver compiles and is tested on any platform. `CloudSync` maps CKSyncEngine
// onto these types (Apple only); the App tests run a fake engine over an in-memory private database.

/// The iCloud account, as `CKContainer.accountStatus()` and `userRecordID()` report it.
enum SyncAccountStatus: Sendable, Equatable {
    /// Signed in; `userID` is the CloudKit user record name (opaque, stable per account and container).
    case available(userID: String)
    case noAccount
    /// Parental controls or device management don't allow iCloud.
    case restricted
    /// Signed in, but the account needs attention (a password, new terms) before it can be used.
    case temporarilyUnavailable
    /// CloudKit couldn't tell (offline at launch, for instance).
    case unknown

    /// The status line says "iCloud is off — progress stays on this device".
    var isOff: Bool {
        switch self {
        case .noAccount, .restricted, .temporarilyUnavailable: true
        case .available, .unknown: false
        }
    }
}

/// `CKSyncEngine.Event.AccountChange.ChangeType`, with user record names.
enum SyncAccountChange: Sendable, Equatable {
    case signIn(currentUser: String)
    case signOut(previousUser: String)
    case switchAccounts(previousUser: String, currentUser: String)
}

/// Why the `Learner` zone was deleted (`CKDatabase.DatabaseChange.Deletion.Reason`).
enum ZoneDeletionReason: Sendable, Equatable {
    /// Reset progress on another device (docs/08 § Reset progress).
    case deleted
    /// The learner deleted the app's data in iCloud settings.
    case purged
    /// The account's encrypted data was reset: the server lost everything this device has.
    case encryptedDataReset
}

/// A CloudKit error as the driver needs it (`CKError.Code`; docs/08 § `.sentRecordZoneChanges`).
enum SyncErrorKind: Sendable, Equatable {
    case serverRecordChanged
    case zoneNotFound
    case unknownItem
    /// No network, or it failed. CKSyncEngine retries; the status line says "Waiting for network".
    case network
    /// Busy, rate-limited, cancelled, a lost response, a zone the learner just deleted: CKSyncEngine retries.
    case transient
    /// Not signed in, or the account can't be used right now (the engine reports the account change).
    case accountUnavailable
    case quotaExceeded
    /// Anything else (a refused record, a permission, a limit): logged, and the status line says "Sync paused".
    case other
}

/// A failed fetch or send (thrown by `SyncEngine`).
struct SyncFailure: Error, Sendable, Equatable {
    var kind: SyncErrorKind
    /// The `CKError.Code` raw value, for the log.
    var code: Int

    init(_ kind: SyncErrorKind, code: Int = 0) {
        self.kind = kind
        self.code = code
    }
}

/// A record as the server holds it: LearningCore's record and its system fields (`encodeSystemFields(with:)`,
/// opaque bytes).
struct ServerRecord: Sendable, Equatable {
    var record: SyncRecord
    var systemFields: Data
}

/// A record to upload, with the cached system fields of the server's copy. Only settings carry them: an event is
/// always saved as a new record, and the server answers `.serverRecordChanged` when it already has that ID.
struct OutgoingRecord: Sendable, Equatable {
    var record: SyncRecord
    var systemFields: Data?
}

/// One failed save of `.sentRecordZoneChanges`.
struct FailedSave: Sendable, Equatable {
    var recordName: String
    var error: SyncErrorKind
    /// The server's copy, for `.serverRecordChanged` (`CKError.serverRecord`).
    var serverRecord: ServerRecord?

    init(recordName: String, error: SyncErrorKind, serverRecord: ServerRecord? = nil) {
        self.recordName = recordName
        self.error = error
        self.serverRecord = serverRecord
    }
}

/// `CKSyncEngine.Event`, reduced to what docs/08 acts on. Only the `Learner` zone's changes are passed on.
enum SyncEngineEvent: Sendable, Equatable {
    /// The engine's state serialization (`CKSyncEngine.State.Serialization`, encoded): persist it.
    case stateUpdate(Data)
    case accountChange(SyncAccountChange)
    /// The `Learner` zone was deleted, once per deletion the fetch saw.
    case fetchedDatabaseChanges(zoneDeletions: [ZoneDeletionReason])
    /// Records created or changed on the server, and record deletions (never expected: Reset deletes the zone).
    case fetchedRecordZoneChanges(modified: [ServerRecord], deletedRecordNames: [String])
    case sentDatabaseChanges(savedZone: Bool, deletedZone: Bool, failedZoneChange: SyncErrorKind?)
    case sentRecordZoneChanges(saved: [ServerRecord], failed: [FailedSave])
    case willFetchChanges
    /// Every change of the `Learner` zone in this fetch has been delivered.
    case didFetchRecordZoneChanges
    case didFetchChanges
    case willSendChanges
    case didSendChanges
}

/// The sync engine (`CKSyncEngine`): its pending changes and its two operations. Record IDs are record names in the
/// `Learner` zone. The engine reports to the driver through `SyncDriver.handle(_:from:)` and asks it for the records
/// to send with `SyncDriver.recordsToSend(_:from:)`; never call `fetchChanges` or `sendChanges` from a handler.
protocol SyncEngine: AnyObject, Sendable {
    /// The record names of the pending `.saveRecord` changes, in order.
    var pendingSaves: [String] { get }
    /// Adds `.saveRecord` changes (one already pending stays as it is).
    func addPendingSaves(_ recordNames: [String])
    func removePendingSaves(_ recordNames: [String])
    /// `.saveZone(Learner)`.
    func addPendingZoneSave()
    /// `.deleteZone(Learner)`.
    func addPendingZoneDelete()
    func fetchChanges() async throws(SyncFailure)
    func sendChanges() async throws(SyncFailure)
}

/// Makes sync engines and reports the account: `CloudSync` in signed builds, a fake in the tests.
protocol SyncEngineFactory: AnyObject, Sendable {
    func accountStatus() async -> SyncAccountStatus
    /// A new engine starting from `stateSerialization` (nil: the first run, or a fresh database) that reports to
    /// `driver`.
    func makeEngine(stateSerialization: Data?, driver: SyncDriver) async -> any SyncEngine
    /// Stops an engine for good (pause, account switch): its operations are cancelled and it sends no more events.
    func discard(_ engine: any SyncEngine) async
}

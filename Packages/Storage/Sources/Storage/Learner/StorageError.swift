import Foundation
import GRDB

/// Everything that can go wrong in the learner database (docs/02 § Logging and errors).
///
/// `corrupt` is the one the App acts on (task M3.9): `LearnerStore.openRecovering` moves the file aside as a backup,
/// starts a fresh database, lets sync download the events again and rebuilds, and the App tells the learner in one
/// sentence. Everything else is a bug or an environment problem (a full disk) to log.
public enum StorageError: Error, Sendable, Equatable, CustomStringConvertible {
    /// The file isn't a usable learner database: SQLite reports it corrupt or not a database, or a migration failed.
    case corrupt(path: String, reason: String)
    /// The file or its folder can't be created, opened or moved (permissions, a missing volume, a full disk).
    case file(path: String, reason: String)
    /// A value can't be stored (a payload that doesn't encode as JSON) or a stored row can't be read back.
    case invalidValue(table: String, id: String, reason: String)
    /// Any other SQLite error.
    case database(String)

    public var description: String {
        switch self {
        case .corrupt(let path, let reason): "the learner database at \(path) is unusable: \(reason)"
        case .file(let path, let reason): "learner database file \(path): \(reason)"
        case .invalidValue(let table, let id, let reason): "\(table) \(id): \(reason)"
        case .database(let message): "learner database: \(message)"
        }
    }

    /// True for the errors that call for the learner-DB recovery (docs/02 § Logging and errors).
    public var isCorruption: Bool {
        if case .corrupt = self { return true }
        return false
    }

    /// Any error thrown inside a learner-database operation, as a `StorageError`. SQLite's "malformed" and "not a
    /// database" become `corrupt`, so a corruption found after launch leads to the same recovery.
    static func wrap(_ error: any Error, path: String) -> StorageError {
        switch error {
        case let e as StorageError: return e
        case let e as DatabaseError:
            switch e.resultCode {
            case .SQLITE_CORRUPT, .SQLITE_NOTADB: return .corrupt(path: path, reason: e.description)
            case .SQLITE_CANTOPEN, .SQLITE_PERM, .SQLITE_READONLY, .SQLITE_FULL, .SQLITE_IOERR:
                return .file(path: path, reason: e.description)
            default: return .database(e.description)
            }
        default: return .database(String(describing: error))
        }
    }
}

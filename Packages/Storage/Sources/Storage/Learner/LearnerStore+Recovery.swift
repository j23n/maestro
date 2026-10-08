import Foundation
import LearningCore

/// Why a learner database file is moved aside.
public enum LearnerDatabaseBackup: String, Sendable {
    /// It couldn't be opened or migrated (docs/02 § Logging and errors; task M3.9).
    case corrupt
    /// The iCloud account changed and the learner confirmed starting fresh (docs/08 § `.accountChange`).
    case archive
}

/// What `openRecovering` did when the database was unusable.
public struct LearnerStoreRecovery: Sendable, Equatable {
    /// Why the old file couldn't be used.
    public var error: StorageError
    /// Where the old file now is.
    public var backupURL: URL
}

/// The file-level primitives of learner-DB recovery and account archiving.
extension LearnerStore {
    /// `Italiano/learner.sqlite` in Application Support (docs/02 § Storage). The folder is created when missing.
    public static func defaultURL() throws(StorageError) -> URL {
        do {
            let support = try FileManager.default.url(
                for: .applicationSupportDirectory, in: .userDomainMask,
                appropriateFor: nil, create: true)
            return support.appendingPathComponent(directoryName, isDirectory: true)
                .appendingPathComponent(fileName)
        } catch {
            throw .file(path: "Application Support/\(directoryName)/\(fileName)", reason: "\(error)")
        }
    }

    /// Opens the store; when the file is unusable (`StorageError.corrupt`), moves it aside as a backup and opens a
    /// fresh database instead (docs/02 § Logging and errors). The fresh database starts with no events: sync
    /// downloads them again and they are replayed as they arrive. The App tells the learner in one sentence when
    /// `recovery` is set. Any other error (a full disk, a folder it can't write) is thrown.
    @concurrent
    public static func openRecovering(
        url: URL, content: ContentIndex, clock: any LearningCore.Clock,
        ids: any UUIDSource, options: Options = Options()
    ) async throws(StorageError)
        -> (store: LearnerStore, recovery: LearnerStoreRecovery?)
    {
        do {
            return (try LearnerStore(url: url, content: content, clock: clock, ids: ids, options: options), nil)
        } catch let error where error.isCorruption {
            let backup = try moveAside(url, as: .corrupt, clock: clock)
            StorageLog.recovered(error, backup: backup)
            let store = try LearnerStore(url: url, content: content, clock: clock, ids: ids, options: options)
            return (store, LearnerStoreRecovery(error: error, backupURL: backup))
        }
    }

    /// Moves a closed learner database, with its `-wal` and `-shm` files, to
    /// `learner-<UTC yyyy-MM-dd-HHmmss>.<kind>.sqlite` in the same folder (a suffix keeps names unique) and returns
    /// the new URL. Nothing to move is not an error: the returned URL then doesn't exist.
    public static func moveAside(
        _ url: URL, as kind: LearnerDatabaseBackup, clock: any LearningCore.Clock
    )
        throws(StorageError) -> URL
    {
        let fm = FileManager.default
        let folder = url.deletingLastPathComponent()
        let stem = "\(url.deletingPathExtension().lastPathComponent)-\(timestamp(ms: clock.nowMs()))"
        var backup = folder.appendingPathComponent("\(stem).\(kind.rawValue).sqlite")
        var n = 2
        while fm.fileExists(atPath: backup.path) {
            backup = folder.appendingPathComponent("\(stem)-\(n).\(kind.rawValue).sqlite")
            n += 1
        }
        for suffix in ["", "-wal", "-shm"] {
            let source = URL(fileURLWithPath: url.path + suffix)
            guard fm.fileExists(atPath: source.path) else { continue }
            do {
                try fm.moveItem(at: source, to: URL(fileURLWithPath: backup.path + suffix))
            } catch {
                throw .file(path: source.path, reason: "can't move it aside: \(error)")
            }
        }
        return backup
    }

    /// `yyyy-MM-dd-HHmmss` in UTC, without Calendar (the same on every platform).
    static func timestamp(ms: Int64) -> String {
        let seconds = ms >= 0 ? ms / 1000 : (ms - 999) / 1000
        let days = seconds >= 0 ? seconds / 86_400 : (seconds - 86_399) / 86_400
        let rest = Int(seconds - days * 86_400)
        let time = [rest / 3600, rest % 3600 / 60, rest % 60].map { $0 < 10 ? "0\($0)" : "\($0)" }.joined()
        return "\(LocalDay.string(dayNumber: days))-\(time)"
    }
}

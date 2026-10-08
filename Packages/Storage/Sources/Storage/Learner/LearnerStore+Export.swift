import Foundation
import GRDB

/// A copy of the learner database for the Debug menu's "Export the learner DB" (docs/02 § App configuration).
extension LearnerStore {
    /// Writes a consistent copy of the whole database to `destination` with SQLite's online backup of a read
    /// snapshot, so appends carry on meanwhile. The copy is one self-contained file (rollback journal, no `-wal`);
    /// an existing file there is replaced. Nothing in this database changes.
    public func exportCopy(to destination: URL) async throws(StorageError) {
        let path = destination.path
        let files = FileManager.default
        do {
            try files.createDirectory(at: destination.deletingLastPathComponent(), withIntermediateDirectories: true)
            for suffix in ["", "-wal", "-shm", "-journal"] where files.fileExists(atPath: path + suffix) {
                try files.removeItem(atPath: path + suffix)
            }
        } catch {
            throw .file(path: path, reason: "can't prepare the export: \(error)")
        }
        let target: DatabaseQueue
        do {
            target = try DatabaseQueue(path: path)
        } catch {
            throw StorageError.wrap(error, path: path)
        }
        try await read { db in
            try target.writeWithoutTransaction { copy in
                try db.backup(to: copy)
                // The source is WAL; the backup copies its header, so switch the copy back to a rollback journal.
                try copy.execute(sql: "PRAGMA journal_mode = DELETE")
            }
        }
        do {
            try target.close()
        } catch {
            throw StorageError.wrap(error, path: path)
        }
    }
}

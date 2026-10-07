import Foundation
import GRDB
import LearningCore

/// Storage module: the read-only content pack (`PackReader`) and the learner database (`LearnerStore`),
/// both on GRDB (docs/02 § Storage).
public enum StorageInfo {
    /// The SQLite library version GRDB links against.
    public static func sqliteVersion() throws -> String {
        let queue = try DatabaseQueue()
        return try queue.read { db in try String.fetchOne(db, sql: "SELECT sqlite_version()") ?? "?" }
    }
}

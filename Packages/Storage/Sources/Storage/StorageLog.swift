import Foundation
import LearningCore

#if canImport(os)
import os
#endif

/// Storage's logging (docs/02 § Logging and errors): `os.Logger`, subsystem `com.j23n.italian`, one category per
/// area. On Linux (tests and CI) there is no `os`, so it logs nothing. Never log learner free text: replay messages
/// carry only IDs, and errors only SQLite's message and the file path.
enum StorageLog {
    #if canImport(os)
    static let pack = Logger(subsystem: "com.j23n.italian", category: "pack")
    static let learner = Logger(subsystem: "com.j23n.italian", category: "learner")
    static let replay = Logger(subsystem: "com.j23n.italian", category: "replay")
    #endif

    /// The pack could not be opened (the App shows the pack error screen).
    static func packFailed(_ error: PackError) {
        #if canImport(os)
        pack.error("content pack refused: \(error.description, privacy: .public)")
        #endif
    }

    /// The learner database could not be opened or migrated.
    static func learnerFailed(_ error: StorageError) {
        #if canImport(os)
        learner.error("learner database refused: \(error.description, privacy: .private)")
        #endif
    }

    /// A write failed; nothing was changed.
    static func writeFailed(_ error: StorageError) {
        #if canImport(os)
        learner.error("learner database write rolled back: \(error.description, privacy: .private)")
        #endif
    }

    /// The derived state was rebuilt from the whole log at open.
    static func rebuilt(reason: String, events: Int) {
        #if canImport(os)
        learner.notice("rebuilt derived state from \(events, privacy: .public) events (\(reason, privacy: .public))")
        #endif
    }

    /// A synced record that isn't a valid event was skipped.
    static func skippedRecord(_ recordName: String) {
        #if canImport(os)
        learner.error("skipped an invalid Event record \(recordName, privacy: .public)")
        #endif
    }

    /// An unusable learner database was moved aside and a fresh one created.
    static func recovered(_ error: StorageError, backup: URL) {
        #if canImport(os)
        let name = backup.lastPathComponent
        let reason = error.description
        learner.error("learner database moved aside to \(name, privacy: .public): \(reason, privacy: .private)")
        #endif
    }

    /// The reducer's messages (skipped events and the like): IDs only.
    struct ReplayLogger: CoreLogger {
        func log(_ message: String) {
            #if canImport(os)
            StorageLog.replay.debug("\(message, privacy: .public)")
            #endif
        }
    }
}

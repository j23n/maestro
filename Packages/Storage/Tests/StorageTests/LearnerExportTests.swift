import Foundation
import GRDB
import LearningCore
import LearningCoreTestSupport
import Testing

@testable import Storage

/// The Debug menu's "Export the learner DB" (docs/02): a self-contained, consistent copy.
@Suite struct LearnerExportTests {
    @Test func theCopyHoldsEverythingAndIsOneFile() async throws {
        let db = try TestLearnerDB()
        let store = try db.open()
        defer { try? store.close() }
        try await store.append(SyntheticLearner.log(120))
        try await store.set(.profileName, to: .string("Sam"))
        let copy = db.folder.appendingPathComponent("export/learner-copy.sqlite")

        try await store.exportCopy(to: copy)
        // Exporting again replaces the file; the store keeps working.
        try await store.append(SyntheticLearner.log(130).suffix(10).map { $0 })
        try await store.exportCopy(to: copy)

        #expect(!FileManager.default.fileExists(atPath: copy.path + "-wal"))
        let queue = try DatabaseQueue(path: copy.path)
        defer { try? queue.close() }
        let (events, name, mode) = try await queue.read { db in
            (
                try Int.fetchOne(db, sql: "SELECT COUNT(*) FROM events") ?? 0,
                try String.fetchOne(db, sql: "SELECT value FROM settings WHERE key = 'profile.name'"),
                try String.fetchOne(db, sql: "PRAGMA journal_mode")
            )
        }
        #expect(events == 130)
        #expect(name == #""Sam""#)
        #expect(mode == "delete")
        #expect(try await store.eventCount() == 130)
    }
}

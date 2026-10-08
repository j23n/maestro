import Foundation
import GRDB
import LearningCore
import LearningCoreTestSupport
import Testing

@testable import Storage

/// Learner-DB recovery primitives (docs/02 § Logging and errors; task M3.9) against deliberately damaged files.
@Suite struct LearnerRecoveryTests {
    /// A store with some progress, closed, then damaged: everything after the 100-byte header of page 1 (the
    /// schema's root page) overwritten.
    func damagedDatabase(_ db: TestLearnerDB) async throws -> Data {
        let store = try db.open()
        try await store.append(SyntheticLearner.log(150))
        try store.close()
        let handle = try FileHandle(forUpdating: db.url)
        try handle.seek(toOffset: 100)
        try handle.write(contentsOf: Data(repeating: 0xA5, count: 3_996))
        try handle.close()
        return try Data(contentsOf: db.url)
    }

    @Test func aFileThatIsNotADatabaseIsCorrupt() throws {
        let db = try TestLearnerDB()
        try Data(String(repeating: "not a database ", count: 400).utf8).write(to: db.url)
        #expect {
            try db.open()
        } throws: { error in
            (error as? StorageError)?.isCorruption == true
        }
    }

    @Test func aDamagedSchemaPageIsCorrupt() async throws {
        let db = try TestLearnerDB()
        _ = try await damagedDatabase(db)
        #expect {
            try db.open()
        } throws: { error in
            (error as? StorageError)?.isCorruption == true
        }
    }

    @Test func openRecoveringBacksUpTheFileAndStartsFresh() async throws {
        let db = try TestLearnerDB()
        let damaged = try await damagedDatabase(db)
        let (store, recovery) = try await LearnerStore.openRecovering(
            url: db.url, content: TestCourse.standard, clock: db.clock, ids: SeededUUIDSource(seed: "fresh"))
        let report = try #require(recovery)
        #expect(report.error.isCorruption)
        #expect(report.backupURL.lastPathComponent == "learner-2026-01-05-090000.corrupt.sqlite")
        #expect(try Data(contentsOf: report.backupURL) == damaged)
        // A fresh, working database: no events, the initial state, ready for sync to bring the events back.
        #expect(try await store.eventCount() == 0)
        #expect(store.state == Replay.initialState(content: TestCourse.standard))
        let events = SyntheticLearner.log(40)
        try await store.insertRemote(events)
        #expect(store.state == Replay.rebuildAll(events: events, content: TestCourse.standard))
        try store.close()
    }

    @Test func openRecoveringLeavesAHealthyDatabaseAlone() async throws {
        let db = try TestLearnerDB()
        let first = try db.open()
        try await first.append(SyntheticLearner.log(20))
        try first.close()
        let (store, recovery) = try await LearnerStore.openRecovering(
            url: db.url, content: TestCourse.standard, clock: db.clock, ids: SeededUUIDSource(seed: "x"))
        defer { try? store.close() }
        #expect(recovery == nil)
        #expect(try await store.eventCount() == 20)
        let files = try FileManager.default.contentsOfDirectory(atPath: db.folder.path)
        #expect(!files.contains { $0.contains(".corrupt.") })
    }

    @Test func movingAsideTakesTheSidecarsAndKeepsNamesUnique() throws {
        let db = try TestLearnerDB()
        for suffix in ["", "-wal", "-shm"] { try Data([1]).write(to: URL(fileURLWithPath: db.url.path + suffix)) }
        let first = try LearnerStore.moveAside(db.url, as: .archive, clock: db.clock)
        #expect(first.lastPathComponent == "learner-2026-01-05-090000.archive.sqlite")
        for suffix in ["", "-wal", "-shm"] {
            #expect(FileManager.default.fileExists(atPath: first.path + suffix))
            #expect(!FileManager.default.fileExists(atPath: db.url.path + suffix))
        }
        try Data([2]).write(to: db.url)
        let second = try LearnerStore.moveAside(db.url, as: .archive, clock: db.clock)
        #expect(second.lastPathComponent == "learner-2026-01-05-090000-2.archive.sqlite")
        #expect(try Data(contentsOf: second) == Data([2]))
    }

    @Test func backupTimestampsAreUTC() {
        #expect(LearnerStore.timestamp(ms: 0) == "1970-01-01-000000")
        #expect(LearnerStore.timestamp(ms: mondayNine + 3_723_000) == "2026-01-05-100203")
        #expect(LearnerStore.timestamp(ms: -1) == "1969-12-31-235959")
    }

    @Test func storageErrorsMapSQLiteCodes() {
        let corrupt = StorageError.wrap(DatabaseError(resultCode: .SQLITE_CORRUPT), path: "p")
        #expect(corrupt.isCorruption)
        #expect(StorageError.wrap(DatabaseError(resultCode: .SQLITE_NOTADB), path: "p").isCorruption)
        #expect(
            StorageError.wrap(DatabaseError(resultCode: .SQLITE_FULL), path: "p")
                == .file(path: "p", reason: DatabaseError(resultCode: .SQLITE_FULL).description))
        #expect(!StorageError.wrap(DatabaseError(resultCode: .SQLITE_CONSTRAINT), path: "p").isCorruption)
    }
}

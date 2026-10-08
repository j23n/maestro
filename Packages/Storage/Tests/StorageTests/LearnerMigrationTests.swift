import Foundation
import GRDB
import LearningCore
import LearningCoreTestSupport
import Testing

@testable import Storage

/// The migrations implement docs/03 § The learner database: the tables are exactly those of the reference DDL, with
/// the same columns, types, nullability, defaults and primary keys (the DDL is read from the doc itself).
@Suite struct LearnerMigrationTests {
    /// The reference DDL: the ```sql block under "## The learner database" in docs/03.
    static func referenceDDL() throws -> String {
        let doc = try String(contentsOf: Repo.url("docs/03-content-model.md"), encoding: .utf8)
        let section = try #require(doc.range(of: "## The learner database"))
        let rest = doc[section.upperBound...]
        let start = try #require(rest.range(of: "```sql\n"))
        let end = try #require(rest[start.upperBound...].range(of: "```"))
        return String(rest[start.upperBound..<end.lowerBound])
    }

    static func columns(_ db: Database, _ table: String) throws -> [String] {
        try Row.fetchAll(db, sql: "PRAGMA table_info(\(table))").map { row in
            let name: String = row["name"]
            let type: String = row["type"]
            let notNull: Int = row["notnull"]
            let defaultValue: String? = row["dflt_value"]
            let pk: Int = row["pk"]
            return "\(name) \(type) notnull=\(notNull) default=\(defaultValue ?? "-") pk=\(pk)"
        }
    }

    static func tables(_ db: Database) throws -> Set<String> {
        Set(try String.fetchAll(db, sql: "SELECT name FROM sqlite_master WHERE type = 'table'"))
    }

    @Test func everyReferenceTableExistsWithTheSameColumns() throws {
        let reference = try DatabaseQueue()
        try reference.write { db in try db.execute(sql: try Self.referenceDDL()) }
        let db = try TestLearnerDB()
        let store = try db.open()
        defer { try? store.close() }
        let referenceTables = try reference.read { db in try Self.tables(db) }
        #expect(referenceTables.count == 17)
        try read(store) { stored in
            let storedTables = try Self.tables(stored)
            for table in referenceTables.sorted() {
                #expect(storedTables.contains(table), "\(table)")
                let expected = try reference.read { db in try Self.columns(db, table) }
                #expect(try Self.columns(stored, table) == expected, "\(table)")
            }
            // Nothing undocumented: every table is in docs/03 (GRDB adds its own bookkeeping table).
            #expect(storedTables.subtracting(referenceTables) == ["grdb_migrations"])
            #expect(Set(LearnerSchema.allTables) == storedTables.subtracting(["grdb_migrations"]))
            let indexes = try String.fetchAll(stored, sql: "SELECT name FROM sqlite_master WHERE type = 'index'")
            #expect(indexes.contains("events_order"))
            #expect(try String.fetchOne(stored, sql: "PRAGMA journal_mode") == "wal")
        }
    }

    @Test func reopeningKeepsTheMigrationsTheDeviceIdAndTheData() async throws {
        let db = try TestLearnerDB()
        let first = try db.open()
        let deviceId = first.deviceId
        #expect(UUID(uuidString: deviceId) != nil && deviceId == deviceId.lowercased())
        let factory = try await first.makeEventFactory(packVersion: "0.1.0", ids: SeededUUIDSource(seed: "f"))
        try await first.append(factory.stepStarted(TestCourse.step(0, "preview"), sessionId: "s"))
        try first.close()

        let second = try db.open(device: "another-seed")
        defer { try? second.close() }
        #expect(second.deviceId == deviceId)
        #expect(second.launchRebuild == nil)
        #expect(try await second.eventCount() == 1)
        let applied = try read(second) { db in
            try String.fetchAll(db, sql: "SELECT identifier FROM grdb_migrations")
        }
        #expect(applied == ["v1"])
    }

    @Test func aFreshDatabaseStartsWithTheInitialState() throws {
        let db = try TestLearnerDB()
        let store = try db.open()
        defer { try? store.close() }
        #expect(store.launchRebuild == .noDerivedState)
        #expect(store.state == Replay.initialState(content: TestCourse.standard))
        // One unit_progress row per unit, Unit 0 available; derived_meta names the version and the pack.
        #expect(try count(store, "unit_progress") == TestCourse.standard.units.count)
        let meta = try read(store) { db in try DerivedMeta.read(db) }
        #expect(
            meta
                == DerivedMeta(
                    derivedVersion: Replay.derivedVersion, contentHash: "hash-1", lastApplied: nil,
                    eventCount: 0))
    }
}

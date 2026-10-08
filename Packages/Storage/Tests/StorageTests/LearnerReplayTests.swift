import Foundation
import GRDB
import LearningCore
import LearningCoreTestSupport
import Testing

@testable import Storage

/// The replay driver against `fixtures/replay/*.json` (the same expectations as LearningCore's ReplayFixtureTests,
/// here through appends, synced inserts, the derived tables and reopening).
@Suite struct LearnerStoreReplayFixtureTests {
    let content = TestCourse.standard

    func load(_ name: String) throws -> [String: Any] {
        let data = try Data(contentsOf: Repo.url("fixtures/replay/\(name)"))
        return try #require(try JSONSerialization.jsonObject(with: data) as? [String: Any])
    }

    func events(_ value: Any?) throws -> [Event] {
        try EventCodec.decodeLog(try JSONSerialization.data(withJSONObject: try #require(value)))
    }

    func pair(_ key: String) -> (item: String, skill: String) {
        let parts = key.split(separator: "/").map(String.init)
        return (parts[0], parts[1])
    }

    @Test func resumeMidStep() async throws {
        let fixture = try load("resume-mid-step.json")
        let stepId = StepID(try #require(fixture["step"] as? String))
        let step = try #require(content.step(stepId))
        let log = try events(fixture["events"])
        let db = try TestLearnerDB()
        var store = try db.open(checkpointInterval: 4)
        var applied = 0
        for checkpoint in try #require(fixture["checkpoints"] as? [[String: Any]]) {
            let count = try #require(checkpoint["afterEvents"] as? Int)
            for event in log[applied..<count] { try await store.append(event) }
            applied = count
            // Quit and relaunch: the checkpoint plus the events after it give the same state.
            let before = store.state
            try store.close()
            store = try db.open(checkpointInterval: 4)
            #expect(store.launchRebuild == nil)
            #expect(store.state == before)

            let state = store.state
            #expect(state.cursor(stepId) == checkpoint["cursor"] as? Int)
            #expect(Progression.resumeExercise(step: step, state: state)?.rawValue == checkpoint["resumeAt"] as? String)
            #expect(state.stepProgress(stepId)?.isOpen == checkpoint["open"] as? Bool)
            #expect(state.stepProgress(stepId)?.isComplete == checkpoint["completed"] as? Bool)
            let row = try read(store) { db in
                try Row.fetchOne(
                    db, sql: "SELECT cursor, completed_at FROM step_progress WHERE step_id = ?",
                    arguments: [stepId.rawValue])
            }
            #expect(row?["cursor"] as Int? == checkpoint["cursor"] as? Int)
            let completedAt: Int64? = row?["completed_at"]
            #expect((completedAt != nil) == (checkpoint["completed"] as? Bool ?? false))
        }
        try store.close()
    }

    @Test(arguments: 0..<8)
    func twoDevicesConvergeThroughTheStore(seed: Int) async throws {
        let fixture = try load("two-devices.json")
        let devices = try #require(fixture["devices"] as? [String: Any])
        let ipad = try events(devices["ipad-1"])
        let iphone = try events(devices["iphone-1"])
        let reference = Replay.rebuildAll(events: ipad + iphone, content: content)
        var rng = SplitMix64(seedString: "store-fixture-\(seed)")
        for (index, (own, other)) in [(ipad, iphone), (iphone, ipad)].enumerated() {
            let db = try TestLearnerDB("twoDevices\(seed)-\(index)")
            let store = try db.open(checkpointInterval: 3)
            try await store.append(own)
            let parcel = (other + other.filter { _ in rng.nextInt(below: 3) == 0 } + own.prefix(2))
                .seededShuffle(using: &rng)
            for chunk in stride(from: 0, to: parcel.count, by: 4) {
                try await store.insertRemote(Array(parcel[chunk..<min(chunk + 4, parcel.count)]))
            }
            #expect(try store.state.canonicalEncoding() == reference.canonicalEncoding())
            #expect(try count(store, "events") == ipad.count + iphone.count)
            #expect(try count(store, "sync_pending") == own.count)
            let incremental = try derivedSnapshot(store)
            if seed == 0 { try checkExpected(fixture, store) }
            try store.close()

            let reopened = try db.open(checkpointInterval: 3)
            #expect(reopened.launchRebuild == nil)
            #expect(try reopened.state.canonicalEncoding() == reference.canonicalEncoding())
            try await reopened.rebuildAll()
            #expect(try derivedSnapshot(reopened) == incremental)
            try reopened.close()
        }
    }

    /// The fixture's expectations, read back from the derived tables.
    func checkExpected(_ fixture: [String: Any], _ store: LearnerStore) throws {
        let expected = try #require(fixture["expected"] as? [String: Any])
        try read(store) { db in
            for (key, value) in try #require(expected["introductions"] as? [String: [String: Any]]) {
                let (item, skill) = pair(key)
                let row = try Row.fetchOne(
                    db, sql: "SELECT at, via FROM introductions WHERE item_id = ? AND skill = ?",
                    arguments: [item, skill])
                #expect(row?["via"] as String? == value["via"] as? String, "\(key)")
                #expect(row?["at"] as Int64? == (value["at"] as? NSNumber)?.int64Value, "\(key)")
            }
            for (key, reps) in try #require(expected["memoryReps"] as? [String: Int]) {
                let (item, skill) = pair(key)
                let stored = try Int.fetchOne(
                    db, sql: "SELECT reps FROM memory WHERE item_id = ? AND skill = ?",
                    arguments: [item, skill])
                #expect((stored ?? 0) == reps, "\(key)")
            }
            for (key, value) in try #require(expected["steps"] as? [String: [String: Any]]) {
                let row = try Row.fetchOne(
                    db, sql: "SELECT completed_at, cursor FROM step_progress WHERE step_id = ?",
                    arguments: [key])
                #expect(row?["completed_at"] as Int64? == (value["completedAt"] as? NSNumber)?.int64Value, "\(key)")
                #expect(row?["cursor"] as Int? == value["cursor"] as? Int, "\(key)")
            }
            for (key, value) in try #require(expected["units"] as? [String: String]) {
                let state = try String.fetchOne(
                    db, sql: "SELECT state FROM unit_progress WHERE unit_id = ?",
                    arguments: [key])
                #expect(state == value, "\(key)")
            }
            for (key, value) in try #require(expected["days"] as? [String: [String: Int]]) {
                let row = try #require(
                    try Row.fetchOne(
                        db, sql: "SELECT * FROM daily_activity WHERE local_day = ?",
                        arguments: [key]))
                #expect(row["active_seconds"] as Int? == value["activeSeconds"])
                #expect(row["steps_completed"] as Int? == value["stepsCompleted"])
                #expect(row["cards_reviewed"] as Int? == value["cardsReviewed"])
            }
            let lastApplied = try String.fetchOne(
                db, sql: "SELECT value FROM derived_meta WHERE key = 'last_applied_id'")
            #expect(lastApplied == expected["lastApplied"] as? String)
        }
    }
}

/// Incremental replay through the store equals a full rebuild (docs/10: Storage tests), whatever the delivery
/// order, and reopening (checkpoint + catch-up) or a changed pack or reducer leads to the same place.
@Suite struct LearnerReplayDriverTests {
    let content = TestCourse.standard

    @Test(arguments: 0..<4)
    func randomDeliveryEqualsAFullRebuild(seed: Int) async throws {
        let phone = SyntheticLearner.log(700, device: "phone-\(seed)")
        // The second device's clock runs 90 minutes behind: its events interleave with the phone's.
        var pad = SyntheticLearner(device: "pad-\(seed)", start: mondayNine - 5_400_000)
        pad.run(until: 500)
        let padEvents = Array(pad.events.prefix(500))
        let reference = Replay.rebuildAll(events: phone + padEvents, content: content)

        let db = try TestLearnerDB("randomDelivery\(seed)")
        var store = try db.open(checkpointInterval: 64)
        var rng = SplitMix64(seedString: "delivery-\(seed)")
        var p = 0
        var q = 0
        var rebuilds = 0
        while p < phone.count || q < padEvents.count {
            if q >= padEvents.count || (p < phone.count && rng.nextInt(below: 2) == 0) {
                let n = min(1 + rng.nextInt(below: 30), phone.count - p)
                try await store.append(Array(phone[p..<p + n]))
                p += n
            } else {
                let n = min(1 + rng.nextInt(below: 60), padEvents.count - q)
                let batch = Array(padEvents[q..<q + n]).seededShuffle(using: &rng)
                if try await store.insertRemote(batch).rebuilt { rebuilds += 1 }
                q += n
            }
            if rng.nextInt(below: 10) == 0 {
                let before = store.state
                try store.close()
                store = try db.open(checkpointInterval: 64)
                #expect(store.launchRebuild == nil)
                #expect(store.state == before)
            }
        }
        #expect(rebuilds > 0)
        #expect(try store.state.canonicalEncoding() == reference.canonicalEncoding())
        let incremental = try derivedSnapshot(store)
        try await store.rebuildAll()
        #expect(try derivedSnapshot(store) == incremental)
        try store.close()
    }

    func storeWithEvents(_ db: TestLearnerDB, _ n: Int, checkpointInterval: Int = 250) async throws -> [Event] {
        let store = try db.open(checkpointInterval: checkpointInterval)
        let events = SyntheticLearner.log(n)
        try await store.append(events)
        try store.close()
        return events
    }

    @Test func reopeningCatchesUpFromTheCheckpoint() async throws {
        let db = try TestLearnerDB()
        let store = try db.open(checkpointInterval: 10)
        let events = SyntheticLearner.log(57)
        for event in events { try await store.append(event) }
        let checkpointed = try read(store) { db in
            try JSONDecoder().decode(
                LearnerState.self,
                from: try #require(
                    try Data.fetchOne(db, sql: "SELECT state FROM derived_checkpoint")))
        }
        #expect(checkpointed.lastApplied == events[49].key)
        try store.close()

        let reopened = try db.open(checkpointInterval: 10)
        #expect(reopened.launchRebuild == nil)
        #expect(reopened.state == Replay.rebuildAll(events: events, content: content))
        // The caught-up state was saved: the next launch has nothing to replay.
        let saved = try read(reopened) { db in
            try JSONDecoder().decode(
                LearnerState.self,
                from: try #require(
                    try Data.fetchOne(db, sql: "SELECT state FROM derived_checkpoint")))
        }
        #expect(saved.lastApplied == events.last?.key)
        try reopened.close()
    }

    @Test func checkpointWritesOnlyWhenSomethingChanged() async throws {
        let db = try TestLearnerDB()
        let store = try db.open(checkpointInterval: 1_000)
        defer { try? store.close() }
        let events = SyntheticLearner.log(30)
        try await store.append(events)
        try await store.checkpoint()
        let saved = try read(store) { db in
            try JSONDecoder().decode(
                LearnerState.self,
                from: try #require(
                    try Data.fetchOne(db, sql: "SELECT state FROM derived_checkpoint")))
        }
        #expect(saved == store.state)
        #expect(store.live.current.sinceCheckpoint == 0)
    }

    @Test func aChangedPackRebuilds() async throws {
        let db = try TestLearnerDB()
        let events = try await storeWithEvents(db, 300)
        let newPack = TestCourse.make(contentHash: "hash-2")
        let store = try db.open(content: newPack)
        defer { try? store.close() }
        #expect(store.launchRebuild == .contentChanged)
        #expect(store.state == Replay.rebuildAll(events: events, content: newPack))
        #expect(try read(store) { db in try DerivedMeta.read(db) }.contentHash == "hash-2")
    }

    /// The ways the stored derived state can be stale or unusable, and the rebuild each one triggers.
    enum Damage: String, CaseIterable, CustomTestStringConvertible {
        case derivedVersion, noCheckpoint, unreadableCheckpoint, eventOutsideTheStore, noMeta
        var testDescription: String { rawValue }

        var reason: RebuildReason {
            switch self {
            case .derivedVersion: .derivedVersionChanged
            case .noCheckpoint, .unreadableCheckpoint, .eventOutsideTheStore, .noMeta: .noDerivedState
            }
        }

        func apply(_ db: Database, extra: Event) throws {
            switch self {
            case .derivedVersion:
                try db.execute(sql: "UPDATE derived_meta SET value = '0' WHERE key = 'derived_version'")
            case .noCheckpoint: try db.execute(sql: "DELETE FROM derived_checkpoint")
            case .unreadableCheckpoint: try db.execute(sql: "UPDATE derived_checkpoint SET state = x'7b7d'")
            case .eventOutsideTheStore:
                let row = try EventRow(extra, origin: .remote)
                try db.execute(
                    sql: "INSERT INTO events (\(EventRow.columns)) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    arguments: row.arguments)
            case .noMeta: try db.execute(sql: "DELETE FROM derived_meta")
            }
        }
    }

    @Test(arguments: Damage.allCases)
    func staleOrMissingDerivedStateRebuildsAtOpen(_ damage: Damage) async throws {
        let db = try TestLearnerDB()
        var events = try await storeWithEvents(db, 120, checkpointInterval: 50)
        let extra = SyntheticLearner.log(121).last
        let queue = try db.queue()
        let event = try #require(extra)
        try await queue.write { db in try damage.apply(db, extra: event) }
        try queue.close()
        if damage == .eventOutsideTheStore, let extra { events.append(extra) }

        let store = try db.open(checkpointInterval: 50)
        defer { try? store.close() }
        #expect(store.launchRebuild == damage.reason)
        #expect(store.state == Replay.rebuildAll(events: events, content: content))
        let rebuilt = try derivedSnapshot(store)
        try await store.rebuildAll()
        #expect(try derivedSnapshot(store) == rebuilt)
    }

    @Test func anUnreadableRowIsSkippedNotFatal() async throws {
        let db = try TestLearnerDB()
        let events = try await storeWithEvents(db, 60)
        let queue = try db.queue()
        try await queue.write { db in
            try db.execute(sql: """
                INSERT INTO events (\(EventRow.columns))
                VALUES ('0bad0000-0000-4000-8000-000000000000', 'yesterday', 0, 'glossTapped', 'x', 1, '0', '{}', 'remote')
                """)
        }
        try queue.close()
        let store = try db.open()
        defer { try? store.close() }
        #expect(store.launchRebuild == .noDerivedState)
        #expect(store.state == Replay.rebuildAll(events: events, content: content))
        #expect(try await store.events() == events)
        // The next launch is consistent again (the row still counts, so nothing is rebuilt).
        try store.close()
        let again = try db.open()
        #expect(again.launchRebuild == nil)
        try again.close()
    }

    @Test func eventsWithIDsMissingFromThePackAreKeptAndSkipped() async throws {
        let db = try TestLearnerDB()
        let store = try db.open()
        defer { try? store.close() }
        let factory = EventFactory(
            deviceId: "d", packVersion: "0.0.9", clock: db.clock, ids: SeededUUIDSource(seed: "r"))
        let retired = factory.stepStarted(StepID("u00.l9.step-gone"), sessionId: "s")
        let result = try await store.append(retired)
        #expect(result.inserted == [retired])
        #expect(result.state.stepProgress(StepID("u00.l9.step-gone")) == nil)
        #expect(try count(store, "events") == 1)
    }
}

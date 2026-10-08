import Foundation
import GRDB
import LearningCore
import LearningCoreTestSupport
import Testing

@testable import Storage

/// docs/02 § Storage: an event append, its derived-state update and its `sync_pending` row happen in one
/// transaction; a failure anywhere leaves the file and the in-memory state as they were.
@Suite struct LearnerAppendTests {
    let content = TestCourse.standard

    /// A short lesson: start the preview, introduce its items, answer its exercises.
    func lesson(_ factory: EventFactory) -> [Event] {
        let step = content.step(TestCourse.step(0, "preview"))
        var events = [factory.stepStarted(TestCourse.step(0, "preview"), sessionId: "s")]
        if let pairs = step?.introduces, let intro = factory.introduced(pairs, via: .preview) { events.append(intro) }
        for id in step?.presentationOrder ?? [] {
            guard let exercise = content.exercise(id) else { continue }
            events.append(
                factory.attempt(
                    exerciseId: id, format: exercise.format, context: .lesson,
                    stepId: exercise.stepId, sessionId: "s", outcome: .correct,
                    targets: exercise.targets, mode: .typed, latencyMs: 1_000))
        }
        return events
    }

    func factory(_ db: TestLearnerDB, _ store: LearnerStore) -> EventFactory {
        EventFactory(deviceId: store.deviceId, packVersion: "0.1.0", clock: db.clock, ids: SeededUUIDSource(seed: "e"))
    }

    @Test func appendWritesTheEventItsPendingRowAndTheDerivedRows() async throws {
        let db = try TestLearnerDB()
        let store = try db.open()
        defer { try? store.close() }
        let events = lesson(factory(db, store))
        let result = try await store.append(events)
        #expect(result.inserted == events)
        #expect(!result.rebuilt)
        #expect(result.state == Replay.rebuildAll(events: events, content: content))
        #expect(store.state == result.state)

        #expect(try count(store, "events") == events.count)
        let pending = try await store.pendingChanges()
        #expect(pending.map(\.recordName).sorted() == events.map(\.id).sorted())
        #expect(pending.allSatisfy { $0.recordType == .event && $0.addedAt == mondayNine })
        #expect(try count(store, "memory") == result.state.memory.count)
        #expect(try count(store, "introductions") == result.state.introductions.count)
        // Stored as written: local origin, canonical payload.
        let row = try #require(try await store.eventRow(id: events[2].id))
        #expect(row.origin == .local)
        #expect(row.payload == (try EventCodec.payloadString(events[2].payload)))
        #expect(row.event == events[2])
        // The rows are exactly what a full rebuild writes.
        let incremental = try derivedSnapshot(store)
        try await store.rebuildAll()
        #expect(try derivedSnapshot(store) == incremental)
    }

    @Test func appendingAnEventAgainChangesNothing() async throws {
        let db = try TestLearnerDB()
        let store = try db.open()
        defer { try? store.close() }
        let events = lesson(factory(db, store))
        try await store.append(events)
        try await store.removePending(recordNames: [events[0].id])
        let before = try derivedSnapshot(store)
        let again = try await store.append(events)
        #expect(again.inserted.isEmpty)
        #expect(try count(store, "events") == events.count)
        #expect(try derivedSnapshot(store) == before)
        // An uploaded event isn't marked pending again.
        #expect(try await store.pendingChanges().count == events.count - 1)
    }

    /// Where the injected failure strikes: the event insert has run in each case.
    enum Failure: String, CaseIterable, CustomTestStringConvertible {
        case syncPending = "sync_pending"
        case derivedTable = "memory"
        case derivedMeta = "derived_meta"
        var testDescription: String { rawValue }
    }

    @Test(arguments: Failure.allCases)
    func aFailureMidTransactionLeavesNothingBehind(_ failure: Failure) async throws {
        let db = try TestLearnerDB()
        let store = try db.open()
        defer { try? store.close() }
        let factory = factory(db, store)
        let events = lesson(factory)
        try await store.append(Array(events.prefix(2)))
        let stateBefore = store.state
        let tablesBefore = try derivedSnapshot(store)
        let pendingBefore = try await store.pendingChanges()

        try await store.pool.write { db in
            try db.execute(
                sql: """
                    CREATE TRIGGER injected BEFORE INSERT ON \(failure.rawValue)
                    BEGIN SELECT RAISE(ABORT, 'injected failure'); END
                    """)
        }
        await #expect(throws: StorageError.self) { try await store.append(Array(events.dropFirst(2))) }
        #expect(try count(store, "events") == 2)
        #expect(try await store.pendingChanges() == pendingBefore)
        #expect(try derivedSnapshot(store) == tablesBefore)
        #expect(store.state == stateBefore)

        // The same append succeeds once the fault is gone, and matches a full rebuild.
        try await store.pool.write { db in try db.execute(sql: "DROP TRIGGER injected") }
        let result = try await store.append(Array(events.dropFirst(2)))
        #expect(!result.rebuilt)
        #expect(result.state == Replay.rebuildAll(events: events, content: content))
        let incremental = try derivedSnapshot(store)
        try await store.rebuildAll()
        #expect(try derivedSnapshot(store) == incremental)
    }

    @Test func aFailedEnqueuedAppendReportsAndLeavesNothing() async throws {
        let db = try TestLearnerDB()
        let store = try db.open()
        defer { try? store.close() }
        try await store.pool.write { db in
            try db.execute(
                sql: "CREATE TRIGGER injected BEFORE INSERT ON sync_pending BEGIN SELECT RAISE(ABORT, 'x'); END")
        }
        let event = factory(db, store).stepStarted(TestCourse.step(0, "preview"), sessionId: "s")
        let result = await withCheckedContinuation { continuation in
            store.enqueueAppend(event) { continuation.resume(returning: $0) }
        }
        guard case .failure = result else {
            Issue.record("expected a failure")
            return
        }
        #expect(try count(store, "events") == 0)
        #expect(store.state == Replay.initialState(content: content))
    }

    @Test func enqueuedAppendsKeepTheirOrderAndNeverRebuild() async throws {
        let db = try TestLearnerDB()
        let store = try db.open()
        defer { try? store.close() }
        let events = SyntheticLearner.log(400)
        let results = Locked<[LearnerStore.AppendResult]>([])
        await withCheckedContinuation { (done: CheckedContinuation<Void, Never>) in
            for (i, event) in events.enumerated() {
                store.enqueueAppend(event) { result in
                    if case .success(let r) = result { results.withLock { $0.append(r) } }
                    if i == events.count - 1 { done.resume() }
                }
            }
        }
        #expect(results.current.count == events.count)
        #expect(results.current.allSatisfy { !$0.rebuilt })
        #expect(
            try store.state.canonicalEncoding()
                == Replay.rebuildAll(events: events, content: content)
                .canonicalEncoding())
    }

    @Test func concurrentAppendsFromManyTasksEndInTheRebuiltState() async throws {
        let db = try TestLearnerDB()
        let store = try db.open(checkpointInterval: 37)
        defer { try? store.close() }
        let events = SyntheticLearner.log(600)
        try await withThrowingTaskGroup(of: Void.self) { group in
            for chunk in stride(from: 0, to: events.count, by: 50) {
                let slice = Array(events[chunk..<min(chunk + 50, events.count)])
                group.addTask { for event in slice { try await store.append(event) } }
            }
            try await group.waitForAll()
        }
        let reference = Replay.rebuildAll(events: events, content: content)
        #expect(try store.state.canonicalEncoding() == reference.canonicalEncoding())
        #expect(try count(store, "events") == events.count)
        #expect(try count(store, "sync_pending") == events.count)
        let incremental = try derivedSnapshot(store)
        try await store.rebuildAll()
        #expect(try derivedSnapshot(store) == incremental)
    }

    @Test func remoteEventsAreNotPendingAndAnEarlierOneRebuilds() async throws {
        let db = try TestLearnerDB()
        let store = try db.open()
        defer { try? store.close() }
        let local = lesson(factory(db, store))
        try await store.append(local)
        // Another device answered earlier (it was offline): it sorts before the last applied event.
        let other = EventFactory(
            deviceId: "ipad", packVersion: "0.1.0", clock: FixedClock(ms: mondayNine - 60_000),
            ids: SeededUUIDSource(seed: "ipad"))
        let remote = [other.stepStarted(TestCourse.step(0, "story"), sessionId: "p")]
        let result = try await store.insertRemote(remote)
        #expect(result.rebuilt)
        #expect(result.inserted.map(\.origin) == [.remote])
        #expect(try await store.pendingChanges().count == local.count)
        #expect(result.state == Replay.rebuildAll(events: local + remote, content: content))
        #expect(try await store.eventRow(id: remote[0].id)?.origin == .remote)
        // The same event again (sync delivers duplicates): ignored.
        #expect(try await store.insertRemote(remote).inserted.isEmpty)
    }

    @Test func remoteRecordsKeepTheirPayloadBytes() async throws {
        let db = try TestLearnerDB()
        let store = try db.open()
        defer { try? store.close() }
        let other = EventFactory(
            deviceId: "mac", packVersion: "0.2.0", clock: FixedClock(ms: mondayNine),
            ids: SeededUUIDSource(seed: "mac"))
        let event = other.stepStarted(TestCourse.step(0, "preview"), sessionId: "m")
        var record = try RecordMapping.record(for: event)
        // A newer client's extra field, and a type this version doesn't know.
        let payload = #"{"futureField":[1,2],"sessionId":"m","stepId":"u00.l1.step-preview"}"#
        record.fields[RecordMapping.EventField.payload] = .bytes(Data(payload.utf8))
        var unknown = try RecordMapping.record(for: other.stepStarted(TestCourse.step(0, "story"), sessionId: "m"))
        unknown.fields[RecordMapping.EventField.type] = .string("streakFrozen")
        let bad = SyncRecord(recordType: .event, recordName: "not-a-uuid", fields: [:])
        let result = try await store.insertRemote(records: [record, unknown, bad])
        #expect(result.inserted.count == 2)
        #expect(try await store.eventRow(id: event.id)?.payload == payload)
        #expect(store.state.stepProgress(TestCourse.step(0, "preview"))?.isOpen == true)
        #expect(
            try await store.syncRecord(named: event.id)?.fields[RecordMapping.EventField.payload]
                == .bytes(Data(payload.utf8)))
        #expect(try await store.eventRow(id: unknown.recordName)?.type == "streakFrozen")
    }

    @Test func theFactoryContinuesAfterTheLastLocalEvent() async throws {
        let db = try TestLearnerDB()
        let store = try db.open()
        defer { try? store.close() }
        let first = try await store.makeEventFactory(packVersion: "0.1.0", ids: SeededUUIDSource(seed: "a"))
        let a = first.stepStarted(TestCourse.step(0, "preview"), sessionId: "s")
        try await store.append(a)
        // The clock didn't move (or went back): the next event still sorts after the stored one.
        let second = try await store.makeEventFactory(packVersion: "0.1.0", ids: SeededUUIDSource(seed: "b"))
        let b = second.stepCompleted(TestCourse.step(0, "preview"), sessionId: "s")
        #expect(b.at == a.at + 1)
        #expect(b.deviceId == store.deviceId)
        #expect(!(try await store.append(b)).rebuilt)
    }

    @Test func observersSeeEveryCommittedState() async throws {
        let db = try TestLearnerDB()
        let store = try db.open()
        defer { try? store.close() }
        var updates = store.states().makeAsyncIterator()
        #expect(await updates.next() == Replay.initialState(content: content))
        let event = factory(db, store).stepStarted(TestCourse.step(0, "preview"), sessionId: "s")
        let result = try await store.append(event)
        #expect(await updates.next() == result.state)
    }
}

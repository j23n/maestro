import Foundation
import GRDB
import LearningCore
import LearningCoreTestSupport
import Testing

@testable import Storage

/// docs/02 § Performance budgets: a full replay of 50,000 events in < 1.5 s on an iPhone (release build); M2.12
/// checks < 1.5 s on an M-series Mac and the device check is M9. This test measures the same work here (read every
/// row, decode, reduce, rewrite the derived tables and the checkpoint) and prints the timings. Its bound is
/// deliberately loose, for unoptimised builds on slow CI machines: it catches an accidental quadratic, not a miss
/// of the budget.
@Suite(.serialized) struct LearnerPerformanceTests {
    static let eventCount = 50_000

    @Test func fiftyThousandEventsRebuild() async throws {
        let events = SyntheticLearner.log(Self.eventCount)
        #expect(events.count == Self.eventCount)
        let attempts = events.filter { $0.type == "attempt" }.count
        let db = try TestLearnerDB()
        let store = try db.open()
        // Load the log as sync would have left it, without applying it event by event.
        try await store.pool.write { db in
            let insert = try db.cachedStatement(
                sql: """
                    INSERT INTO events (\(EventRow.columns)) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """)
            for event in events { try insert.execute(arguments: try EventRow(event).arguments) }
        }
        let clock = ContinuousClock()
        var state = LearnerState()
        let rebuild = try await clock.measure { state = try await store.rebuildAll() }
        let memoryOnly = clock.measure { _ = Replay.rebuildAll(events: events, content: TestCourse.standard) }
        try store.close()
        var reopened: LearnerStore?
        let open = try clock.measure { reopened = try db.open() }
        let appended = SyntheticLearner.log(Self.eventCount + 200).suffix(200)
        var perAppend = Duration.zero
        if let reopened {
            #expect(reopened.launchRebuild == nil)
            #expect(reopened.state == state)
            let started = clock.now
            for event in appended { try await reopened.append(event) }
            perAppend = (clock.now - started) / appended.count
            try reopened.close()
        }
        print(
            """
            [perf] \(Self.eventCount) events (\(attempts) attempts): rebuildAll \(rebuild) \
            (in-memory replay alone \(memoryOnly)); open from checkpoint \(open); append \(perAppend) per event \
            (\(state.memory.count) memory rows, \(state.exerciseHistory.count) exercises)
            """)
        #expect(rebuild < .seconds(60))
        #expect(open < .seconds(10))
    }
}

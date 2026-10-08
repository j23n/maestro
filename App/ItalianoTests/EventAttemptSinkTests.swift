import Foundation
import LearningCore
import Testing

@testable import Italiano

@MainActor
@Suite struct EventAttemptSinkTests {
    @Test func draftsBecomeAttemptEvents() throws {
        var written: [Event] = []
        let factory = EventFactory(deviceId: "dev-1", packVersion: "1", clock: FixedClock(ms: 1_000),
                                   ids: SeededUUIDSource(seed: "t"))
        let sink = EventAttemptSink(factory: factory, context: .lesson, sessionID: "s1", stepID: "u02.l1.s4") {
            written.append($0)
        }
        let m = try #require(MatchModel(payload: try PayloadFixtures.exercise("u02.l1.ex20"),
                                        env: .preview(), sink: sink))
        m.tapLeft(0)
        m.tapRight(1)
        m.tapLeft(0)
        m.tapRight(0)
        m.tapLeft(1)
        m.tapRight(1)
        let e = try #require(written.first)
        guard case .attempt(let a) = e.payload else {
            Issue.record("not an attempt: \(e.payload)")
            return
        }
        #expect(a.stepId == "u02.l1.s4" && a.sessionId == "s1" && a.context == .lesson)
        #expect(a.targets.map(\.outcome) == [.wrong, .correct])  // each pair keeps its own outcome
        #expect(a.mode == .tapped && e.deviceId == "dev-1" && e.at == 1_000)
    }
}

import Foundation
import Testing

@testable import LearningCore

/// docs/05 § Events: envelopes, payload JSON, unknown types, response caps and target rules.
@Suite struct EventCodecTests {
    func json(_ payload: EventPayload) throws -> String { try EventCodec.payloadString(payload) }

    @Test func attemptPayloadIsCamelCaseWithSortedKeys() throws {
        let payload = AttemptPayload(
            exerciseId: "u02.l1.ex20", turnId: "n1", format: .match, context: .lesson, stepId: "u02.l1.step-practice",
            sessionId: "s1", attemptIndex: 1, outcome: .wrong,
            targets: [AttemptTarget(itemId: "w:caffe", skill: .read, outcome: .correct)], response: "un caffè",
            mode: .tapped, latencyMs: 4200, feedbackShown: .hint)
        #expect(
            try json(.attempt(payload))
                == #"{"attemptIndex":1,"context":"lesson","exerciseId":"u02.l1.ex20","feedbackShown":"hint","#
                + #""format":"match","latencyMs":4200,"mode":"tapped","outcome":"wrong","response":"un caffè","#
                + #""sessionId":"s1","stepId":"u02.l1.step-practice","#
                + #""targets":[{"itemId":"w:caffe","outcome":"correct","skill":"read"}],"turnId":"n1"}"#
        )
    }

    @Test func optionalFieldsAreOmitted() throws {
        let payload = AttemptPayload(exerciseId: "gen:recall:w:cornetto", format: .recall, context: .review,
                                     sessionId: "s2", outcome: .correct, targets: [], mode: .typed)
        let text = try json(.attempt(payload))
        #expect(!text.contains("turnId"))
        #expect(!text.contains("stepId"))
        #expect(!text.contains("response"))
        #expect(
            try json(.introduced(IntroducedPayload(items: [.init(itemId: "w:oggi", skills: [.read, .listen])],
                                                   via: .preview)))
                == #"{"items":[{"itemId":"w:oggi","skills":["read","listen"]}],"via":"preview"}"#)
    }

    static let samples: [EventPayload] = [
        .introduced(IntroducedPayload(items: [.init(itemId: "w:caffe", skills: [.read, .listen, .recall])],
                                      via: .story, stepId: "u02.l1.step-story")),
        .attempt(AttemptPayload(exerciseId: "u02.task.conv1", turnId: "n2", format: .conversation, context: .check,
                                stepId: "u02.step-check", sessionId: "s", attemptIndex: 1, outcome: .correct,
                                targets: [], response: "un cornetto per favore", mode: .spoken, latencyMs: 900,
                                feedbackShown: .none)),
        .stepStarted(StepEventPayload(stepId: "u02.l1.step-story", sessionId: "s")),
        .stepCompleted(StepEventPayload(stepId: "u02.l1.step-story", sessionId: "s", durationMs: 120_000)),
        .glossTapped(GlossTappedPayload(textId: "u02.l1.story", line: 3, token: 2, itemId: "w:cornetto")),
        .audioPlayed(AudioPlayedPayload(audioId: "a:3f9c0e1a2b4d", textId: "u02.l1.story", rate: 0.8,
                                        playedMs: 31_000, context: .story)),
        .session(SessionPayload(sessionId: "s", kind: .review, platform: .iPad, startedAt: 1, endedAt: 2,
                                activeSeconds: 300)),
        .checkCompleted(CheckCompletedPayload(checkId: "u02.check", kind: .unit, sections: [
            .init(id: "listening", earned: 1.5, possible: 2),
            .init(id: "speaking", earned: 0, possible: 4, excluded: true),
        ], overall: 0.75, passed: true, canDosReached: ["cd:order-food-drink"])),
        .placementCompleted(PlacementCompletedPayload(startUnit: "u03", blocks: [
            .init(unit: "u01", correct: 5, total: 5), .init(unit: "u02", correct: 4.5, total: 5),
            .init(unit: "u03", correct: 2, total: 5),
        ])),
        .onboardingCompleted(OnboardingCompletedPayload(reason: "travel", forms: .f, country: "gb-wls",
                                                        beginner: false)),
    ]

    @Test(arguments: samples)
    func payloadsRoundTrip(_ payload: EventPayload) throws {
        let data = try EventCodec.encodePayload(payload)
        #expect(EventCodec.decodePayload(type: payload.typeName, json: data) == payload)
        #expect(try EventCodec.encodePayload(EventCodec.decodePayload(type: payload.typeName, json: data)) == data)
    }

    @Test func everyTypeHasASample() {
        #expect(Set(Self.samples.compactMap(\.eventType)) == Set(EventType.allCases))
    }

    @Test func envelopesRoundTripAndUseDocNames() throws {
        for (n, payload) in Self.samples.enumerated() {
            let event = Event(id: "6F1C0000-0000-4000-8000-00000000000\(n)", at: 1_791_360_000_000 + Int64(n),
                              tzOffsetMin: 120, deviceId: "ipad-1", packVersion: "0.1.0", payload: payload)
            #expect(event.id == event.id.lowercased())
            let data = try EventCodec.encodeEnvelope(event)
            let object = try #require(try JSONSerialization.jsonObject(with: data) as? [String: Any])
            #expect(Set(object.keys) == ["id", "at", "tzOffsetMin", "type", "deviceId", "schema", "packVersion",
                                         "payload", "origin"])
            #expect(object["type"] as? String == payload.typeName)
            #expect(object["schema"] as? Int == 1)
            #expect(try EventCodec.decodeEnvelope(data) == event)
        }
    }

    @Test func unknownTypesKeepTheirRawJSON() throws {
        let raw = Data(#"{"zeta":1,"alpha":{"b":[true,null]}}"#.utf8)
        let payload = EventCodec.decodePayload(type: "streakFrozen", json: raw)
        #expect(payload == .unknown(type: "streakFrozen", json: raw))
        #expect(try EventCodec.encodePayload(payload) == raw)
        #expect(payload.eventType == nil)
        #expect(payload.typeName == "streakFrozen")
        // Through an envelope (fixtures) the payload stays structurally the same.
        let event = Event(id: "00000000-0000-4000-8000-000000000001", at: 5, tzOffsetMin: 0, deviceId: "d",
                          packVersion: "0.1.0", payload: payload)
        let back = try EventCodec.decodeEnvelope(try EventCodec.encodeEnvelope(event))
        #expect(back.type == "streakFrozen")
        guard case .unknown(_, let json) = back.payload else {
            Issue.record("expected unknown")
            return
        }
        #expect(try JSONDecoder().decode(JSONValue.self, from: json) == JSONDecoder().decode(JSONValue.self, from: raw))
    }

    @Test func undecodablePayloadsOfKnownTypesBecomeUnknown() {
        let raw = Data(#"{"stepId":"u02.l1.step-story"}"#.utf8)  // sessionId missing
        #expect(EventCodec.decodePayload(type: "stepStarted", json: raw) == .unknown(type: "stepStarted", json: raw))
    }

    @Test func unknownKeysAreIgnored() {
        let raw = Data(#"{"stepId":"u02.l1.step-story","sessionId":"s","newField":42}"#.utf8)
        #expect(EventCodec.decodePayload(type: "stepStarted", json: raw)
                == .stepStarted(StepEventPayload(stepId: "u02.l1.step-story", sessionId: "s")))
    }

    @Test func eventKeyOrdersByTimeThenID() {
        let a = EventKey(at: 10, id: "b")
        let b = EventKey(at: 10, id: "c")
        let c = EventKey(at: 9, id: "z")
        #expect([a, b, c].sorted() == [c, a, b])
    }

    // MARK: Factory

    func factory(at: Int64 = mondayNine) -> (EventFactory, FixedClock) {
        let clock = FixedClock(ms: at, tzOffsetMinutes: 60)
        return (EventFactory(deviceId: "phone", packVersion: "0.1.0", clock: clock, ids: SeededUUIDSource(seed: "f")),
                clock)
    }

    @Test func factoryFillsTheEnvelope() {
        let (f, _) = factory()
        let e = f.stepStarted("u02.l1.step-story", sessionId: "s")
        #expect(e.at == mondayNine)
        #expect(e.tzOffsetMin == 60)
        #expect(e.deviceId == "phone")
        #expect(e.schema == 1)
        #expect(e.packVersion == "0.1.0")
        #expect(e.origin == .local)
        #expect(UUID(uuidString: e.id) != nil)
        #expect(e.type == "stepStarted")
    }

    @Test func factoryTimesStrictlyIncrease() {
        let (f, clock) = factory()
        let a = f.stepStarted("x", sessionId: "s")
        let b = f.stepCompleted("x", sessionId: "s")
        #expect(b.at == a.at + 1)
        clock.advance(byMs: -60_000)  // the device clock jumps back
        let c = f.stepStarted("y", sessionId: "s")
        #expect(c.at == b.at + 1)
        clock.advance(byMs: 120_000)
        #expect(f.stepStarted("z", sessionId: "s").at == clock.nowMs())
    }

    @Test func responsesAreCapped() {
        let long = String(repeating: "è", count: 2_500)
        #expect(EventFactory.cap(long, format: .recall)?.count == 200)
        #expect(EventFactory.cap(long, format: .conversation)?.count == 200)
        #expect(EventFactory.cap(long, format: .writing)?.count == 2_000)
        #expect(EventFactory.cap(long, format: .talk)?.count == 2_000)
        #expect(EventFactory.cap("short", format: .cloze) == "short")
        #expect(EventFactory.cap(nil, format: .cloze) == nil)
        let (f, _) = factory()
        let e = f.attempt(exerciseId: "u02.task.talk", format: .talk, context: .lesson, sessionId: "s",
                          outcome: .correct, targets: [], response: long, mode: .spoken, latencyMs: 1)
        guard case .attempt(let p) = e.payload else {
            Issue.record("expected an attempt")
            return
        }
        #expect(p.response?.count == 2_000)
    }

    @Test func targetsFollowTheFormatRules() {
        let cornetto = ItemSkillPair("w:cornetto", .recall)
        let caffe = ItemSkillPair("w:caffe", .read)
        let oggi = ItemSkillPair("w:oggi", .read)
        // Non-match: every target gets the exercise's outcome.
        #expect(EventFactory.attemptTargets(format: .cloze, mode: .typed, targets: [cornetto, caffe], outcome: .almost,
                                            pairOutcomes: nil).map(\.outcome) == [.almost, .almost])
        // Match: each pair's outcome goes to its target.
        #expect(EventFactory.attemptTargets(format: .match, mode: .tapped, targets: [caffe, oggi], outcome: .wrong,
                                            pairOutcomes: [.correct, .wrong]).map(\.outcome) == [.correct, .wrong])
        // Conversation turns carry no targets.
        #expect(EventFactory.attemptTargets(format: .conversation, mode: .spoken, targets: [cornetto],
                                            outcome: .correct, pairOutcomes: nil).isEmpty)
        // A recall answered by voice records its targets under speak (docs/06 § 7).
        #expect(EventFactory.attemptTargets(format: .recall, mode: .spoken, targets: [cornetto], outcome: .correct,
                                            pairOutcomes: nil).map(\.skill) == [.speak])
    }

    @Test func introducedPayloadGroupsPairsByItem() {
        let p = IntroducedPayload(pairs: [ItemSkillPair("w:b", .recall), ItemSkillPair("w:a", .listen),
                                          ItemSkillPair("w:b", .read)], via: .catchup)
        #expect(p.items == [.init(itemId: "w:a", skills: [.listen]), .init(itemId: "w:b", skills: [.read, .recall])])
        let (f, _) = factory()
        #expect(f.introduced([], via: .preview) == nil)
    }
}

import Foundation
import Testing

@testable import LearningCore

/// `fixtures/replay/*.json`: event logs with expected derived state (fixtures/README.md).
@Suite struct ReplayFixtureTests {
    let content = TestCourse.standard

    func load(_ name: String) throws -> [String: Any] {
        try #require(try Fixtures.json("fixtures/replay/\(name)") as? [String: Any])
    }

    func events(_ value: Any?) throws -> [Event] {
        let data = try JSONSerialization.data(withJSONObject: try #require(value))
        return try EventCodec.decodeLog(data)
    }

    func pair(_ key: String) -> ItemSkillPair {
        let parts = key.split(separator: "/").map(String.init)
        return ItemSkillPair(ItemID(parts[0]), Skill(rawValue: parts[1]) ?? .read)
    }

    @Test func resumeMidStep() throws {
        let fixture = try load("resume-mid-step.json")
        let stepId = StepID(try #require(fixture["step"] as? String))
        let step = try #require(content.step(stepId))
        // The fixture's order was computed independently (Python): Swift must agree.
        #expect(step.presentationOrder.map(\.rawValue) == fixture["presentationOrder"] as? [String])
        let log = try events(fixture["events"])
        for checkpoint in try #require(fixture["checkpoints"] as? [[String: Any]]) {
            let count = try #require(checkpoint["afterEvents"] as? Int)
            let state = Replay.rebuildAll(events: Array(log.prefix(count)), content: content)
            let progress = state.stepProgress(stepId)
            #expect(state.cursor(stepId) == checkpoint["cursor"] as? Int)
            #expect(Progression.resumeExercise(step: step, state: state)?.rawValue == checkpoint["resumeAt"] as? String)
            #expect(progress?.isOpen == checkpoint["open"] as? Bool)
            #expect(progress?.isComplete == checkpoint["completed"] as? Bool)
            #expect(Progression.shouldWriteStepStarted(stepId, state: state) == !(progress?.isOpen ?? false))
        }
    }

    @Test(arguments: 0..<25)
    func twoDevicesConvergeInAnyOrder(seed: Int) throws {
        let fixture = try load("two-devices.json")
        let devices = try #require(fixture["devices"] as? [String: Any])
        let ipad = try events(devices["ipad-1"])
        let iphone = try events(devices["iphone-1"])
        let reference = Replay.rebuildAll(events: ipad + iphone, content: content)

        // Each device starts with its own log, then receives the other's in a random order with duplicates.
        var rng = SplitMix64(seedString: "fixture-\(seed)")
        for (own, other) in [(ipad, iphone), (iphone, ipad)] {
            var log: [String: Event] = [:]
            MergeRules.insert(own, into: &log)
            var state = Replay.rebuildAll(events: own, content: content)
            let parcel = (other + other.filter { _ in rng.nextInt(below: 3) == 0 } + own.prefix(2))
                .seededShuffle(using: &rng)
            for chunk in stride(from: 0, to: parcel.count, by: 4) {
                let fresh = MergeRules.insert(Array(parcel[chunk..<min(chunk + 4, parcel.count)]), into: &log)
                if !Replay.applyIncremental(to: &state, events: fresh, content: content) {
                    state = Replay.rebuildAll(events: Array(log.values), content: content)
                }
            }
            #expect(try state.canonicalEncoding() == reference.canonicalEncoding())
        }
        if seed == 0 { try checkExpected(fixture, reference) }
    }

    func checkExpected(_ fixture: [String: Any], _ state: LearnerState) throws {
        let expected = try #require(fixture["expected"] as? [String: Any])
        for (key, value) in try #require(expected["introductions"] as? [String: [String: Any]]) {
            let intro = state.introductions[pair(key)]
            #expect(intro?.via.rawValue == value["via"] as? String, "\(key)")
            #expect(intro?.at == (value["at"] as? NSNumber)?.int64Value, "\(key)")
        }
        for (key, reps) in try #require(expected["memoryReps"] as? [String: Int]) {
            #expect((state.memory[pair(key)]?.reps ?? 0) == reps, "\(key)")
        }
        for (key, value) in try #require(expected["steps"] as? [String: [String: Any]]) {
            let progress = state.stepProgress(StepID(key))
            #expect(progress?.completedAt == (value["completedAt"] as? NSNumber)?.int64Value, "\(key)")
            #expect(progress?.isOpen == value["open"] as? Bool, "\(key)")
            #expect(progress?.cursor == value["cursor"] as? Int, "\(key)")
            if let open = value["openStartedAt"] as? NSNumber {
                #expect(progress?.openStartedAt == open.int64Value, "\(key)")
            }
        }
        for (key, value) in try #require(expected["units"] as? [String: String]) {
            #expect(state.unitState(UnitID(key)).rawValue == value, "\(key)")
        }
        for (key, value) in try #require(expected["days"] as? [String: [String: Int]]) {
            let day = try #require(state.dailyActivity.values.first { $0.localDay == key })
            #expect(day.activeSeconds == value["activeSeconds"])
            #expect(day.stepsCompleted == value["stepsCompleted"])
            #expect(day.cardsReviewed == value["cardsReviewed"])
        }
        #expect(state.lastApplied?.id == expected["lastApplied"] as? String)
    }
}

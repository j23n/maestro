import Foundation
import Testing

@testable import LearningCore

/// One simulated device: its own clock (skewed), time zone, event log keyed by ID, and replayed state. Local and
/// remote events both go through the incremental path, rebuilding when an event sorts before the last applied one.
final class SimDevice {
    let content: ContentIndex
    let clock: FixedClock
    let factory: EventFactory
    let platform: Platform
    var rng: SplitMix64
    var log: [String: Event] = [:]
    var state: LearnerState
    var rebuilds = 0
    /// This device's clock error against real time.
    let skew: Int64

    init(name: String, seed: String, content: ContentIndex, start: Int64, tz: Int, platform: Platform,
         skew: Int64 = 0)
    {
        self.content = content
        self.skew = skew
        self.clock = FixedClock(ms: start + skew, tzOffsetMinutes: tz)
        self.factory = EventFactory(deviceId: name, packVersion: content.packVersion, clock: clock,
                                    ids: SeededUUIDSource(seed: "\(seed)/\(name)"))
        self.platform = platform
        self.rng = SplitMix64(seedString: "\(seed)/\(name)/actions")
        self.state = Replay.initialState(content: content)
    }

    /// Remote events: dedupe by ID (merge rules), then the incremental path or a rebuild.
    func apply(_ events: [Event]) {
        let fresh = MergeRules.insert(events, into: &log)
        guard !fresh.isEmpty else { return }
        if !Replay.applyIncremental(to: &state, events: fresh, content: content) {
            rebuilds += 1
            state = Replay.rebuildAll(events: Array(log.values), content: content)
        }
    }

    /// A local event. After a sync it may still sort before a remote event (clock skew): then it rebuilds too.
    func record(_ event: Event?) {
        guard let event else { return }
        log[event.id] = event
        if !Replay.applyIncremental(to: &state, events: [event], content: content) {
            rebuilds += 1
            state = Replay.rebuildAll(events: Array(log.values), content: content)
        }
    }

    var localEvents: [Event] { log.values.filter { $0.deviceId == factory.deviceId } }

    func pick<T>(_ options: [T]) -> T? { options.isEmpty ? nil : options[rng.nextInt(below: options.count)] }
    func chance(_ percent: Int) -> Bool { rng.nextInt(below: 100) < percent }

    func outcome() -> AttemptOutcome {
        pick([.correct, .correct, .correct, .correctWithNote, .almost, .wrong, .wrong, .revealed, .skipped]) ?? .correct
    }

    /// One thing a learner does on this device at real time `now`, chosen from its own current state.
    func act(at now: Int64, sessionPrefix: String) {
        clock.set(ms: now + skew)
        act(sessionPrefix: sessionPrefix)
    }

    /// One thing a learner does on this device, chosen from its own current state.
    func act(sessionPrefix: String) {
        let roll = rng.nextInt(below: 100)
        let session = "\(sessionPrefix)-\(factory.deviceId)-\(rng.nextInt(below: 1_000_000))"
        switch roll {
        case 0..<45: lesson(session)
        case 45..<65: review(session)
        case 65..<75:
            record(factory.session(sessionId: session, kind: .lesson, platform: platform, startedAt: clock.nowMs(),
                                   endedAt: clock.nowMs(), activeSeconds: rng.nextInt(below: 900)))
        case 75..<80:
            record(factory.glossTapped(textId: "u00.l1.story", line: 1, token: 2, itemId: TestCourse.noun(0, 1)))
        case 80..<84: record(factory.make(.unknown(type: "fromTheFuture", json: Data(#"{"a":1}"#.utf8))))
        case 84..<88:
            record(factory.attempt(exerciseId: "u00.l1.ex99", format: .recall, context: .lesson, sessionId: session,
                                   outcome: outcome(), targets: [ItemSkillPair(TestCourse.noun(0, 2), .recall),
                                                                 ItemSkillPair("w:retired", .recall)],
                                   mode: .typed, latencyMs: 100))
        case 88..<91:
            let start = pick(content.units.map(\.id)) ?? "u00"
            record(factory.placementCompleted(PlacementCompletedPayload(startUnit: start, blocks: [])))
            if let payload = Introductions.placementPayload(startUnit: start, content: content) {
                record(factory.introduced(payload))
            }
        default:
            if let step = pick(content.steps) {
                let entry = Eligibility.enter(step, state: state, content: content)
                record(entry.catchupPayload.flatMap { factory.introduced($0) })
            }
        }
    }

    func lesson(_ session: String) {
        guard let point = Progression.continuePoint(state: state, content: content),
            let step = content.step(point.stepId)
        else { return }
        if Progression.shouldWriteStepStarted(step.id, state: state) {
            record(factory.stepStarted(step.id, sessionId: session))
        }
        let entry = Eligibility.enter(step, state: state, content: content)
        record(entry.introducedPayload.flatMap { factory.introduced($0) })
        record(entry.catchupPayload.flatMap { factory.introduced($0) })
        if step.kind == .check, let check = step.checkId.flatMap({ content.check($0) }) {
            var answers: [ExerciseID: CheckAnswer] = [:]
            for id in check.exerciseIds {
                guard let exercise = content.exercise(id) else { continue }
                let result = outcome()
                answers[id] = .outcome(result)
                record(factory.attempt(exerciseId: id, format: exercise.format, context: .check, stepId: step.id,
                                       sessionId: session, outcome: result, targets: exercise.targets,
                                       mode: exercise.format.family == .tapped ? .tapped : .typed, latencyMs: 500))
            }
            let excluded: Set<String> = chance(20) ? ["speaking"] : []
            let result = CheckScoring.score(check: check, answers: answers, excludedSections: excluded,
                                            content: content)
            record(factory.checkCompleted(result.payload))
            record(factory.stepCompleted(step.id, sessionId: session))
            return
        }
        let order = step.presentationOrder
        var index = state.cursor(step.id)
        for _ in 0..<(1 + rng.nextInt(below: 4)) where index < order.count {
            guard let exercise = content.exercise(order[index]) else { break }
            let mode: AnswerMode = exercise.format == .repeat ? .spoken : exercise.format.family == .tapped ? .tapped
                : (exercise.format == .recall && chance(20) ? .spoken : .typed)
            let first = outcome()
            record(factory.attempt(exerciseId: exercise.id, format: exercise.format, context: .lesson,
                                   stepId: step.id, sessionId: session, outcome: first, targets: exercise.targets,
                                   pairOutcomes: exercise.format == .match
                                       ? exercise.targets.map { _ in chance(70) ? .correct : .wrong } : nil,
                                   mode: mode, latencyMs: 1_000))
            if !first.isFinal {
                record(factory.attempt(exerciseId: exercise.id, format: exercise.format, context: .lesson,
                                       stepId: step.id, sessionId: session, attemptIndex: 2, outcome: outcome(),
                                       targets: exercise.targets, mode: mode, latencyMs: 1_000))
            }
            index += 1
        }
        if index >= order.count || chance(25) { record(factory.stepCompleted(step.id, sessionId: session)) }
    }

    func review(_ session: String) {
        let builder = ReviewSessionBuilder(content: content, state: state, sessionTarget: 6)
        var built = chance(30)
            ? builder.buildCatchUp(sessionId: session, now: clock.nowMs(), tzOffsetMinutes: clock.tzOffsetMinutes())
            : builder.build(sessionId: session, now: clock.nowMs(), tzOffsetMinutes: clock.tzOffsetMinutes())
        var index = 0
        while index < built.cards.count {
            let card = built.cards[index]
            let result = outcome()
            let mode: AnswerMode = card.format.family == .tapped ? .tapped : .typed
            record(factory.attempt(exerciseId: card.exerciseId, format: card.format, context: .review,
                                   sessionId: session, outcome: result, targets: [card.pair], mode: mode,
                                   latencyMs: 2_000))
            builder.requeueIfNeeded(&built, cardIndex: index, outcome: result, mode: mode, now: clock.nowMs())
            index += 1
        }
        record(factory.session(sessionId: session, kind: .review, platform: platform, startedAt: clock.nowMs(),
                               endedAt: clock.nowMs(), activeSeconds: 10 * built.cards.count))
    }
}

/// docs/08 § Tests 1 and M7.1: devices create events offline, then exchange them in random orders and with
/// duplicates; the derived states (memory, introductions, unit progress, daily activity — the whole state) must be
/// byte-identical on every device, for 1,000 seeded runs.
@Suite struct MultiDeviceSimulationTests {
    static let content = TestCourse.small

    /// Delivers `events` to `device` shuffled, with duplicates, in one to three batches.
    static func deliver(_ events: [Event], to device: SimDevice, rng: inout SplitMix64) {
        var parcel = events + events.filter { _ in rng.nextInt(below: 4) == 0 }
        parcel = parcel.seededShuffle(using: &rng)
        let batches = 1 + rng.nextInt(below: 3)
        let size = max(1, (parcel.count + batches - 1) / batches)
        while !parcel.isEmpty {
            device.apply(Array(parcel.prefix(size)))
            parcel.removeFirst(min(size, parcel.count))
        }
    }

    struct Outcome {
        var events: Int
        var rebuilds: Int
        var unitsTouched: Bool
        var memoryPairs: Int
    }

    static func run(seed: Int, deviceCount: Int, actions: Int = 4) throws -> Outcome {
        let platforms: [Platform] = [.iPhone, .iPad, .Mac]
        let zones = [0, 120, -300]
        var rng = SplitMix64(seedString: "sim-\(seed)")
        var now = mondayNine + Int64(seed % 7) * day
        let devices = (0..<deviceCount).map { i in
            SimDevice(name: "device-\(i)", seed: "sim-\(seed)", content: content, start: now, tz: zones[i],
                      platform: platforms[i], skew: Int64(rng.nextInt(below: 21) - 10) * minute)
        }
        // One real timeline; the learner picks up whichever device, which may be offline.
        func round(_ name: String) {
            for _ in 0..<(actions * deviceCount) {
                now += Int64(rng.nextInt(below: 120)) * minute + (rng.nextInt(below: 8) == 0 ? day : 0)
                devices[rng.nextInt(below: deviceCount)].act(at: now, sessionPrefix: name)
            }
        }
        round("r1")
        // A partial exchange: some devices hear some of the others' events.
        for device in devices where rng.nextInt(below: 2) == 0 {
            let others = devices.filter { $0 !== device }.flatMap(\.localEvents)
                .filter { _ in rng.nextInt(below: 2) == 0 }
            deliver(others, to: device, rng: &rng)
        }
        round("r2")
        // Full exchange.
        let all = devices.flatMap(\.localEvents)
        for device in devices { deliver(all, to: device, rng: &rng) }

        let reference = Replay.rebuildAll(events: all, content: content)
        let referenceBytes = try reference.canonicalEncoding()
        for device in devices {
            #expect(device.log.count == all.count)
            let bytes = try device.state.canonicalEncoding()
            if bytes != referenceBytes {
                Issue.record("seed \(seed): \(device.factory.deviceId) diverged")
                #expect(device.state.memory == reference.memory)
                #expect(device.state.introductions == reference.introductions)
                #expect(device.state.units == reference.units)
                #expect(device.state.dailyActivity == reference.dailyActivity)
            }
        }
        return Outcome(events: all.count, rebuilds: devices.map(\.rebuilds).reduce(0, +),
                       unitsTouched: reference.units.values.contains { $0.state != .locked && $0.state != .available },
                       memoryPairs: reference.memory.count)
    }

    /// 1,000 runs in 10 chunks of 100 seeds (the chunks run in parallel); even seeds use two devices, odd three.
    @Test(arguments: 0..<10)
    func thousandSeededRunsConverge(chunk: Int) throws {
        var events = 0
        var rebuilds = 0
        var touched = 0
        var memory = 0
        for seed in (chunk * 100)..<(chunk * 100 + 100) {
            let outcome = try Self.run(seed: seed, deviceCount: seed % 2 == 0 ? 2 : 3)
            events += outcome.events
            rebuilds += outcome.rebuilds
            touched += outcome.unitsTouched ? 1 : 0
            memory += outcome.memoryPairs
        }
        // The runs really exercise late events, unit progress and memory.
        #expect(events > 3_000, "\(events) events")
        #expect(rebuilds > 200, "\(rebuilds) rebuilds")
        #expect(touched > 40, "\(touched) runs moved a unit")
        #expect(memory > 500, "\(memory) memory pairs")
    }
}

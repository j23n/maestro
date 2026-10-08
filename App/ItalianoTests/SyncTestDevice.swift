import Foundation
import LearningCore
import Storage

@testable import Italiano

/// A tiny course for the sync tests: one step introducing four words, a recall exercise each, so attempts move
/// FSRS memory and arrival order matters to replay.
enum SyncTestCourse {
    static let unit = UnitID("u00")
    static let lesson = LessonID("u00.l1")
    static let step = StepID("u00.l1.s1")
    static let items: [ItemID] = (1...4).map { ItemID("w:u00-n\($0)") }
    static let exercises: [ExerciseID] = (1...4).map { ExerciseID("u00.l1.ex0\($0)") }
    static let pairs = items.map { ItemSkillPair($0, .recall) }

    static let content = ContentIndex(
        packVersion: "0.7.0", contentHash: "sync-tests", units: [.init(id: unit, ord: 0)],
        lessons: [.init(id: lesson, unitId: unit, ord: 1)],
        steps: [
            .init(
                id: step, unitId: unit, lessonId: lesson, ord: 1, kind: .preview, exerciseIds: exercises,
                introduces: pairs)
        ],
        items: items.enumerated().map { index, id in
            .init(
                id: id, it: "n\(index + 1)", gloss: "thing \(index + 1)", unitId: unit, lessonId: lesson,
                skills: [.recall: .init(status: .P, scheduled: true)])
        },
        exercises: zip(exercises, pairs).map { id, pair in
            .init(id: id, format: .recall, unitId: unit, stepId: step, targets: [pair])
        })
}

/// One simulated device: a learner store in its own folder, its iCloud (`FakeICloud`) and a `SyncDriver`, with
/// helpers to act like a learner and to kill and relaunch the app.
final class SyncTestDevice {
    let name: String
    let platform: Platform
    let folder: URL
    let url: URL
    let clock: FixedClock
    let icloud: FakeICloud
    let box: StoreBox
    let logs = LogLines()
    let insertBatchLimit: Int
    private(set) var driver: SyncDriver
    private var factory: (store: ObjectIdentifier, factory: EventFactory)?
    private var sessions = 0

    init(
        _ name: String, platform: Platform = .iPhone, account: FakeICloud.Account?, start: Int64 = 1_767_603_600_000,
        fetchBatch: Int = 3, sendBatch: Int = 4, insertBatchLimit: Int = 2_000
    ) throws {
        self.name = name
        self.platform = platform
        folder = FileManager.default.temporaryDirectory
            .appendingPathComponent("italiano-sync-\(name)-\(UUID().uuidString)", isDirectory: true)
        url = folder.appendingPathComponent(LearnerStore.fileName)
        clock = FixedClock(ms: start, tzOffsetMinutes: 60)
        self.insertBatchLimit = insertBatchLimit
        let store = try LearnerStore(
            url: url, content: SyncTestCourse.content, clock: clock, ids: SeededUUIDSource(seed: name))
        box = StoreBox(store)
        icloud = FakeICloud(account: account, fetchBatch: fetchBatch, sendBatch: sendBatch, seed: name)
        driver = Self.makeDriver(
            box: box, icloud: icloud, clock: clock, platform: platform, logs: logs, name: name,
            insertBatchLimit: insertBatchLimit)
    }

    static func makeDriver(
        box: StoreBox, icloud: FakeICloud, clock: FixedClock, platform: Platform, logs: LogLines, name: String,
        insertBatchLimit: Int
    ) -> SyncDriver {
        let opener: SyncDriver.StoreOpener = { url in
            try LearnerStore(
                url: url, content: SyncTestCourse.content, clock: clock, ids: SeededUUIDSource(seed: "\(name)/fresh"))
        }
        return SyncDriver(
            store: box.store, factory: icloud,
            configuration: .init(platform: platform, insertBatchLimit: insertBatchLimit), clock: clock,
            logger: logs, openStore: opener, onStoreReplaced: { box.replace($0) })
    }

    var store: LearnerStore { box.store }
    var engine: FakeEngine? { icloud.engine }
    var cloud: FakeCloud? { icloud.account?.cloud }

    /// The app is killed: the engine stops mid-air, nothing else is saved, and the app launches again on the same
    /// file with a new driver (not started).
    func relaunch() throws {
        for engine in icloud.engines { engine.discard() }
        try store.close()
        box.replace(
            try LearnerStore(
                url: url, content: SyncTestCourse.content, clock: clock, ids: SeededUUIDSource(seed: name)))
        driver = Self.makeDriver(
            box: box, icloud: icloud, clock: clock, platform: platform, logs: logs, name: name,
            insertBatchLimit: insertBatchLimit)
    }

    func snapshot() async -> SyncSnapshot? {
        var iterator = await driver.snapshots().makeAsyncIterator()
        return await iterator.next()
    }

    // MARK: Acting like a learner

    func events() async throws -> EventFactory {
        let store = store
        if let factory, factory.store == ObjectIdentifier(store) { return factory.factory }
        let made = try await store.makeEventFactory(
            packVersion: SyncTestCourse.content.packVersion, ids: SeededUUIDSource(seed: "\(name)/\(store.deviceId)"))
        factory = (ObjectIdentifier(store), made)
        return made
    }

    @discardableResult
    func gloss() async throws -> Event {
        clock.advance(byMs: 1_000)
        let event = try await events().glossTapped(
            textId: TextID("u00.l1.story"), line: 1, token: 2, itemId: SyncTestCourse.items[0])
        try await store.append(event)
        return event
    }

    /// A short lesson: introduce the words, answer each exercise, and end the session with this device's platform.
    @discardableResult
    func lesson(outcomes: [AttemptOutcome]) async throws -> [Event] {
        let factory = try await events()
        sessions += 1
        let session = "\(name)-session-\(sessions)"
        clock.advance(byMs: 60_000)
        let started = clock.nowMs()
        var log: [Event] = [factory.stepStarted(SyncTestCourse.step, sessionId: session)]
        if let introduced = factory.introduced(SyncTestCourse.pairs, via: .preview, stepId: SyncTestCourse.step) {
            log.append(introduced)
        }
        for (index, outcome) in outcomes.enumerated() {
            clock.advance(byMs: 4_000)
            let i = index % SyncTestCourse.exercises.count
            log.append(
                factory.attempt(
                    exerciseId: SyncTestCourse.exercises[i], format: .recall, context: .lesson,
                    stepId: SyncTestCourse.step, sessionId: session, outcome: outcome,
                    targets: [SyncTestCourse.pairs[i]], response: "answer \(index)", mode: .typed, latencyMs: 2_000))
        }
        log.append(
            factory.session(
                sessionId: session, kind: .lesson, platform: platform, startedAt: started, endedAt: clock.nowMs(),
                activeSeconds: Int((clock.nowMs() - started) / 1000)))
        try await store.append(log)
        return log
    }

    @discardableResult
    func set(_ key: SettingKey, _ value: JSONValue) async throws -> SettingRecord {
        clock.advance(byMs: 1_000)
        return try await store.set(key, to: value)
    }

    // MARK: Sync helpers

    var pendingNames: Set<String> {
        get async throws { Set(try await store.pendingChanges().map(\.recordName)) }
    }

    /// Waits until the engine lists every `sync_pending` row (the driver hands new ones over on its own task).
    func settle() async throws -> Bool {
        guard let engine else { return true }
        return await eventually {
            let pending = (try? await self.pendingNames) ?? []
            return pending.isSubset(of: Set(engine.pendingSaves))
        }
    }

    /// Waits for the handover, then fetches and sends.
    func sync() async throws {
        _ = try await settle()
        await driver.syncNow()
    }
}

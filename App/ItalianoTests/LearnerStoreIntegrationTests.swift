import Foundation
import LearningCore
import Storage
import Testing

@testable import Italiano

/// The App's seams onto the real learner store (M2.12): attempt events from the exercise sink are appended in
/// order, and the telemetry uploader reads and marks the store's events. Runs on Linux too
/// (scripts/check-app-logic.sh --test).
@MainActor
@Suite struct LearnerStoreIntegrationTests {
    let content = ContentIndex(packVersion: "0.6.0", contentHash: "h", units: [.init(id: "u00", ord: 0)])

    func openStore() throws -> LearnerStore {
        let folder = FileManager.default.temporaryDirectory
            .appendingPathComponent("italiano-app-tests-\(UUID().uuidString)", isDirectory: true)
        return try LearnerStore(
            url: folder.appendingPathComponent(LearnerStore.fileName), content: content,
            clock: FixedClock(ms: 5_000, tzOffsetMinutes: 120), ids: SeededUUIDSource(seed: "app"))
    }

    func draft(_ id: ExerciseID, format: ExerciseFormat, response: String?) -> AttemptDraft {
        AttemptDraft(
            exerciseID: id, turnID: nil, format: format, attemptIndex: 1, outcome: .correct, targets: [],
            response: response, mode: .typed, latencyMs: 900, feedbackShown: .none)
    }

    @Test func sinkAttemptsReachTheStoreInOrder() async throws {
        let store = try openStore()
        defer { try? store.close() }
        let factory = try await store.makeEventFactory(packVersion: "0.6.0", ids: SeededUUIDSource(seed: "sink"))
        let sink = EventAttemptSink(factory: factory, context: .lesson, sessionID: "s1") { store.enqueueAppend($0) }
        for n in 1...5 {
            sink.record(draft(ExerciseID("u00.l1.ex0\(n)"), format: .recall, response: "risposta \(n)"))
        }
        try await store.checkpoint()  // waits behind the queued appends (one writer queue)
        let events = try await store.events()
        #expect(events.count == 5)
        #expect(events.map(\.deviceId).allSatisfy { $0 == store.deviceId })
        #expect(try await store.pendingChanges().count == 5)
    }

    @Test func theUploaderSendsStoredLocalEventsOnceAndMarksThem() async throws {
        let store = try openStore()
        defer { try? store.close() }
        let factory = try await store.makeEventFactory(packVersion: "0.6.0", ids: SeededUUIDSource(seed: "tel"))
        let talk = factory.attempt(
            exerciseId: "u00.task.talk", format: .talk, context: .lesson, sessionId: "s",
            outcome: .correct, targets: [], response: "free text", mode: .typed, latencyMs: 1)
        let gloss = factory.glossTapped(textId: "u00.l1.story", line: 1, token: 2, itemId: nil)
        try await store.append([talk, gloss])
        let remote = EventFactory(
            deviceId: "pad", packVersion: "0.6.0", clock: FixedClock(ms: 6_000),
            ids: SeededUUIDSource(seed: "pad")
        )
        .glossTapped(textId: "u00.l1.story", line: 1, token: 3, itemId: nil)
        try await store.insertRemote([remote])

        let server = TelemetryUploaderTests.Server([200])
        let uploader = TelemetryUploader(
            endpoint: URL(string: "https://study.example.org"), token: "tok",
            source: store, transport: server, newBatchID: { "batch-1" },
            now: { 9_000 })
        let consent = StudyConsent(version: "1", date: 1_000, granted: true)
        let app = TelemetryUploaderTests.app
        #expect(
            await uploader.uploadPending(consent: consent, installID: "i", app: app) == .sent(events: 2, batches: 1))
        let body = try #require(server.bodies().first)
        let sent = try #require(body["events"] as? [[String: Any]])
        #expect(sent.compactMap { $0["id"] as? String } == [talk.id, gloss.id])
        #expect((sent.first?["payload"] as? [String: Any])?["response"] == nil)
        #expect(await uploader.uploadPending(consent: consent, installID: "i", app: app) == .nothingToSend)
        #expect(try await store.unsentTelemetryEvents(since: 0, limit: 10).isEmpty)
    }
}

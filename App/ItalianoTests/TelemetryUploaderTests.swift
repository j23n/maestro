import Foundation
import LearningCore
import Testing

@testable import Italiano

/// M6.5: the uploader against a mock server (docs/12). Runs on Linux too (scripts/check-app-logic.sh --test).
@Suite struct TelemetryUploaderTests {
    final class Source: TelemetryEventSource, @unchecked Sendable {
        // @unchecked: test double, state guarded by `lock`.
        let lock = NSLock()
        var events: [StoredEvent]
        var sent: [String: String] = [:]  // event id → batch id

        init(_ events: [StoredEvent]) { self.events = events }

        func unsentLocalEvents(since: Int64, limit: Int) async throws -> [StoredEvent] {
            lock.withLock {
                Array(
                    events.filter { $0.isLocal && $0.at >= since && sent[$0.id] == nil }
                        .sorted { ($0.at, $0.id) < ($1.at, $1.id) }.prefix(limit))
            }
        }

        func markSent(eventIDs: [String], batchID: String, at: Int64) async throws {
            lock.withLock { for id in eventIDs { sent[id] = batchID } }
        }
    }

    final class Server: HTTPTransport, @unchecked Sendable {
        let lock = NSLock()
        var statuses: [Int]
        var requests: [HTTPRequestSpec] = []
        var failNetwork = false

        init(_ statuses: [Int]) { self.statuses = statuses }

        func send(_ request: HTTPRequestSpec) async throws -> Int {
            try lock.withLock {
                requests.append(request)
                if failNetwork { throw URLError(.notConnectedToInternet) }
                return statuses.isEmpty ? 200 : statuses.removeFirst()
            }
        }

        func bodies() -> [[String: Any]] {
            lock.withLock {
                requests.compactMap {
                    $0.body.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
                }
            }
        }
    }

    static let app = TelemetryAppInfo(
        version: "0.9.0", build: "57", pack: "0.6.0", platform: "iOS", os: "26",
        deviceClass: "phone")
    static let consent = StudyConsent(version: "1", date: 1_000, granted: true)

    static func event(
        _ i: Int, at: Int64 = 2_000, type: String = "attempt", local: Bool = true,
        payload: String = #"{"exerciseId":"u02.l1.ex04","format":"recall","mode":"typed","response":"un cornetto"}"#
    )
        -> StoredEvent
    {
        StoredEvent(
            id: String(format: "00000000-0000-4000-8000-%012d", i), at: at + Int64(i), tzOffsetMin: 120,
            type: type, schema: 1, packVersion: "0.6.0", payloadJSON: payload, isLocal: local)
    }

    func uploader(_ source: Source, _ server: Server, now: Int64 = 10_000) -> TelemetryUploader {
        let counter = Counter()
        return TelemetryUploader(
            endpoint: URL(string: "https://study.example.org"), token: "tok", source: source, transport: server,
            newBatchID: { "batch-\(counter.next())" }, now: { now })
    }

    final class Counter: @unchecked Sendable {
        let lock = NSLock()
        var n = 0
        func next() -> Int {
            lock.withLock {
                n += 1
                return n
            }
        }
    }

    @Test func nothingIsSentWithoutConsent() async {
        let server = Server([])
        let up = uploader(Source([Self.event(1)]), server)
        #expect(await up.uploadPending(consent: nil, installID: "i", app: Self.app) == .notAllowed)
        let off = StudyConsent(version: "1", date: 0, granted: false)
        #expect(await up.uploadPending(consent: off, installID: "i", app: Self.app) == .notAllowed)
        #expect(server.requests.isEmpty)
        let noEndpoint = TelemetryUploader(
            endpoint: nil, token: "t", source: Source([Self.event(1)]), transport: server,
            newBatchID: { "b" }, now: { 0 })
        #expect(await noEndpoint.uploadPending(consent: Self.consent, installID: "i", app: Self.app) == .notAllowed)
    }

    @Test func batchesOfAtMost500LocalEventsFromTheConsentDate() async {
        var events = (0..<1_203).map { Self.event($0) }
        events.append(Self.event(5_000, at: -10_000))  // before consent
        events.append(Self.event(5_001, local: false))  // synced from another device
        let source = Source(events)
        let server = Server([])
        let outcome = await uploader(source, server).uploadPending(
            consent: Self.consent, installID: "inst", app: Self.app)
        #expect(outcome == .sent(events: 1_203, batches: 3))
        let bodies = server.bodies()
        #expect(bodies.map { ($0["events"] as? [Any])?.count ?? -1 } == [500, 500, 203])
        #expect(source.sent.count == 1_203)
        #expect(source.sent[Self.event(5_000, at: -10_000).id] == nil)
        #expect(server.requests[0].url.absoluteString == "https://study.example.org/v1/batches")
        #expect(server.requests[0].headers["Authorization"] == "Bearer tok")
        #expect(bodies[0]["installId"] as? String == "inst")
        #expect((bodies[0]["app"] as? [String: Any])?["deviceClass"] as? String == "phone")
    }

    @Test func clientErrorsAreMarkedSentAndNeverRetried() async {
        let source = Source([Self.event(1), Self.event(2)])
        let server = Server([422])
        let outcome = await uploader(source, server).uploadPending(consent: Self.consent, installID: "i", app: Self.app)
        #expect(outcome == .sent(events: 2, batches: 1))
        #expect(source.sent.count == 2)
    }

    @Test func serverErrorsAndNetworkFailuresBackOffExponentially() async {
        let source = Source([Self.event(1)])
        let server = Server([503])
        let up = uploader(source, server)
        #expect(
            await up.uploadPending(consent: Self.consent, installID: "i", app: Self.app)
                == .retryLater(afterSeconds: 60))
        #expect(source.sent.isEmpty)
        // still inside the backoff window: no request is made
        #expect(
            await up.uploadPending(consent: Self.consent, installID: "i", app: Self.app)
                == .retryLater(afterSeconds: 60))
        #expect(server.requests.count == 1)
        #expect(TelemetryUploader.backoffSeconds(failures: 2) == 120)
        #expect(TelemetryUploader.backoffSeconds(failures: 30) == 6 * 3600)
        server.failNetwork = true
        let later = uploader(source, server, now: 1_000_000)
        #expect(
            await later.uploadPending(consent: Self.consent, installID: "i", app: Self.app)
                == .retryLater(afterSeconds: 60))
    }

    @Test func privateTextNeverLeavesTheDevice() {
        func payload(_ type: String, _ json: String) -> [String: Any] {
            TelemetryPrivacy.sanitizedPayload(type: type, payloadJSON: json) as? [String: Any] ?? [:]
        }
        let writing = payload("attempt", #"{"format":"writing","mode":"typed","response":"Cara Sara…"}"#)
        #expect(writing["response"] == nil)
        #expect(payload("attempt", #"{"format":"talk","mode":"spoken","response":"buongiorno"}"#)["response"] == nil)
        #expect(payload("attempt", #"{"format":"recall","mode":"spoken","response":"vorrei"}"#)["response"] == nil)
        #expect(
            payload("attempt", #"{"format":"recall","mode":"typed","response":"vorrei"}"#)["response"] as? String
                == "vorrei")
        let long = String(repeating: "a", count: 300)
        #expect(
            (payload("attempt", #"{"format":"cloze","mode":"typed","response":"\#(long)"}"#)["response"] as? String)?
                .count == 200)
        let onboarding = payload(
            "onboardingCompleted", #"{"reason":"travel","forms":"m","country":"us","beginner":true}"#)
        #expect(Set(onboarding.keys) == ["reason", "beginner"])
    }

    @Test func unknownEventTypesStayLocal() {
        let body = TelemetryUploader.batchBody(
            installID: "i", app: Self.app,
            events: [Self.event(1, type: "somethingNew"), Self.event(2)])
        let json = (try? JSONSerialization.jsonObject(with: body)) as? [String: Any]
        #expect((json?["events"] as? [Any])?.count == 1)
    }

    @Test func deletingStudyData() async {
        let server = Server([200])
        let ok = await uploader(Source([]), server).deleteStudyData(installID: "6f1c")
        #expect(ok)
        #expect(server.requests.first?.method == "DELETE")
        #expect(server.requests.first?.url.absoluteString == "https://study.example.org/v1/installs/6f1c")
    }
}

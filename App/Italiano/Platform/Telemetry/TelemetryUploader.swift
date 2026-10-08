import Foundation
import LearningCore

// Study telemetry (docs/12, ADR-11, task M6.5). Opt-in, study builds only, pseudonymous install ID, batches of
// ≤ 500 events from the consent date on, local-origin events only, and nothing a participant didn't consent to:
// free text from talk and writing, spoken answers and the onboarding country never leave the device.
// Platform-neutral: the HTTP transport and the event source are protocols (URLSession and LearnerStore adapters).

/// One stored event as the learner DB holds it (docs/03 `events`).
struct StoredEvent: Sendable, Equatable {
    let id: String
    let at: Int64
    let tzOffsetMin: Int
    let type: String
    let schema: Int
    let packVersion: String
    let payloadJSON: String
    let isLocal: Bool
}

/// `app` in the batch body (docs/12 § The endpoint contract).
struct TelemetryAppInfo: Codable, Sendable, Equatable {
    let version: String
    let build: String
    let pack: String
    let platform: String  // iOS | iPadOS | macOS
    let os: String  // major version only
    let deviceClass: String  // phone | tablet | mac
}

/// Where the uploader reads pending events and records what was sent (`telemetry_sent`, never synced).
protocol TelemetryEventSource: Sendable {
    /// Local-origin events with `at ≥ since` that have no `telemetry_sent` row, oldest first (by at, id).
    func unsentLocalEvents(since: Int64, limit: Int) async throws -> [StoredEvent]
    func markSent(eventIDs: [String], batchID: String, at: Int64) async throws
}

struct HTTPRequestSpec: Sendable, Equatable {
    let method: String
    let url: URL
    let headers: [String: String]
    let body: Data?
}

protocol HTTPTransport: Sendable {
    /// Returns the status code; throws on network errors.
    func send(_ request: HTTPRequestSpec) async throws -> Int
}

enum TelemetryPrivacy {
    static let closedResponseLimit = 200

    /// docs/12 § What is uploaded: strip `response` from talk, writing and every spoken answer (closed typed
    /// answers keep ≤ 200 characters); `onboardingCompleted` keeps only reason and the beginner flag.
    static func sanitizedPayload(type: String, payloadJSON: String) -> Any? {
        guard let data = payloadJSON.data(using: .utf8),
            var payload = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
        else { return nil }
        switch type {
        case "attempt":
            let format = payload["format"] as? String
            let mode = payload["mode"] as? String
            if format == "talk" || format == "writing" || mode == "spoken" {
                payload.removeValue(forKey: "response")
            } else if let r = payload["response"] as? String, r.count > closedResponseLimit {
                payload["response"] = String(r.prefix(closedResponseLimit))
            }
        case "onboardingCompleted":
            payload = payload.filter { $0.key == "reason" || $0.key == "beginner" }
        default:
            break
        }
        return payload
    }

    /// The uploaded types (docs/12); anything else (future types) stays on the device.
    static let uploadedTypes: Set<String> = [
        "attempt", "introduced", "stepStarted", "stepCompleted", "glossTapped", "audioPlayed", "session",
        "checkCompleted", "placementCompleted", "onboardingCompleted",
    ]
}

/// Builds batches and talks to the study endpoint. Callers trigger `uploadPending` when the app goes to the
/// background and every 15 minutes while active (docs/12 § Client).
actor TelemetryUploader {
    enum Outcome: Equatable, Sendable {
        case notAllowed  // no consent, not a study build, or no endpoint/token
        case nothingToSend
        case sent(events: Int, batches: Int)
        /// 5xx or network: try again after the backoff delay (seconds).
        case retryLater(afterSeconds: Int)
    }

    static let batchLimit = 500
    static let maxBackoffSeconds = 6 * 3600

    private let endpoint: URL?
    private let token: String?
    private let source: TelemetryEventSource
    private let transport: HTTPTransport
    private let newBatchID: @Sendable () -> String
    private let now: @Sendable () -> Int64
    private var failures = 0
    private var notBefore: Int64 = 0

    init(
        endpoint: URL?, token: String?, source: TelemetryEventSource, transport: HTTPTransport,
        newBatchID: @escaping @Sendable () -> String, now: @escaping @Sendable () -> Int64
    ) {
        self.endpoint = endpoint
        self.token = token
        self.source = source
        self.transport = transport
        self.newBatchID = newBatchID
        self.now = now
    }

    /// Exponential backoff for 5xx and network errors: 60 s, 120 s, 240 s … capped at 6 h.
    static func backoffSeconds(failures: Int) -> Int {
        guard failures > 0 else { return 0 }
        let exp = min(failures - 1, 20)
        return min(60 * (1 << exp), maxBackoffSeconds)
    }

    func uploadPending(consent: StudyConsent?, installID: String?, app: TelemetryAppInfo) async -> Outcome {
        guard let endpoint, let token, let consent, consent.granted, let installID else { return .notAllowed }
        if now() < notBefore { return .retryLater(afterSeconds: Int((notBefore - now()) / 1000)) }
        var sentEvents = 0
        var batches = 0
        while true {
            let events: [StoredEvent]
            do {
                events = try await source.unsentLocalEvents(since: consent.date, limit: Self.batchLimit)
                    .filter { $0.isLocal && $0.at >= consent.date }
            } catch {
                return registerFailure()
            }
            guard !events.isEmpty else { break }
            let batchID = newBatchID()
            let body = Self.batchBody(installID: installID, app: app, events: events)
            let request = HTTPRequestSpec(
                method: "POST", url: endpoint.appendingPathComponent("v1/batches"),
                headers: ["Authorization": "Bearer \(token)", "Content-Type": "application/json"], body: body)
            let status: Int
            do {
                status = try await transport.send(request)
            } catch {
                return registerFailure()
            }
            switch status {
            case 200..<300, 400..<500:
                // 2xx: accepted (idempotent). 4xx: logged and marked sent, never retried (docs/12).
                do {
                    try await source.markSent(eventIDs: events.map(\.id), batchID: batchID, at: now())
                } catch {
                    return registerFailure()
                }
                failures = 0
                notBefore = 0
                sentEvents += events.count
                batches += 1
                if events.count < Self.batchLimit { return .sent(events: sentEvents, batches: batches) }
            default:
                return registerFailure()
            }
        }
        return sentEvents == 0 ? .nothingToSend : .sent(events: sentEvents, batches: batches)
    }

    private func registerFailure() -> Outcome {
        failures += 1
        let delay = Self.backoffSeconds(failures: failures)
        notBefore = now() + Int64(delay) * 1000
        return .retryLater(afterSeconds: delay)
    }

    /// "Delete my study data" (docs/12 § Privacy): DELETE {url}/v1/installs/{installId}. The caller turns consent off.
    func deleteStudyData(installID: String) async -> Bool {
        guard let endpoint, let token else { return false }
        let request = HTTPRequestSpec(
            method: "DELETE", url: endpoint.appendingPathComponent("v1/installs/\(installID)"),
            headers: ["Authorization": "Bearer \(token)"], body: nil)
        guard let status = try? await transport.send(request) else { return false }
        return (200..<300).contains(status)
    }

    static func batchBody(installID: String, app: TelemetryAppInfo, events: [StoredEvent]) -> Data {
        let appDict: [String: Any] = [
            "version": app.version, "build": app.build, "pack": app.pack, "platform": app.platform, "os": app.os,
            "deviceClass": app.deviceClass,
        ]
        let list: [[String: Any]] = events.compactMap { e in
            guard TelemetryPrivacy.uploadedTypes.contains(e.type),
                let payload = TelemetryPrivacy.sanitizedPayload(type: e.type, payloadJSON: e.payloadJSON)
            else { return nil }
            return [
                "id": e.id, "at": e.at, "tzOffsetMin": e.tzOffsetMin, "type": e.type, "schema": e.schema,
                "payload": payload,
            ]
        }
        let body: [String: Any] = ["installId": installID, "app": appDict, "events": list]
        return (try? JSONSerialization.data(withJSONObject: body, options: [.sortedKeys])) ?? Data()
    }
}

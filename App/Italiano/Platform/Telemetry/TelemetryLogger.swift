import LearningCore
import os

private let telemetryLog = Logger(subsystem: "com.j23n.italian", category: "telemetry")

/// The study uploader's log (docs/12: a 4xx is logged, marked sent and never retried). Batch IDs, counts and status
/// codes only: never an event or anything the participant wrote.
struct TelemetryLogger: CoreLogger {
    func log(_ message: String) { telemetryLog.error("\(message, privacy: .public)") }
}

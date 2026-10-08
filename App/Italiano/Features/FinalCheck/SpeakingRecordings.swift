import Foundation
import LearningCore

/// The final check's speaking recordings (docs/09 § Transcription): every spoken answer records to
/// `Application Support/Italiano/recordings/<exerciseId>-<attemptId>.m4a` on the recording device (never synced),
/// for the examiner export (docs/12). The recogniser writes to a pending file while the learner speaks; when the
/// answer becomes an `attempt` event, the file takes the event's ID. Recordings are deleted once they are inside an
/// export, or 30 days after they were made, whichever comes first. Platform-neutral and tested.
@MainActor
final class SpeakingRecordings {
    nonisolated static let retentionDays = 30

    let directory: URL
    private let ids: any UUIDSource
    /// The recording made for each exercise since its last attempt.
    private var pending: [ExerciseID: URL] = [:]
    /// Attempt event ID → its recording.
    private(set) var byAttempt: [String: URL] = [:]

    init(directory: URL, ids: any UUIDSource) {
        self.directory = directory
        self.ids = ids
    }

    /// Where the recogniser writes the next spoken answer to `exercise`. A pending recording of the same exercise
    /// that never became an attempt (nothing was heard) is replaced.
    func destination(for exercise: ExerciseID) -> URL? {
        do {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        } catch {
            return nil
        }
        if let old = pending[exercise] { try? FileManager.default.removeItem(at: old) }
        let url = directory.appendingPathComponent("\(Self.safe(exercise.rawValue))-pending-\(ids.next()).m4a")
        pending[exercise] = url
        return url
    }

    /// An attempt was recorded: its pending recording (if the recogniser wrote one) becomes
    /// `<exerciseId>-<attemptId>.m4a`.
    @discardableResult
    func attach(attemptID: String, exercise: ExerciseID) -> URL? {
        guard let url = pending.removeValue(forKey: exercise),
            FileManager.default.fileExists(atPath: url.path)
        else { return nil }
        let target = directory.appendingPathComponent(Self.fileName(exercise: exercise, attemptID: attemptID))
        do {
            try? FileManager.default.removeItem(at: target)
            try FileManager.default.moveItem(at: url, to: target)
            byAttempt[attemptID] = target
            return target
        } catch {
            return nil
        }
    }

    /// The end of the sitting: recordings that never became an attempt are deleted.
    func discardPending() {
        for url in pending.values { try? FileManager.default.removeItem(at: url) }
        pending = [:]
    }

    /// After a successful export: the recordings it holds are deleted from their folder.
    func delete(_ urls: [URL]) {
        for url in urls { try? FileManager.default.removeItem(at: url) }
        byAttempt = byAttempt.filter { !urls.contains($0.value) }
    }

    nonisolated static func fileName(exercise: ExerciseID, attemptID: String) -> String {
        "\(safe(exercise.rawValue))-\(safe(attemptID)).m4a"
    }

    /// IDs are already file-safe (`final.s01`, UUIDs); this keeps a stray `/` or `:` out of a path anyway.
    nonisolated static func safe(_ s: String) -> String {
        String(s.map { $0 == "/" || $0 == ":" || $0 == "\\" ? "_" : $0 })
    }

    /// Deletes files in `directory` older than the retention period (at launch). Returns how many went.
    @discardableResult
    nonisolated static func purge(directory: URL, nowMs: Int64, days: Int = retentionDays) -> Int {
        let fm = FileManager.default
        guard
            let files = try? fm.contentsOfDirectory(
                at: directory, includingPropertiesForKeys: [.contentModificationDateKey])
        else { return 0 }
        let cutoff = Date(timeIntervalSince1970: Double(nowMs) / 1000 - Double(days) * 86_400)
        var removed = 0
        for url in files {
            let modified = (try? url.resourceValues(forKeys: [.contentModificationDateKey]))?.contentModificationDate
            if let modified, modified < cutoff, (try? fm.removeItem(at: url)) != nil { removed += 1 }
        }
        return removed
    }
}

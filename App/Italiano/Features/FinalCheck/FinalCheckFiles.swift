import Foundation

/// What the final A1 check keeps on the recording device for the examiner export (docs/09 § Transcription,
/// docs/12 § Final check export), under `Application Support/Italiano/`:
///
/// - `final-check/<sittingId>/`: one folder per sitting, with its recordings (`SpeakingRecordings`) and, once the
///   check ends, `sitting.json` (the `ExaminerExport` record the zip is built from). It goes after a completed share
///   of the export, or 30 days after the check, whichever comes first; leaving a sitting deletes it at once.
/// - `exports/`: a zip only while it is in the share sheet (built when **Export for examiner** is tapped, deleted
///   when the share ends either way); whatever is left there at launch is deleted.
///
/// The files belong to the learner database that holds the sitting's `checkCompleted` event: the container deletes
/// them all when progress is reset or the iCloud account changes, and never offers a sitting whose event is gone.
/// Platform-neutral and tested.
struct FinalCheckFiles: Sendable {
    static let retentionDays = 30
    static let recordName = "sitting.json"

    /// `Application Support/Italiano/` (or the folder of a test's learner database).
    let root: URL

    var sittingsDirectory: URL { root.appendingPathComponent("final-check", isDirectory: true) }
    var exportsDirectory: URL { root.appendingPathComponent("exports", isDirectory: true) }

    func sittingDirectory(_ sittingId: String) -> URL {
        sittingsDirectory.appendingPathComponent(SpeakingRecordings.safe(sittingId), isDirectory: true)
    }

    /// Writes the sitting's record next to its recordings.
    func save(_ export: ExaminerExport) throws {
        let directory = sittingDirectory(export.sittingId)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        try encoder.encode(export).write(to: directory.appendingPathComponent(Self.recordName), options: .atomic)
    }

    /// The sitting's record is still on this device (no completed share, not past 30 days, not reset).
    func hasSitting(_ sittingId: String) -> Bool {
        FileManager.default.fileExists(
            atPath: sittingDirectory(sittingId).appendingPathComponent(Self.recordName).path)
    }

    /// Every sitting with a readable record, the newest first.
    func sittings() -> [ExaminerExport] {
        let decoder = JSONDecoder()
        return folders().compactMap { folder in
            (try? Data(contentsOf: folder.appendingPathComponent(Self.recordName)))
                .flatMap { try? decoder.decode(ExaminerExport.self, from: $0) }
        }
        .sorted { ($0.takenAt, $0.sittingId) > ($1.takenAt, $1.sittingId) }
    }

    /// The sitting's recordings and record.
    func deleteSitting(_ sittingId: String) {
        try? FileManager.default.removeItem(at: sittingDirectory(sittingId))
    }

    /// Everything: every sitting and any zip (progress reset, another learner database).
    func deleteAll() {
        try? FileManager.default.removeItem(at: sittingsDirectory)
        try? FileManager.default.removeItem(at: exportsDirectory)
    }

    /// Builds the export's zip in `exports/` for the share sheet.
    func writeZip(_ export: ExaminerExport) throws -> URL {
        try FileManager.default.createDirectory(at: exportsDirectory, withIntermediateDirectories: true)
        let url = exportsDirectory.appendingPathComponent(export.fileName)
        try export.archive(recordings: sittingDirectory(export.sittingId)).write(to: url, options: .atomic)
        return url
    }

    /// At launch (no sitting is running): sittings taken more than 30 days ago, folders without a record (a sitting
    /// the app was closed in) and every zip left in `exports/` are deleted. Returns how many sittings went.
    @discardableResult
    func purge(nowMs: Int64, days: Int = retentionDays) -> Int {
        try? FileManager.default.removeItem(at: exportsDirectory)
        let cutoff = nowMs - Int64(days) * 86_400_000
        let decoder = JSONDecoder()
        var removed = 0
        for folder in folders() {
            let record = (try? Data(contentsOf: folder.appendingPathComponent(Self.recordName)))
                .flatMap { try? decoder.decode(ExaminerExport.self, from: $0) }
            if let record, record.takenAt >= cutoff { continue }
            if (try? FileManager.default.removeItem(at: folder)) != nil { removed += 1 }
        }
        return removed
    }

    private func folders() -> [URL] {
        let urls =
            (try? FileManager.default.contentsOfDirectory(
                at: sittingsDirectory, includingPropertiesForKeys: [.isDirectoryKey])) ?? []
        return urls.filter { (try? $0.resourceValues(forKeys: [.isDirectoryKey]))?.isDirectory == true }
    }
}

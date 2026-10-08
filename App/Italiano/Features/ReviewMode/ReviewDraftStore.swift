import Foundation

/// The review draft as a JSON file (Application Support/Italiano/review-comments.json in the app). Review builds
/// only: it is the content lead's working copy, not learner data, so it lives outside the event log and is never
/// synced; Send and Export are how it leaves the device.
struct FileReviewDraftStore: ReviewDraftStoring, Sendable {
    let url: URL

    /// `Application Support/Italiano/review-comments.json`, next to the learner database.
    static func inApplicationSupport() throws -> FileReviewDraftStore {
        let base = try FileManager.default.url(
            for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true)
        return FileReviewDraftStore(url: base.appendingPathComponent("Italiano/review-comments.json"))
    }

    /// An unreadable file is moved aside (`review-comments.unreadable.json`) before the error is thrown, so the next
    /// save never overwrites the content lead's comments.
    func load() throws -> ReviewDraft? {
        guard FileManager.default.fileExists(atPath: url.path) else { return nil }
        do {
            return try JSONDecoder().decode(ReviewDraft.self, from: Data(contentsOf: url))
        } catch {
            let aside = url.deletingPathExtension().appendingPathExtension("unreadable.json")
            try? FileManager.default.removeItem(at: aside)
            try? FileManager.default.moveItem(at: url, to: aside)
            throw error
        }
    }

    func save(_ draft: ReviewDraft) throws {
        try FileManager.default.createDirectory(
            at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        try encoder.encode(draft).write(to: url, options: .atomic)
    }
}

/// Tests and previews.
final class InMemoryReviewDraftStore: ReviewDraftStoring {
    private(set) var draft: ReviewDraft?
    var failsToSave = false

    init(_ draft: ReviewDraft? = nil) { self.draft = draft }

    func load() throws -> ReviewDraft? { draft }

    func save(_ draft: ReviewDraft) throws {
        struct SaveFailed: Error {}
        if failsToSave { throw SaveFailed() }
        self.draft = draft
    }
}

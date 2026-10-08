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

    /// The file store, or, when it can't be created, one that keeps nothing and says so: the comments screen shows
    /// the save error from launch, before the content lead writes a comment that would vanish on quit.
    static func orUnavailable(_ make: () throws -> FileReviewDraftStore) -> any ReviewDraftStoring {
        (try? make()) ?? UnavailableReviewDraftStore()
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

/// No place on the device for the comments (Application Support couldn't be opened): loading and saving fail with
/// `Unavailable`, which `ReviewCollector` reports as a save error from the start.
struct UnavailableReviewDraftStore: ReviewDraftStoring, Sendable {
    struct Unavailable: Error {}

    func load() throws -> ReviewDraft? { throw Unavailable() }
    func save(_ draft: ReviewDraft) throws { throw Unavailable() }
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

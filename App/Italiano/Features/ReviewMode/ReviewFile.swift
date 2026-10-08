import Foundation
import Observation

// Review mode in the app (docs/04 § Content review loop › 2 and 3, docs/06 § Shared player behaviour, task M6.10).
// The content lead's comments are collected into the same review file the review pages produce; `content
// review-import` files it unchanged. Platform-neutral: the share sheet and the HTTP transport live elsewhere.

/// One comment (docs/04 § The review file).
struct ReviewComment: Codable, Sendable, Equatable, Identifiable {
    var id: String
    var target: String  // an ID from docs/03, a text line `<textId>#n`, or a conversation node `<exerciseId>/<nodeId>`
    var file: String?
    var quote: String?
    var verdict: Verdict
    var category: Category
    var comment: String
    var suggestion: String?
    var response: String?  // the learner answer behind "This should be accepted"
    var at: String  // ISO 8601 UTC

    enum Verdict: String, Codable, Sendable, CaseIterable { case ok, change, question }

    /// The categories of the review page (docs/04 § Review pages).
    enum Category: String, Codable, Sendable, CaseIterable {
        case italianError = "italian-error"
        case naturalness
        case level
        case answerKey = "answer-key"
        case hintOrRule = "hint-or-rule"
        case english
        case cultureOrFacts = "culture-or-facts"
        case audio
        case other

        var label: String {
            switch self {
            case .italianError: "Italian error"
            case .naturalness: "Unnatural"
            case .level: "Level"
            case .answerKey: "Answer key"
            case .hintOrRule: "Hint or rule"
            case .english: "English"
            case .cultureOrFacts: "Culture or facts"
            case .audio: "Audio"
            case .other: "Other"
            }
        }
    }
}

struct ReviewSignoff: Codable, Sendable, Equatable {
    var name: String
    var at: String
    var files: [String: String]
}

/// The review file: `format` 1, `channel` page | app.
struct ReviewFile: Codable, Sendable, Equatable {
    var format = 1
    var reviewer: String
    var channel = "app"
    var scope: String
    var created: String
    var files: [String: String]  // content path → approval hash of the version shown
    var comments: [ReviewComment]
    var signoff: ReviewSignoff?

    func encoded() throws -> Data {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        return try encoder.encode(self)
    }

    /// `review-<scope>-<date>.json`, the name the review page uses for downloads.
    var suggestedFileName: String { "review-\(scope)-\(created.prefix(10)).json" }
}

/// Which content file (and approval hash) a target belongs to, from the pack's `meta.review_files`
/// (`{"<id prefix>": {"file": "content/…yaml", "hash": "<approval hash>"}}`, written by the dev pack build).
struct ReviewFileIndex: Sendable, Equatable {
    struct Entry: Codable, Sendable, Equatable {
        let file: String
        let hash: String
    }

    let byPrefix: [String: Entry]

    init(byPrefix: [String: Entry]) { self.byPrefix = byPrefix }

    init(metaJSON: String?) {
        let data = Data((metaJSON ?? "{}").utf8)
        byPrefix = (try? JSONDecoder().decode([String: Entry].self, from: data)) ?? [:]
    }

    /// The longest prefix match: `u02.l1.ex07` → the `u02.l1` lesson file; `u02.task.conv1/n3` → `u02.task`.
    func entry(for target: String) -> Entry? {
        let base = target.split(separator: "/").first.map(String.init) ?? target
        var candidate = base.split(separator: "#").first.map(String.init) ?? base
        while true {
            if let e = byPrefix[candidate] { return e }
            guard let dot = candidate.lastIndex(of: ".") else { return nil }
            candidate = String(candidate[..<dot])
        }
    }
}

/// The review session the content lead builds in the app: comments, Export and Send (docs/04).
@MainActor
@Observable
final class ReviewCollector {
    private(set) var comments: [ReviewComment] = []
    var reviewer: String
    let scope: String
    private let index: ReviewFileIndex
    private let newID: () -> String
    private let nowISO: () -> String

    init(
        reviewer: String, scope: String, index: ReviewFileIndex, newID: @escaping () -> String,
        nowISO: @escaping () -> String
    ) {
        self.reviewer = reviewer
        self.scope = scope
        self.index = index
        self.newID = newID
        self.nowISO = nowISO
    }

    @discardableResult
    func add(
        target: String, quote: String?, verdict: ReviewComment.Verdict, category: ReviewComment.Category,
        comment: String, suggestion: String? = nil, response: String? = nil
    ) -> ReviewComment {
        let c = ReviewComment(
            id: newID(), target: target, file: index.entry(for: target)?.file, quote: quote, verdict: verdict,
            category: category, comment: comment, suggestion: suggestion?.nilIfEmpty, response: response, at: nowISO())
        comments.append(c)
        return c
    }

    /// "This should be accepted" in the feedback panel after a rejected answer: one tap, an answer-key comment.
    @discardableResult
    func shouldBeAccepted(exerciseID: String, turnID: String?, response: String, prompt: String?) -> ReviewComment {
        add(
            target: turnID.map { "\(exerciseID)/\($0)" } ?? exerciseID, quote: prompt, verdict: .change,
            category: .answerKey, comment: "This should be accepted.", response: response)
    }

    func remove(id: String) { comments.removeAll { $0.id == id } }

    func reviewFile() -> ReviewFile {
        var files: [String: String] = [:]
        for c in comments {
            if let e = index.entry(for: c.target) { files[e.file] = e.hash }
        }
        return ReviewFile(
            reviewer: reviewer, scope: scope, created: nowISO(), files: files, comments: comments,
            signoff: nil)
    }

    /// POST {ITA_REVIEW_URL}/v1/review-comments (docs/12); Export works without it.
    func send(endpoint: URL, token: String, transport: HTTPTransport) async -> Bool {
        guard let body = try? reviewFile().encoded() else { return false }
        let request = HTTPRequestSpec(
            method: "POST", url: endpoint.appendingPathComponent("v1/review-comments"),
            headers: ["Authorization": "Bearer \(token)", "Content-Type": "application/json"], body: body)
        guard let status = try? await transport.send(request) else { return false }
        return (200..<300).contains(status)
    }
}

extension String {
    var nilIfEmpty: String? { isEmpty ? nil : self }
}

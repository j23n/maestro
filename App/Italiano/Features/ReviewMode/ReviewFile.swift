import Foundation
import Observation

// Review mode in the app (docs/04 § Content review loop › 2 and 3, docs/06 § Shared player behaviour, task M6.10).
// The content lead's comments are collected into the same review file the review pages produce; `content
// review-import` files it unchanged. Platform-neutral: the share sheet and the HTTP transport live elsewhere.

/// One comment (docs/04 § The review file; `schemas/review-file.schema.json` › comment).
struct ReviewComment: Codable, Sendable, Equatable, Identifiable {
    var id: String
    var target: String  // an ID from docs/03, a text line `<textId>#n`, or a conversation node `<exerciseId>/<nodeId>`
    var file: String  // required by the schema: a comment is only filed when the pack names the target's file
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

    /// Optional fields are written as `null`, like the review page does.
    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(id, forKey: .id)
        try c.encode(target, forKey: .target)
        try c.encode(file, forKey: .file)
        try c.encode(quote, forKey: .quote)
        try c.encode(verdict, forKey: .verdict)
        try c.encode(category, forKey: .category)
        try c.encode(comment, forKey: .comment)
        try c.encode(suggestion, forKey: .suggestion)
        try c.encode(response, forKey: .response)
        try c.encode(at, forKey: .at)
    }
}

extension ReviewComment.Verdict {
    /// The page's verdict names (docs/04 § Review pages: ✓ OK · ✎ Change · ? Question).
    var title: String {
        switch self {
        case .ok: "OK"
        case .change: "Change"
        case .question: "Question"
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

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(format, forKey: .format)
        try c.encode(reviewer, forKey: .reviewer)
        try c.encode(channel, forKey: .channel)
        try c.encode(scope, forKey: .scope)
        try c.encode(created, forKey: .created)
        try c.encode(files, forKey: .files)
        try c.encode(comments, forKey: .comments)
        try c.encode(signoff, forKey: .signoff)  // the app never signs off: always null
    }

    func encoded() throws -> Data {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        return try encoder.encode(self)
    }

    /// `review-<scope>-<date>.json`, the name the review page uses for downloads.
    var suggestedFileName: String { "review-\(scope)-\(created.prefix(10)).json" }
}

/// The review scope a comment is filed under, from its file (mirrors `itcontent.review.unit_of_comment`): a unit's
/// lessons, task, check and items file → `uNN`; the placement test and final check → `assessments`; everything else
/// (unit specs, grammar points, story bible…) → `specs`. `content review-import` files each review in its scope's
/// ledger, so one review file holds one scope.
enum ReviewScope {
    static func of(file: String) -> String {
        let parts = file.split(separator: "/", omittingEmptySubsequences: false).map(String.init)
        if parts.count >= 4, parts[0] == "content", parts[1] == "units", parts[3] != "unit.yaml" || parts.count > 4,
            let n = unitNumber(parts[2], separator: "-")
        {
            return "u\(n)"
        }
        if parts.count == 3, parts[0] == "content", parts[1] == "items", parts[2].hasPrefix("u"),
            parts[2].hasSuffix(".yaml"), let n = unitNumber(String(parts[2].dropFirst().dropLast(5)), separator: nil)
        {
            return "u\(n)"
        }
        if file.hasPrefix("content/assessments/") { return "assessments" }
        return "specs"
    }

    /// `02-al-bar` → `02` (with separator "-"), `02` → `02` (without).
    private static func unitNumber(_ s: String, separator: Character?) -> String? {
        let digits = s.prefix(2)
        guard digits.count == 2, digits.allSatisfy(\.isASCIIDigit) else { return nil }
        if let separator {
            return s.dropFirst(2).first == separator ? String(digits) : nil
        }
        return s.count == 2 ? String(digits) : nil
    }
}

extension Character {
    fileprivate var isASCIIDigit: Bool { ("0"..."9").contains(self) }
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

/// What the app keeps on the device between launches: the comments, the hash of the file version each one was made
/// on (the review file's `files`), and which comments Send already delivered.
struct ReviewDraft: Codable, Sendable, Equatable {
    struct Filed: Codable, Sendable, Equatable {
        var comment: ReviewComment
        /// The approval hash of the file version the teacher saw.
        var hash: String
        var sent = false
    }

    var reviewer = ""
    var comments: [Filed] = []
}

/// Where the draft lives: a JSON file in Application Support (`FileReviewDraftStore`), or memory in tests.
protocol ReviewDraftStoring {
    func load() throws -> ReviewDraft?
    func save(_ draft: ReviewDraft) throws
}

/// The comments the content lead makes in the app: kept on the device until they are sent or exported, so closing
/// the app never loses them (docs/04 § Review mode in the app).
@MainActor
@Observable
final class ReviewCollector {
    private(set) var filed: [ReviewDraft.Filed]
    private(set) var reviewer: String
    private(set) var index: ReviewFileIndex
    /// Set when the device couldn't store the comments (shown on the comments screen).
    private(set) var saveError: String?
    /// Set when the stored comments couldn't be read at launch (the file is kept aside, never overwritten).
    private(set) var loadError: String?
    @ObservationIgnored private let store: (any ReviewDraftStoring)?
    @ObservationIgnored private let newID: () -> String
    @ObservationIgnored private let nowISO: () -> String

    init(
        index: ReviewFileIndex = ReviewFileIndex(byPrefix: [:]), store: (any ReviewDraftStoring)? = nil,
        newID: @escaping () -> String, nowISO: @escaping () -> String
    ) {
        var draft: ReviewDraft?
        var unreadable: String?
        do {
            draft = try store?.load()
        } catch {
            unreadable = "Earlier comments couldn't be read; the file was kept as review-comments.unreadable.json."
        }
        filed = draft?.comments ?? []
        reviewer = draft?.reviewer ?? ""
        self.index = index
        self.store = store
        self.newID = newID
        self.nowISO = nowISO
        loadError = unreadable
    }

    var comments: [ReviewComment] { filed.map(\.comment) }
    var unsent: [ReviewComment] { filed.filter { !$0.sent }.map(\.comment) }

    func setIndex(_ index: ReviewFileIndex) { self.index = index }

    func setReviewer(_ name: String) {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed != reviewer else { return }
        reviewer = trimmed
        persist()
    }

    /// A comment can be filed only when the pack names the target's file and hash (the schema requires `file`).
    func canFile(_ target: String) -> Bool { index.entry(for: target) != nil }

    /// "content/units/02-al-bar/lesson-1.yaml · b9c81449": what the comment sheet shows under the target.
    func fileLine(for target: String) -> String? {
        index.entry(for: target).map { "\($0.file) · \($0.hash.prefix(8))" }
    }

    /// Files a comment; nil when the target's file is unknown (nothing is filed against nothing).
    @discardableResult
    func add(
        target: String, quote: String?, verdict: ReviewComment.Verdict, category: ReviewComment.Category,
        comment: String, suggestion: String? = nil, response: String? = nil
    ) -> ReviewComment? {
        guard let entry = index.entry(for: target) else { return nil }
        let c = ReviewComment(
            id: newID(), target: target, file: entry.file, quote: quote?.nilIfEmpty, verdict: verdict,
            category: category, comment: comment.trimmingCharacters(in: .whitespacesAndNewlines),
            suggestion: suggestion?.trimmingCharacters(in: .whitespacesAndNewlines).nilIfEmpty,
            response: response, at: nowISO())
        filed.append(.init(comment: c, hash: entry.hash))
        persist()
        return c
    }

    /// "This should be accepted" in the feedback panel after a rejected answer: one tap files an answer-key change
    /// with the answer as `response`, which `content review-import` turns into an accept proposal (docs/04 § 4).
    @discardableResult
    func shouldBeAccepted(target: String, response: String, quote: String?) -> ReviewComment? {
        add(
            target: target, quote: quote, verdict: .change, category: .answerKey,
            comment: "This should be accepted.", response: response)
    }

    func hasAcceptRequest(target: String, response: String) -> Bool {
        filed.contains {
            $0.comment.target == target && $0.comment.response == response && $0.comment.category == .answerKey
        }
    }

    /// Only comments not sent yet can be taken back; sent ones are already with the owner.
    func remove(id: String) {
        filed.removeAll { $0.comment.id == id && !$0.sent }
        persist()
    }

    func isSent(_ id: String) -> Bool { filed.contains { $0.comment.id == id && $0.sent } }

    func markSent(_ ids: Set<String>) {
        for i in filed.indices where ids.contains(filed[i].comment.id) { filed[i].sent = true }
        persist()
    }

    /// The review files for `selection` (default: every comment): one per scope, and within a scope one per file
    /// version, so `files` always names the version each comment was made on and `review-import` flags stale ones.
    func reviewFiles(of selection: [ReviewDraft.Filed]? = nil) -> [ReviewFile] {
        let list = selection ?? filed
        let created = nowISO()
        let name = reviewer.isEmpty ? "Content lead" : reviewer
        var byScope: [String: [[ReviewDraft.Filed]]] = [:]
        for f in list {
            let scope = ReviewScope.of(file: f.comment.file)
            var buckets = byScope[scope] ?? []
            if let i = buckets.firstIndex(where: { bucket in
                !bucket.contains { $0.comment.file == f.comment.file && $0.hash != f.hash }
            }) {
                buckets[i].append(f)
            } else {
                buckets.append([f])
            }
            byScope[scope] = buckets
        }
        return byScope.keys.sorted().flatMap { scope in
            (byScope[scope] ?? []).map { bucket in
                ReviewFile(
                    reviewer: name, scope: scope, created: created,
                    files: Dictionary(bucket.map { ($0.comment.file, $0.hash) }, uniquingKeysWith: { a, _ in a }),
                    comments: bucket.map(\.comment), signoff: nil)
            }
        }
    }

    /// POST {ITA_REVIEW_URL}/v1/review-comments (docs/12), one review file per scope and version, with the comments
    /// not sent yet. The server is idempotent by comment id; a file is marked sent only after a 2xx.
    func send(endpoint: URL, token: String, transport: any HTTPTransport) async -> ReviewSendResult {
        let pending = filed.filter { !$0.sent }
        guard !pending.isEmpty else { return ReviewSendResult(sent: 0, failure: nil) }
        var result = ReviewSendResult(sent: 0, failure: nil)
        for file in reviewFiles(of: pending) {
            guard let body = try? file.encoded() else {
                result.failure = .couldNotEncode
                continue
            }
            let request = HTTPRequestSpec(
                method: "POST", url: endpoint.appendingPathComponent("v1/review-comments"),
                headers: ["Authorization": "Bearer \(token)", "Content-Type": "application/json"], body: body)
            do {
                let status = try await transport.send(request)
                if (200..<300).contains(status) {
                    markSent(Set(file.comments.map(\.id)))
                    result.sent += file.comments.count
                } else {
                    result.failure = .refused(status: status)
                }
            } catch {
                result.failure = .unreachable
            }
        }
        return result
    }

    private func persist() {
        do {
            try store?.save(ReviewDraft(reviewer: reviewer, comments: filed))
            saveError = nil
        } catch {
            saveError = "Your comments couldn't be saved on this device. Export them before closing Italiano."
        }
    }
}

/// What Send did: how many comments the server took, and why the rest weren't sent.
struct ReviewSendResult: Sendable, Equatable {
    enum Failure: Sendable, Equatable {
        case unreachable
        case refused(status: Int)
        case couldNotEncode
    }

    var sent: Int
    var failure: Failure?
}

extension String {
    var nilIfEmpty: String? { isEmpty ? nil : self }
}

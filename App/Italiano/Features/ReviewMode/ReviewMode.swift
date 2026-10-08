import Foundation
import LearningCore
import Observation

/// Review mode (docs/04 § Content review loop › 2, docs/06 § Shared player behaviour, task M6.10): the content
/// lead's tools in Review (TestFlight) and Debug builds: every unit and step unlocked with a jump menu and draft
/// badges, Comment on any step, exercise, text, line or word, the answer key, "This should be accepted", and Send
/// and Export of the review file.
///
/// **Learners never get it** (CLAUDE.md hard rule 4): it exists only when the build sets `ITA_REVIEW_MODE = YES`
/// (Debug and Review; never Release or Study, and `AppConfig` refuses it in study builds), and it turns on
/// (`isActive`) only on a dev pack (`meta.release = 0`), which learner builds never bundle. Everything that bypasses
/// eligibility (open locked units, jump to any page, no mini-preview) asks `isActive` first.
@MainActor
@Observable
final class ReviewMode {
    enum SendState: Equatable {
        case idle
        case sending
        case done(ReviewSendResult)
    }

    /// The launch argument that turns review mode off in a Debug build (UI tests of the learner's path).
    static let offArgument = "-ITANoReviewMode"

    let collector: ReviewCollector
    let tap = ReviewAnswerTap()
    /// The pack is a dev pack: the tools are on.
    private(set) var isActive = false
    private(set) var menu = ReviewJumpMenu(units: [])
    private(set) var sendState: SendState = .idle
    @ObservationIgnored private let endpoint: URL?
    @ObservationIgnored private let token: String?
    @ObservationIgnored private let transport: any HTTPTransport

    init?(
        config: AppConfig, arguments: [String] = [], store: (any ReviewDraftStoring)?, transport: any HTTPTransport,
        clock: any LearningCore.Clock, ids: any UUIDSource
    ) {
        guard config.reviewMode, !arguments.contains(Self.offArgument) else { return nil }
        endpoint = config.canSendReviewComments ? config.reviewURL : nil
        token = config.canSendReviewComments ? config.reviewToken : nil
        self.transport = transport
        collector = ReviewCollector(
            store: store, newID: { ids.next() }, nowISO: { ReviewMode.iso(ms: clock.nowMs()) })
    }

    /// The pack is open: review mode turns on for a dev pack only, with its file index and the jump menu.
    func attach(isReleasePack: Bool, index: ReviewFileIndex, menu: ReviewJumpMenu) {
        isActive = !isReleasePack
        guard isActive else { return }
        collector.setIndex(index)
        self.menu = menu
    }

    /// Send needs the endpoint and the review token (docs/12); Export always works.
    var canSend: Bool { endpoint != nil && token != nil }

    // MARK: - Unlocked course

    /// The Indice with every unit open (docs/04: every unit and step unlocked). Learners' rows are untouched.
    func unlocked(_ rows: [CourseRow]) -> [CourseRow] {
        guard isActive else { return rows }
        return rows.map {
            CourseRow(
                unitID: $0.unitID, number: $0.number, titleIt: $0.titleIt, subtitle: $0.subtitle,
                status: $0.status, tone: $0.tone, isOpen: true)
        }
    }

    func isDraft(_ step: StepID) -> Bool { isActive && menu.isDraft(step) }

    /// Opens the player exactly where the content lead jumped (a step's first page or one exercise), whatever the
    /// learner state says, and listens to the answers for "This should be accepted".
    func prepare(_ launch: AppModel.PlayerLaunch, at jump: ReviewJump) {
        guard isActive else { return }
        let model = launch.model
        if let i = jump.exercise.flatMap({ model.index(ofExercise: $0) }) ?? model.index(ofStep: jump.step) {
            model.move(to: i)
        }
        tap.reset()
        let previous = launch.sink.onRecord
        let tap = self.tap
        launch.sink.onRecord = { draft in
            previous?(draft)
            tap.record(draft)
        }
    }

    // MARK: - Comments

    /// The targets the Comment button offers on a page (only those whose file the pack names).
    func targets(
        for entry: LessonPlayerModel.Entry, bundle: LessonBundle, conversationNode: String? = nil,
        first: ReviewTarget? = nil
    ) -> [ReviewTarget] {
        var seen: Set<String> = []
        let all =
            [first].compactMap { $0 } + ReviewTargets.forPage(entry, bundle: bundle, conversationNode: conversationNode)
        return all.filter { collector.canFile($0.id) && seen.insert($0.id).inserted }
    }

    func commentDraft(targets: [ReviewTarget]) -> ReviewCommentDraft { ReviewCommentDraft(targets: targets) }

    /// Saves the comment sheet; nil when it can't be filed yet.
    @discardableResult
    func save(_ draft: ReviewCommentDraft) -> ReviewComment? {
        guard draft.canSave, let target = draft.target, let category = draft.category else { return nil }
        return collector.add(
            target: target.id, quote: target.quote, verdict: draft.verdict, category: category,
            comment: draft.comment, suggestion: draft.suggestion)
    }

    /// "This should be accepted": the rejected answer of the exercise on screen, if any.
    func rejectedAnswer(for exercise: ExerciseID) -> RejectedAnswer? { tap.rejected[exercise] }

    func isFiled(_ r: RejectedAnswer) -> Bool { collector.hasAcceptRequest(target: r.target, response: r.response) }

    @discardableResult
    func fileAcceptRequest(_ r: RejectedAnswer, payload: ExercisePayload?) -> ReviewComment? {
        guard !isFiled(r) else { return nil }
        var quote = payload.flatMap(ReviewTargets.quote(for:))
        if let turn = r.turnID, case .conversation(let c)? = payload?.body, let node = c.node(turn) {
            quote = node.say.text
        }
        return collector.shouldBeAccepted(target: r.target, response: r.response, quote: quote)
    }

    // MARK: - Send and Export

    func send() async {
        guard let endpoint, let token, sendState != .sending else { return }
        sendState = .sending
        let result = await collector.send(endpoint: endpoint, token: token, transport: transport)
        sendState = .done(result)
    }

    /// One sentence about the last Send for the comments screen.
    var sendStatus: String? {
        switch sendState {
        case .idle: return nil
        case .sending: return "Sending…"
        case .done(let r):
            switch r.failure {
            case nil:
                return r.sent == 0 ? "Everything was already sent." : "Sent \(r.sent) comment\(r.sent == 1 ? "" : "s")."
            case .refused(let status)?:
                return "The review server refused the comments (error \(status)). They are kept; use Export instead."
            case .unreachable?:
                return "Couldn't reach the review server. Your comments are kept: try again later, or use Export."
            case .couldNotEncode?:
                return "Some comments couldn't be prepared for sending. Use Export instead."
            }
        }
    }

    /// Writes every comment as review files (one per scope and file version) into `folder` for the share sheet.
    /// Same-day names get `-2`, `-3`… like `content review-import` does in the inbox.
    func exportFiles(to folder: URL) throws -> [URL] {
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        var used: Set<String> = []
        var urls: [URL] = []
        for file in collector.reviewFiles() {
            let stem = String(file.suggestedFileName.dropLast(5))
            var name = "\(stem).json"
            var n = 2
            while used.contains(name) {
                name = "\(stem)-\(n).json"
                n += 1
            }
            used.insert(name)
            let url = folder.appendingPathComponent(name)
            try file.encoded().write(to: url, options: .atomic)
            urls.append(url)
        }
        return urls
    }

    /// `2026-10-20T09:15:00Z`: the review file's date-time format.
    nonisolated static func iso(ms: Int64) -> String {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        f.timeZone = TimeZone(identifier: "UTC")
        return f.string(from: Date(timeIntervalSince1970: Double(ms) / 1000))
    }
}

/// A typed, spoken or tapped answer the grader rejected: what "This should be accepted" files.
struct RejectedAnswer: Sendable, Equatable {
    let exerciseID: ExerciseID
    /// Conversation turns: the node that rejected it.
    let turnID: String?
    let response: String

    /// `u02.l1.ex07`, or `u02.task.conv1/n2` for a conversation turn.
    var target: String { turnID.map { "\(exerciseID.rawValue)/\($0)" } ?? exerciseID.rawValue }
}

/// Listens to the player's attempt drafts and keeps each exercise's latest rejected answer until a later answer
/// is accepted; revealing the answer or skipping keeps it (the panel still shows it was rejected).
@MainActor
@Observable
final class ReviewAnswerTap {
    private(set) var rejected: [ExerciseID: RejectedAnswer] = [:]

    func record(_ d: AttemptDraft) {
        switch d.outcome {
        case .wrong:
            let response = (d.response ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            rejected[d.exerciseID] =
                response.isEmpty ? nil : RejectedAnswer(exerciseID: d.exerciseID, turnID: d.turnID, response: response)
        case .correct, .correctWithNote, .almost:
            rejected[d.exerciseID] = nil
        case .revealed, .skipped:
            break
        }
    }

    func reset() { rejected = [:] }
}

/// The comment sheet's state (docs/06: pre-filled with the target ID, the quoted text and the file hash; the
/// content lead adds the verdict, category, comment and suggestion).
@MainActor
@Observable
final class ReviewCommentDraft {
    let targets: [ReviewTarget]
    var selectedID: String
    var verdict: ReviewComment.Verdict = .change
    /// Chosen by the content lead; nothing is preselected.
    var category: ReviewComment.Category?
    var comment = ""
    var suggestion = ""

    init(targets: [ReviewTarget]) {
        self.targets = targets
        selectedID = targets.first?.id ?? ""
    }

    var target: ReviewTarget? { targets.first { $0.id == selectedID } }

    /// A target and a category, and something to say (an OK may stand alone).
    var canSave: Bool {
        guard target != nil, category != nil else { return false }
        let said = [comment, suggestion].contains { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
        return said || verdict == .ok
    }
}

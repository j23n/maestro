import Foundation
import LearningCore
import Observation

// Output tasks: conversation, talk, writing, relay (docs/06 §12–§15). No FSRS updates (docs/05 § Rating policy);
// they are task-level evidence and check scores: talk and writing earn score × found/required, conversation
// score × goals completed/goals.

/// A conversation with a character: typed or spoken turns, goals that tick, help chips, a node-level register.
@MainActor
@Observable
final class ConversationModel {
    struct Line: Sendable, Equatable, Identifiable {
        enum Speaker: Sendable, Equatable { case character, learner }
        let id: Int
        let speaker: Speaker
        let italian: TokenizedText?
        let text: String
        let english: String?
    }

    enum TurnFeedback: Sendable, Equatable {
        /// First miss: the near hint or the node's hint, plus the help chips.
        case hint(String?)
        /// Second miss: "You could say: …"; the learner says or types it, or continues.
        case youCouldSay(String)
    }

    let payload: ExercisePayload
    let conversation: ExerciseBody.Conversation
    private let env: ExerciseEnvironment
    private weak var sink: AttemptSink?
    private(set) var nodeID: String
    private(set) var path: [String] = []
    private(set) var lines: [Line] = []
    private(set) var goalsDone: Set<String> = []
    private(set) var feedback: TurnFeedback?
    private(set) var missesAtNode = 0
    private(set) var isFinished = false
    var response = ""
    @ObservationIgnored private var clock: AttemptClock

    init?(payload: ExercisePayload, env: ExerciseEnvironment, sink: AttemptSink?) {
        guard case .conversation(let c) = payload.body, c.node(c.start) != nil else { return nil }
        self.payload = payload
        conversation = c
        self.env = env
        self.sink = sink
        nodeID = c.start
        clock = AttemptClock(now: env.nowMs)
        enterNode(c.start)
    }

    var node: ExerciseBody.ConversationNode? { conversation.node(nodeID) }
    var register: ExerciseBody.Register { conversation.register(at: nodeID, path: path) }
    var helpChips: [TokenizedText] { node?.help ?? [] }
    /// In checks speech is required when available and typing is hidden (docs/06 §12).
    var canType: Bool { !(env.context.isAssessment && env.canSpeak) }
    var canSpeak: Bool { env.canSpeak }
    var goals: [GoalProgress] { conversation.goals.map { GoalProgress(id: $0.id, text: $0.en, done: goalsDone.contains($0.id)) } }
    /// Check credit: goals completed / goals.
    var goalFraction: Double {
        conversation.goals.isEmpty ? 1 : Double(goalsDone.count) / Double(conversation.goals.count)
    }

    struct GoalProgress: Sendable, Equatable, Identifiable {
        let id: String
        let text: String
        let done: Bool
    }

    private func enterNode(_ id: String) {
        guard let n = conversation.node(id) else { return }
        nodeID = id
        path.append(id)
        missesAtNode = 0
        feedback = nil
        lines.append(Line(id: lines.count, speaker: .character, italian: n.say, text: n.say.text, english: n.en))
        if n.final || n.expect.isEmpty { isFinished = true }
        clock.restart()
    }

    func submitTyped() {
        let text = response.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, canType else { return }
        let grader = TypedAnswerGrader(knownForms: env.knownForms, profile: env.profile)
        let match = bestIntent { patterns in grader.grade(text, accepted: patterns).outcome.isSuccess }
        respond(text: text, matched: match, mode: .typed, nearCheck: { near in
            grader.grade(text, accepted: AnswerPattern.none, near: [near]).matchedNear
        })
    }

    func submitSpoken(_ result: SpeechResult) {
        guard env.canSpeak else { return }
        let matcher = TranscriptMatcher(profile: env.profile)
        var heard = result.transcript
        let match = bestIntent { patterns in
            guard let m = matcher.match(transcripts: result.allTranscripts, accepted: patterns) else { return false }
            if m.passed { heard = m.heard }
            return m.passed
        }
        respond(text: heard, matched: match, mode: .spoken, nearCheck: { near in
            matcher.match(transcripts: result.allTranscripts, accepted: [near.pattern])?.passed ?? false
        })
    }

    /// "Continue" after "You could say": the conversation follows the first intent's `next` (docs/06 §12).
    func continueAfterMiss() {
        guard case .youCouldSay = feedback, let first = node?.expect.first else { return }
        enterNode(first.next)
    }

    /// The first intent whose patterns accept the answer.
    private func bestIntent(_ accepts: ([AnswerPattern]) -> Bool) -> ExerciseBody.Expectation? {
        node?.expect.first { exp in
            let patterns = exp.accept.compactMap { try? $0.parsed() }
            return !patterns.isEmpty && accepts(patterns)
        }
    }

    private func respond(text: String, matched: ExerciseBody.Expectation?,
                         mode: AnswerMode, nearCheck: (TypedAnswerGrader.NearMiss) -> Bool)
    {
        guard let n = node, !isFinished else { return }
        lines.append(Line(id: lines.count, speaker: .learner, italian: nil, text: text, english: nil))
        let outcome: AttemptOutcome = matched != nil ? .correct : .wrong
        sink?.record(AttemptDraft(
            exerciseID: payload.id, turnID: n.id, format: .conversation, attemptIndex: min(missesAtNode + 1, 2),
            outcome: outcome, targets: [],
            response: mode == .typed ? ExercisePayload.clip(text, format: .conversation) : text, mode: mode,
            latencyMs: clock.latencyMs(), feedbackShown: missesAtNode > 0 ? .hint : .none))
        response = ""
        if let m = matched {
            if let g = m.goal { goalsDone.insert(g) }
            enterNode(m.next)
            return
        }
        missesAtNode += 1
        if env.context.isAssessment {
            // No hints in checks: the conversation moves on along the first intent, the goal is not ticked.
            if let first = n.expect.first { enterNode(first.next) }
            return
        }
        if missesAtNode == 1 {
            let nearHint = n.near.compactMap { try? $0.nearMiss() }.first(where: nearCheck)?.hint
            feedback = .hint(nearHint ?? n.hintEn)
        } else {
            let suggestion = n.help.first?.text
                ?? n.expect.first.flatMap { try? $0.accept.first?.parsed().modelAnswer(profile: env.profile, style: .display).text }
                ?? ""
            feedback = .youCouldSay(suggestion)
        }
    }
}

extension AnswerPattern {
    /// No accepted patterns: grading against it checks only the near misses.
    static let none: [AnswerPattern] = []
}

/// talk: speak (or type, in practice without speech) about the points; see the points found and the model.
@MainActor
@Observable
final class TalkModel {
    let payload: ExercisePayload
    let talk: ExerciseBody.Talk
    private let points: [ContentPointMatcher.Point]
    private let env: ExerciseEnvironment
    private weak var sink: AttemptSink?
    var response = ""
    private(set) var result: ContentPointMatcher.Result?
    private(set) var attempts = 0
    @ObservationIgnored private var clock: AttemptClock

    init?(payload: ExercisePayload, env: ExerciseEnvironment, sink: AttemptSink?) {
        guard case .talk(let t) = payload.body else { return nil }
        self.payload = payload
        talk = t
        points = t.points.compactMap { try? $0.matcherPoint() }
        self.env = env
        self.sink = sink
        clock = AttemptClock(now: env.nowMs)
    }

    /// Typing is allowed in practice when speech is unavailable (docs/06 §13).
    var canType: Bool { !env.canSpeak && !env.context.isAssessment }
    var found: Set<String> { Set(result?.found ?? []) }
    var credit: Double { result?.fraction ?? 0 }

    func submit(transcript: String, mode: AnswerMode) {
        attempts += 1
        response = transcript
        let r = ContentPointMatcher(profile: env.profile).match(response: transcript, points: points, pass: talk.pass)
        result = r
        let outcome: AttemptOutcome = r.passed ? .correct : .wrong
        sink?.record(AttemptDraft(
            exerciseID: payload.id, turnID: nil, format: .talk, attemptIndex: min(attempts, 2), outcome: outcome,
            targets: [], response: ExercisePayload.clip(transcript, format: .talk), mode: mode,
            latencyMs: clock.latencyMs(), feedbackShown: attempts > 1 ? .hint : .none))
        clock.restart()
    }

    func submitSpoken(_ s: SpeechResult) { submit(transcript: s.transcript, mode: .spoken) }
    func submitTyped() { submit(transcript: response, mode: .typed) }
}

/// writing: a form with per-field checks, or free text with a word count, the points and spelling advice.
@MainActor
@Observable
final class WritingModel {
    let payload: ExercisePayload
    let writing: ExerciseBody.Writing
    private let env: ExerciseEnvironment
    private weak var sink: AttemptSink?
    var text = ""
    var fieldValues: [String]
    private(set) var fieldValid: [Bool?]
    private(set) var result: ContentPointMatcher.Result?
    private(set) var suggestions: [WritingChecker.Suggestion] = []
    private(set) var submitted = false
    @ObservationIgnored private var clock: AttemptClock

    init?(payload: ExercisePayload, env: ExerciseEnvironment, sink: AttemptSink?) {
        guard case .writing(let w) = payload.body else { return nil }
        self.payload = payload
        writing = w
        fieldValues = Array(repeating: "", count: w.fields?.count ?? 0)
        fieldValid = Array(repeating: nil, count: w.fields?.count ?? 0)
        self.env = env
        self.sink = sink
        clock = AttemptClock(now: env.nowMs)
    }

    var isForm: Bool { writing.kind == .form }
    var wordCount: Int { WritingChecker.wordCount(text) }
    var wordCountOK: Bool {
        guard let w = writing.words else { return true }
        return (w.min...w.max).contains(wordCount)
    }

    var credit: Double {
        if isForm {
            let checked = fieldValid.compactMap { $0 }
            return checked.isEmpty ? 0 : Double(checked.filter { $0 }.count) / Double(checked.count)
        }
        return result?.fraction ?? 0
    }

    func submit() {
        submitted = true
        let passed: Bool
        let response: String
        if isForm, let fields = writing.fields {
            for (i, f) in fields.enumerated() { fieldValid[i] = Self.validate(fieldValues[i], field: f, env: env) }
            passed = fieldValid.allSatisfy { $0 == true }
            response = zip(fields, fieldValues).map { "\($0.labelIt.text): \($1)" }.joined(separator: "\n")
        } else {
            let points = (writing.points ?? []).compactMap { try? $0.matcherPoint() }
            let r = ContentPointMatcher(profile: env.profile).match(response: text, points: points, pass: writing.pass ?? 0)
            result = r
            suggestions = WritingChecker.spellingSuggestions(text, knownForms: env.knownForms)
            passed = r.passed && wordCountOK
            response = text
        }
        sink?.record(AttemptDraft(
            exerciseID: payload.id, turnID: nil, format: .writing, attemptIndex: 1, outcome: passed ? .correct : .wrong,
            targets: [], response: ExercisePayload.clip(response, format: .writing), mode: .typed,
            latencyMs: clock.latencyMs(), feedbackShown: .none))
    }

    static func validate(_ value: String, field: ExerciseBody.FormField, env: ExerciseEnvironment) -> Bool {
        let v = value.trimmingCharacters(in: .whitespaces)
        guard !v.isEmpty else { return false }
        if let accept = field.accept, !accept.isEmpty {
            let grader = TypedAnswerGrader(knownForms: env.knownForms, profile: env.profile)
            let patterns = accept.compactMap { try? $0.parsed() }
            return grader.grade(v, accepted: patterns).outcome.isSuccess
        }
        switch field.type {
        case .email: return v.contains("@") && v.split(separator: "@").count == 2 && v.contains(".")
        case .number, .phone: return v.allSatisfy { $0.isNumber || $0 == " " || $0 == "+" }
        case .text, .date: return true
        }
    }
}

/// relay: read or hear Italian, answer a friend in English (docs/06 §15).
@MainActor
@Observable
final class RelayModel {
    let payload: ExercisePayload
    let relay: ExerciseBody.Relay
    private let env: ExerciseEnvironment
    private weak var sink: AttemptSink?
    var response = ""
    private(set) var machine: FeedbackMachine
    @ObservationIgnored private var clock: AttemptClock

    init?(payload: ExercisePayload, env: ExerciseEnvironment, sink: AttemptSink?) {
        guard case .relay(let r) = payload.body else { return nil }
        self.payload = payload
        relay = r
        self.env = env
        self.sink = sink
        machine = FeedbackMachine(context: env.context, exerciseHint: payload.hint ?? "Look at the Italian again.")
        clock = AttemptClock(now: env.nowMs)
    }

    var isDone: Bool { machine.isDone }

    /// The expected answer as the friend would read it: "€1.60", "15:30", "3".
    var answerText: String? {
        let a = relay.answerEn
        switch (a.type, a.value) {
        case (.price, .number(let v)?): return "€" + String(format: "%.2f", v)
        case (.number, .number(let v)?): return v.rounded() == v ? String(Int(v)) : String(v)
        case (_, .string(let s)?): return s
        default: return a.accept?.first
        }
    }

    /// Try again after the hint: the field opens for the second attempt.
    func tryAgain() {
        machine.tryAgain()
        clock.restart()
    }

    func check() {
        guard let answer = relay.answerEn.graderAnswer, !response.isEmpty, !machine.isDone else { return }
        if case .hinted = machine.state { machine.tryAgain() }
        if let record = machine.submit(EnglishAnswerGrader.grade(response, answer: answer)) {
            sink?.record(AttemptDraft(
                exerciseID: payload.id, turnID: nil, format: .relay, attemptIndex: record.attemptIndex,
                outcome: record.outcome, targets: [], response: ExercisePayload.clip(response, format: .relay),
                mode: .typed, latencyMs: clock.latencyMs(), feedbackShown: record.feedbackShown))
        }
    }
}

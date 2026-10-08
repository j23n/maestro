import Foundation
import LearningCore
import Observation

/// What a typed exercise asks for, whatever produced it: a pack exercise (cloze, recall) or a generated review card
/// (`gen:recall:<itemId>`, docs/05 § Review session builder).
struct TypedTask: Sendable {
    let exerciseID: ExerciseID
    let format: ExerciseFormat
    let accepted: [AnswerPattern]
    let near: [TypedAnswerGrader.NearMiss]
    let targets: [TargetPayload]
    let hint: String?
    let rule: String?
    /// Shown after the answer for bare-noun answers to generated cards ("Say it with its article: il cornetto").
    let correctWithNoteText: String?

    init(
        exerciseID: ExerciseID, format: ExerciseFormat, accepted: [AnswerPattern],
        near: [TypedAnswerGrader.NearMiss] = [], targets: [TargetPayload], hint: String? = nil, rule: String? = nil,
        correctWithNoteText: String? = nil
    ) {
        self.exerciseID = exerciseID
        self.format = format
        self.accepted = accepted
        self.near = near
        self.targets = targets
        self.hint = hint
        self.rule = rule
        self.correctWithNoteText = correctWithNoteText
    }

    /// Cloze and recall payloads; nil for other formats or a pattern the pack shouldn't contain.
    init?(payload p: ExercisePayload) {
        let accepted: AnswerPattern
        switch p.body {
        case .cloze(let c):
            guard let gap = try? c.gapPattern() else { return nil }
            accepted = gap
        case .recall(let r):
            guard let a = try? r.answer.parsed() else { return nil }
            accepted = a
        default:
            return nil
        }
        self.init(
            exerciseID: p.id, format: p.format, accepted: [accepted], near: p.nearMisses(), targets: p.targets,
            hint: p.hint, rule: p.rule)
    }
}

/// Cloze, recall and generated recall cards: typed input with accent keys, Check, "Show a hint", stepped feedback,
/// and "Say it" for recall when speech is available (docs/06 §6, §7).
@MainActor
@Observable
final class TypedExerciseModel {
    let task: TypedTask
    let env: ExerciseEnvironment
    private weak var sink: AttemptSink?

    var response = ""
    private(set) var machine: FeedbackMachine
    private(set) var lastGrade: TypedGrade?
    private(set) var lastSpoken: TranscriptMatcher.Match?
    /// What the recogniser heard for the last answer when it was spoken (shown as "I heard: …"); nil after a
    /// typed answer.
    private(set) var lastHeard: String?
    private(set) var visibleHint: String?
    @ObservationIgnored private var clock: AttemptClock

    init(task: TypedTask, env: ExerciseEnvironment, sink: AttemptSink?) {
        self.task = task
        self.env = env
        self.sink = sink
        machine = FeedbackMachine(context: env.context, exerciseHint: task.hint)
        clock = AttemptClock(now: env.nowMs)
    }

    var isDone: Bool { machine.isDone }
    /// Checks, the final check and placement: the answer was recorded and nothing is shown, so the player moves
    /// straight on (docs/06 § Unit check).
    var movesOnWithoutFeedback: Bool { machine.isDone && feedback == nil }
    var canCheck: Bool {
        !response.trimmingCharacters(in: .whitespaces).isEmpty && !machine.isDone && !isShowingAnswer
            && !isHinted
    }
    var canRequestHint: Bool { machine.canRequestHint && visibleHint == nil }
    var canSayIt: Bool { env.canSpeak && task.format == .recall && !env.context.isAssessment }
    /// Token indices of the model answer to underline after a miss.
    var underlined: [Int] { lastGrade?.mismatches ?? [] }

    private var isHinted: Bool { if case .hinted = machine.state { true } else { false } }
    private var isShowingAnswer: Bool { if case .answerShown = machine.state { true } else { false } }

    /// The model answer as the learner should see it (their gender form; both forms joined for "both").
    var modelAnswer: String {
        guard let first = task.accepted.first else { return "" }
        return first.modelAnswer(profile: env.profile, style: .display).text
    }

    func insert(_ letter: String) { response += letter }

    /// "Show a hint" before answering (never in checks).
    func requestHint() {
        if let h = machine.requestHint() { visibleHint = h.text }
    }

    func check() {
        guard canCheck else { return }
        let grade = TypedAnswerGrader(knownForms: env.knownForms, profile: env.profile)
            .grade(response, accepted: task.accepted, near: task.near)
        lastGrade = grade
        lastSpoken = nil
        lastHeard = nil
        if let record = machine.submit(grade.answer) {
            emit(record, response: response, mode: .typed, skill: nil)
        }
        updateHint()
    }

    /// "Say it": the transcript is graded with TranscriptMatcher and recorded under skill `speak` (docs/06 §7).
    func submitSpoken(_ result: SpeechResult) {
        guard canSayIt, !machine.isDone else { return }
        let match = TranscriptMatcher(profile: env.profile).match(
            transcripts: result.allTranscripts,
            accepted: task.accepted)
        lastSpoken = match
        lastGrade = nil  // a typed grade from an earlier attempt must not label this one
        response = match?.heard ?? result.transcript
        lastHeard = response
        // A spoken miss has no hint kind: the learner may have said something else ("I heard: …", docs/09).
        if let record = machine.submit(match?.answer ?? GradedAnswer(outcome: .wrong)) {
            emit(record, response: response, mode: .spoken, skill: .speak)
        }
        updateHint()
    }

    func tryAgain() {
        machine.tryAgain()
        response = ""
        clock.restart()
    }

    func showAnswer() {
        if let record = machine.showAnswer() { emit(record, response: response, mode: .typed, skill: nil) }
    }

    /// "Continue" after the answer was shown.
    func acknowledge() { machine.acknowledgeAnswer() }

    private func updateHint() {
        switch machine.state {
        case .hinted(let h), .awaitingSecond(let h): visibleHint = h?.text
        default: break
        }
    }

    private func emit(_ r: FeedbackMachine.AttemptRecord, response: String, mode: AnswerMode, skill: Skill?) {
        let targets = task.targets.map {
            TargetOutcome(itemID: $0.itemId, skill: skill ?? $0.skill, outcome: r.outcome)
        }
        sink?.record(
            AttemptDraft(
                exerciseID: task.exerciseID, turnID: nil, format: task.format, attemptIndex: r.attemptIndex,
                outcome: r.outcome, targets: targets,
                response: response.isEmpty ? nil : ExercisePayload.clip(response, format: task.format), mode: mode,
                latencyMs: clock.latencyMs(), feedbackShown: r.feedbackShown))
    }

    /// The feedback panel for the current state, or nil while answering.
    var feedback: FeedbackPresentation? {
        switch machine.state {
        case .awaitingFirst, .awaitingSecond:
            return nil
        case .hinted(let hint):
            let detail = [lastHeard.map(FeedbackCopy.heard), hint?.text].compactMap { $0 }.joined(separator: "\n")
            return FeedbackPresentation(
                tone: .hint, headline: FeedbackCopy.headline(for: hint, kind: lastGrade?.hintKind),
                detail: detail.isEmpty ? nil : detail, answer: nil, rule: nil, canTryAgain: true,
                canShowAnswer: machine.canShowAnswer, canContinue: false)
        case .answerShown(let reason):
            return FeedbackPresentation(
                tone: .answer, headline: reason == .revealed ? FeedbackCopy.revealed : FeedbackCopy.failedTwice,
                detail: nil, answer: modelAnswer, rule: task.rule, canTryAgain: false, canShowAnswer: false,
                canContinue: true)
        case .done(let result):
            switch result {
            case .success:
                let note =
                    lastGrade?.outcome == .correctWithNote
                    ? (task.correctWithNoteText ?? lastGrade?.correction) : nil
                return FeedbackPresentation(
                    tone: .success, headline: note == nil ? FeedbackCopy.success : FeedbackCopy.successWithNote,
                    detail: note, answer: nil, rule: nil, canTryAgain: false, canShowAnswer: false, canContinue: true)
            case .successWithCorrection, .successAfterHint:
                return FeedbackPresentation(
                    tone: .success,
                    headline: result == .successAfterHint
                        ? FeedbackCopy.successAfterHint
                        : FeedbackCopy.successWithCorrection,
                    detail: lastGrade?.correction, answer: nil, rule: nil, canTryAgain: false, canShowAnswer: false,
                    canContinue: true)
            case .failed, .skipped:
                return env.context.isAssessment
                    ? nil
                    : FeedbackPresentation(
                        tone: .answer, headline: FeedbackCopy.failedTwice, detail: nil,
                        answer: modelAnswer, rule: task.rule, canTryAgain: false,
                        canShowAnswer: false, canContinue: true)
            case .recorded:
                return nil  // no feedback in assessments
            }
        }
    }
}

extension AttemptContext {
    /// Checks, the final check and placement: one attempt, no hints, no feedback until the end (docs/05).
    var isAssessment: Bool { self == .check || self == .final || self == .placement }
}

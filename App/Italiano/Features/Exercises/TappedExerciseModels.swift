import Foundation
import LearningCore
import Observation

// Choice, true-false, sound pairs, match, sentence building, dictation and repeat (docs/06 §1, §8–§11, building
// blocks). Platform-neutral view models; the SwiftUI views render them.

/// One option on screen.
struct ChoiceOption: Sendable, Equatable, Identifiable {
    let id: Int  // index as authored (the grading index)
    let text: String
    let italian: TokenizedText?
    let audioID: AudioID?
}

/// choice, true-false and sound-pair: pick one; a wrong first pick is marked and one more pick is allowed.
@MainActor
@Observable
final class ChoiceModel {
    let payload: ExercisePayload
    let options: [ChoiceOption]  // in display (seeded) order
    let correctIndex: Int
    private let env: ExerciseEnvironment
    private weak var sink: AttemptSink?
    private(set) var machine: FeedbackMachine
    private(set) var selected: Int?
    @ObservationIgnored private var clock: AttemptClock

    init?(payload: ExercisePayload, env: ExerciseEnvironment, sink: AttemptSink?) {
        var opts: [ChoiceOption]
        let answer: Int
        switch payload.body {
        case .choice(let c):
            opts = c.options.enumerated().map {
                ChoiceOption(
                    id: $0.offset, text: $0.element.text, italian: $0.element.it,
                    audioID: nil)
            }
            opts = c.displayOrder(exerciseID: payload.id).map { opts[$0] }
            answer = c.answer
        case .trueFalse(let t):
            opts = [
                ChoiceOption(id: 0, text: "True", italian: nil, audioID: nil),
                ChoiceOption(id: 1, text: "False", italian: nil, audioID: nil),
            ]
            answer = t.answer ? 0 : 1
        case .soundPair(let s):
            switch s.question {
            case .whichWord:
                guard let pair = s.pair, let play = s.play else { return nil }
                opts = pair.enumerated().map {
                    ChoiceOption(
                        id: $0.offset, text: $0.element.it, italian: nil,
                        audioID: $0.element.audioId)
                }
                answer = play
            case .singleOrDouble:
                opts = [
                    ChoiceOption(id: 0, text: "Single", italian: nil, audioID: nil),
                    ChoiceOption(id: 1, text: "Double", italian: nil, audioID: nil),
                ]
                answer = s.answer == .double ? 1 : 0
            }
        default:
            return nil
        }
        self.payload = payload
        options = opts
        correctIndex = answer
        self.env = env
        self.sink = sink
        machine = FeedbackMachine(context: env.context, exerciseHint: payload.hint)
        clock = AttemptClock(now: env.nowMs)
    }

    var isDone: Bool { machine.isDone }
    var markedWrong: [Int] { machine.markedWrongChoices }
    var hint: String? {
        switch machine.state {
        case .hinted(let h), .awaitingSecond(let h): h?.text
        default: nil
        }
    }

    /// The learner picks an option (by its authored index). Keys 1–6 map to `options[n-1].id` on Mac.
    func select(_ index: Int) {
        guard !machine.isDone, !markedWrong.contains(index) else { return }
        if case .hinted = machine.state { machine.tryAgain() }
        selected = index
        var graded = ChoiceGrader.grade(selected: index, answer: correctIndex)
        graded.selectedIndex = index
        if let record = machine.submit(graded) {
            sink?.record(
                AttemptDraft(
                    exerciseID: payload.id, turnID: nil, format: payload.format, attemptIndex: record.attemptIndex,
                    outcome: record.outcome, targets: payload.targetOutcomes(record.outcome),
                    response: options.first { $0.id == index }?.text, mode: .tapped, latencyMs: clock.latencyMs(),
                    feedbackShown: record.feedbackShown))
        }
        if case .answerShown = machine.state { machine.acknowledgeAnswer() }
    }

    func mark(for option: ChoiceOption) -> OptionCardMark {
        guard machine.isDone || !markedWrong.isEmpty else { return .idle }
        if markedWrong.contains(option.id) { return .wrong }
        if machine.isDone, option.id == correctIndex, !env.context.isAssessment { return .correct }
        return .idle
    }
}

/// Mirrors the OptionCard's mark without importing SwiftUI here.
enum OptionCardMark: Sendable, Equatable { case idle, correct, wrong }

/// match: pair the Italian (left) with the English (right). Each pair is graded on its own; a pair's outcome is
/// `correct` only if its first pairing was right (docs/05 § Other graders, Rating policy: per pair).
@MainActor
@Observable
final class MatchModel {
    let payload: ExercisePayload
    let pairs: [ExerciseBody.MatchPair]
    let leftOrder: [Int]
    let rightOrder: [Int]
    private let env: ExerciseEnvironment
    private weak var sink: AttemptSink?
    private(set) var selectedLeft: Int?
    private(set) var locked: [Int: Int] = [:]  // left → right (practice: locked when right)
    private(set) var firstTry: [Int: Bool] = [:]  // left → first pairing was right
    private(set) var assessmentPicks: [Int: Int] = [:]  // check mode: the learner's pairing, no feedback
    private(set) var lastWrong: (left: Int, right: Int)?
    private(set) var isDone = false
    @ObservationIgnored private var clock: AttemptClock

    init?(payload: ExercisePayload, env: ExerciseEnvironment, sink: AttemptSink?) {
        guard case .match(let m) = payload.body, m.pairs.count == payload.targets.count || payload.targets.isEmpty
        else { return nil }
        self.payload = payload
        pairs = m.pairs
        leftOrder = m.leftOrder(exerciseID: payload.id)
        rightOrder = m.rightOrder(exerciseID: payload.id)
        self.env = env
        self.sink = sink
        clock = AttemptClock(now: env.nowMs)
    }

    /// Check mode: pairings are collected without feedback and submitted together.
    var isAssessment: Bool { env.context.isAssessment }

    func tapLeft(_ i: Int) {
        guard !isDone, locked[i] == nil else { return }
        selectedLeft = i
    }

    func tapRight(_ j: Int) {
        guard !isDone, let i = selectedLeft else { return }
        selectedLeft = nil
        if env.context.isAssessment {
            assessmentPicks[i] = j
            return
        }
        guard !locked.values.contains(j) else { return }
        if firstTry[i] == nil { firstTry[i] = (i == j) }
        if i == j {
            locked[i] = j
            lastWrong = nil
            if locked.count == pairs.count {
                finish(pairOutcomes: (0..<pairs.count).map { firstTry[$0] == true ? .correct : .wrong })
            }
        } else {
            lastWrong = (i, j)
        }
    }

    /// Check mode: submit every pairing at once (unpaired = wrong).
    func submitAssessment() {
        guard env.context.isAssessment, !isDone else { return }
        let r = MatchGrader.grade(selections: assessmentPicks, pairCount: pairs.count)
        finish(pairOutcomes: r.pairOutcomes)
    }

    private func finish(pairOutcomes: [AttemptOutcome]) {
        isDone = true
        let outcome: AttemptOutcome = pairOutcomes.allSatisfy { $0 == .correct } ? .correct : .wrong
        let targets = payload.targets.enumerated().map {
            TargetOutcome(itemID: $0.element.itemId, skill: $0.element.skill, outcome: pairOutcomes[$0.offset])
        }
        sink?.record(
            AttemptDraft(
                exerciseID: payload.id, turnID: nil, format: .match, attemptIndex: 1, outcome: outcome,
                targets: targets,
                response: nil, mode: .tapped, latencyMs: clock.latencyMs(), feedbackShown: .none))
    }
}

/// sentence-building: tap tiles onto the answer line; the order must equal an accepted order (docs/06 §8).
@MainActor
@Observable
final class SentenceBuildingModel {
    struct Tile: Sendable, Equatable, Identifiable {
        let id: Int
        let word: String
    }

    let payload: ExercisePayload
    let tiles: [Tile]  // seeded order, never the answer order
    private let answers: [String]
    private let env: ExerciseEnvironment
    private weak var sink: AttemptSink?
    private(set) var placed: [Int] = []  // tile ids on the answer line
    private(set) var machine: FeedbackMachine
    private(set) var lastResult: OrderGrader.Result?
    @ObservationIgnored private var clock: AttemptClock

    init?(payload: ExercisePayload, env: ExerciseEnvironment, sink: AttemptSink?) {
        guard case .sentenceBuilding(let s) = payload.body else { return nil }
        self.payload = payload
        tiles = s.shuffledTiles(exerciseID: payload.id).enumerated().map { Tile(id: $0.offset, word: $0.element) }
        answers = s.answers
        self.env = env
        self.sink = sink
        machine = FeedbackMachine(context: env.context, exerciseHint: payload.hint)
        clock = AttemptClock(now: env.nowMs)
    }

    var available: [Tile] { tiles.filter { !placed.contains($0.id) } }
    var answerLine: [Tile] { placed.compactMap { id in tiles.first { $0.id == id } } }
    /// The first misplaced tile, after a miss in practice (never in assessments: no feedback there).
    var highlighted: Int? {
        guard !env.context.isAssessment else { return nil }
        return lastResult?.firstMisplaced.flatMap { $0 < placed.count ? placed[$0] : nil }
    }
    var isDone: Bool { machine.isDone }

    func place(_ id: Int) { if !placed.contains(id) && !machine.isDone { placed.append(id) } }
    func remove(_ id: Int) { placed.removeAll { $0 == id } }

    /// VoiceOver "Move left" / "Move right" actions on placed tiles.
    func move(_ id: Int, by delta: Int) {
        guard let i = placed.firstIndex(of: id) else { return }
        let j = min(max(i + delta, 0), placed.count - 1)
        placed.swapAt(i, j)
    }

    /// Punctuation and capitals are added in the displayed result (docs/06 §8).
    var displayedSentence: String {
        let s = answerLine.map(\.word).joined(separator: " ")
        guard let first = s.first else { return "" }
        return first.uppercased() + s.dropFirst() + "."
    }

    func check() {
        guard !placed.isEmpty, !machine.isDone else { return }
        if case .hinted = machine.state { machine.tryAgain() }
        let r = OrderGrader.grade(placed: answerLine.map(\.word), accepted: answers)
        lastResult = r
        if let record = machine.submit(r.answer) {
            sink?.record(
                AttemptDraft(
                    exerciseID: payload.id, turnID: nil, format: .sentenceBuilding, attemptIndex: record.attemptIndex,
                    outcome: record.outcome, targets: payload.targetOutcomes(record.outcome),
                    response: answerLine.map(\.word).joined(separator: " "), mode: .tapped,
                    latencyMs: clock.latencyMs(),
                    feedbackShown: record.feedbackShown))
        }
    }

    func showAnswer() {
        if let record = machine.showAnswer() {
            sink?.record(
                AttemptDraft(
                    exerciseID: payload.id, turnID: nil, format: .sentenceBuilding, attemptIndex: record.attemptIndex,
                    outcome: record.outcome, targets: payload.targetOutcomes(record.outcome), response: nil,
                    mode: .tapped, latencyMs: clock.latencyMs(), feedbackShown: record.feedbackShown))
        }
    }

    var modelAnswer: String { answers.first ?? "" }
}

/// dictation: listen, type what you hear; a word-by-word diff marks correct, accent, doubling, typo or wrong.
@MainActor
@Observable
final class DictationModel {
    let payload: ExercisePayload
    let say: TokenizedText
    let audioID: AudioID?
    let plays: Int?
    let offersSlower: Bool
    private let env: ExerciseEnvironment
    private weak var sink: AttemptSink?
    var response = ""
    private(set) var playsUsed = 0
    private(set) var machine: FeedbackMachine
    private(set) var result: DictationGrader.Result?
    @ObservationIgnored private var clock: AttemptClock

    init?(payload: ExercisePayload, env: ExerciseEnvironment, sink: AttemptSink?) {
        guard case .dictation(let d) = payload.body else { return nil }
        self.payload = payload
        say = d.say
        audioID = d.audioId
        plays = d.plays
        offersSlower = d.slow
        self.env = env
        self.sink = sink
        machine = FeedbackMachine(context: env.context, exerciseHint: payload.hint)
        clock = AttemptClock(now: env.nowMs)
    }

    /// "5 words · from the story" (docs/06 §9).
    var hintLine: String {
        let n = say.tokens.filter { $0.kind != .punct }.count
        return payload.source != nil ? "\(n) words · from the story" : "\(n) words"
    }

    var canPlay: Bool { audioID != nil && (plays.map { playsUsed < $0 } ?? true) }
    func didPlay() { playsUsed += 1 }
    func insert(_ letter: String) { response += letter }
    var isDone: Bool { machine.isDone }

    func check() {
        guard !response.trimmingCharacters(in: .whitespaces).isEmpty, !machine.isDone else { return }
        if case .hinted = machine.state { machine.tryAgain() }
        let r = DictationGrader.grade(target: say.text, response: response, knownForms: env.knownForms)
        result = r
        if let record = machine.submit(GradedAnswer(outcome: r.outcome)) {
            sink?.record(
                AttemptDraft(
                    exerciseID: payload.id, turnID: nil, format: .dictation, attemptIndex: record.attemptIndex,
                    outcome: record.outcome, targets: payload.targetOutcomes(record.outcome),
                    response: ExercisePayload.clip(response, format: .dictation), mode: .typed,
                    latencyMs: clock.latencyMs(), feedbackShown: record.feedbackShown))
        }
    }

    func tryAgain() {
        machine.tryAgain()
        clock.restart()
    }

    /// The note for a doubling slip: "Listen again: cornetto has a double t".
    var doublingNote: String? {
        guard !env.context.isAssessment, let w = result?.words.first(where: { $0.mark == .doubling }),
            let c = w.consonant
        else { return nil }
        return w.targetIsDouble == false
            ? "Listen again: \(w.expected) has a single \(c)."
            : "Listen again: \(w.expected) has a double \(c)."
    }
}

/// repeat: hear the model, speak, see "I heard: …". Without speech recognition the screen is listen-and-repeat,
/// ungraded (docs/06 §11). A failed attempt never becomes a lapse (ADR-08).
@MainActor
@Observable
final class RepeatModel {
    let payload: ExercisePayload
    let say: TokenizedText
    let audioID: AudioID?
    private let accept: [AnswerPattern]
    let env: ExerciseEnvironment
    private weak var sink: AttemptSink?
    private(set) var heard: String?
    private(set) var passed: Bool?
    private(set) var attempts = 0
    private(set) var isDone = false
    @ObservationIgnored private var clock: AttemptClock

    init?(payload: ExercisePayload, env: ExerciseEnvironment, sink: AttemptSink?) {
        guard case .repeat(let r) = payload.body, let pattern = try? r.accept.parsed() else { return nil }
        self.payload = payload
        say = r.say
        audioID = r.audioId
        accept = [pattern]
        self.env = env
        self.sink = sink
        clock = AttemptClock(now: env.nowMs)
    }

    /// Listen-and-repeat when the device can't recognise speech.
    var isListenOnly: Bool { !env.canSpeak }

    func submit(_ result: SpeechResult) {
        guard !isDone, env.canSpeak else { return }
        attempts += 1
        let m = TranscriptMatcher(profile: env.profile).match(transcripts: result.allTranscripts, accepted: accept)
        heard = m?.heard ?? result.transcript
        passed = m?.passed ?? false
        record(outcome: passed == true ? .correct : .wrong)
        if passed == true { isDone = true }
    }

    /// "Skip — can't speak now".
    func skip() {
        guard !isDone else { return }
        if env.canSpeak { record(outcome: .skipped) }
        isDone = true
    }

    /// Continue (after a pass, after giving up, or in listen-and-repeat mode).
    func finish() { isDone = true }

    private func record(outcome: AttemptOutcome) {
        sink?.record(
            AttemptDraft(
                exerciseID: payload.id, turnID: nil, format: .repeat, attemptIndex: min(attempts, 2), outcome: outcome,
                targets: payload.targetOutcomes(outcome), response: nil, mode: .spoken, latencyMs: clock.latencyMs(),
                feedbackShown: .none))
        clock.restart()
    }
}

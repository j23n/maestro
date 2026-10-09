import Foundation
import LearningCore

/// The Debug menu's auto-answer (task M6.3; docs/02 § App configuration): answers the exercise on screen the way a
/// learner would, through the exercise's own view model, so the real graders, the feedback machine and the attempt
/// events all run. UI tests use it to get through a unit quickly (`debug.autoAnswer`, `debug.autoAnswerWrong`,
/// `debug.autoAdvance` in the players' debug bar, shown with `-ITAAutoAnswer` or the Debug menu's switch). Builds
/// without the Debug menu never show the bar, so nothing here can run in Release or Study builds.
///
/// A correct answer is built from the exercise's own model answers and correct indices, and kept only when the
/// exercise's grader accepts it for this learner (their forms, name and country), so it never depends on how a
/// pattern happens to be written. Speaking formats get the transcript the simulated recogniser would hand over
/// ("Simulate speech by typing"), or a typed answer where the exercise allows typing.
@MainActor
enum AutoAnswer {
    enum Mode: Sendable, Equatable {
        /// The right answer (after "Try again" when a first attempt missed).
        case correct
        /// One wrong attempt: the first one shows the hint, a second one the answer.
        case wrong
    }

    /// Words that fill a pattern's open slots (`{NAME}`, `{ME.home}`…) when the learner gave nothing to fill them.
    /// Not Italian: a slot left open accepts any word.
    static let slotFiller = "Alex"
    /// A wrong answer for every typed format: no Italian word, no number, no pattern accepts it.
    static let wrongText = "zzz"

    /// Answers once in `mode`. Returns false when there was nothing to answer (the exercise was already done, or
    /// it can't be answered that way, such as a wrong pick when every wrong option is already marked).
    @discardableResult
    static func answer(_ host: ExerciseHostModel, _ mode: Mode) -> Bool {
        switch host {
        case .typed(let m): typed(m, mode)
        case .choice(let m): choice(m, mode)
        case .match(let m): match(m, mode)
        case .building(let m): building(m, mode)
        case .dictation(let m): dictation(m, mode)
        case .repeatAfterMe(let m): repeatAfterMe(m, mode)
        case .conversation(let m): conversation(m, mode)
        case .talk(let m): talk(m, mode)
        case .writing(let m): writing(m, mode)
        case .relay(let m): relay(m, mode)
        }
    }

    /// The debug bar's "Answer" buttons: answers, then continues when the exercise ends without anything on screen
    /// to continue from (a typed answer in a check moves straight on, as its view does after Check).
    static func answerOnPage(_ host: ExerciseHostModel?, _ mode: Mode, advance: () -> Void) {
        guard let host else { return }
        answer(host, mode)
        if host.movesOnWithoutFeedback { advance() }
    }

    /// The debug bar's "Answer and continue": answers the exercise on screen correctly when it is still open, then
    /// moves to the next page. Content pages (story, note, meet cards…) simply move on.
    static func answerAndContinue(_ host: ExerciseHostModel?, advance: () -> Void) {
        if let host, !host.isDone {
            answer(host, .correct)
            if !host.isDone { answer(host, .correct) }  // a shown answer is acknowledged on the second call
        }
        advance()
    }

    // MARK: - Typed formats

    private static func typed(_ m: TypedExerciseModel, _ mode: Mode) -> Bool {
        switch m.machine.state {
        case .done:
            return false
        case .answerShown:
            guard mode == .correct else { return false }
            m.acknowledge()
            return true
        case .hinted:
            m.tryAgain()
        case .awaitingFirst, .awaitingSecond:
            break
        }
        let grader = TypedAnswerGrader(knownForms: m.env.knownForms, profile: m.env.profile)
        let text: String
        switch mode {
        case .wrong:
            text = wrongText
        case .correct:
            guard
                let right = correctText(
                    patterns: m.task.accepted, profile: m.env.profile,
                    grade: {
                        grader.grade($0, accepted: m.task.accepted, near: m.task.near).outcome
                    })
            else { return false }
            text = right
        }
        m.response = text
        m.check()
        return true
    }

    private static func dictation(_ m: DictationModel, _ mode: Mode) -> Bool {
        guard !m.isDone else { return false }
        if case .answerShown = m.machine.state { return false }
        if case .hinted = m.machine.state { m.tryAgain() }
        m.response = mode == .correct ? m.say.text : wrongText
        m.check()
        return true
    }

    private static func relay(_ m: RelayModel, _ mode: Mode) -> Bool {
        guard !m.isDone, let answer = m.relay.answerEn.graderAnswer else { return false }
        if case .answerShown = m.machine.state { return false }
        if case .hinted = m.machine.state { m.tryAgain() }
        switch mode {
        case .wrong:
            m.response = wrongText
        case .correct:
            guard let text = relayCandidates(m).first(where: { EnglishAnswerGrader.isCorrect($0, answer: answer) })
            else { return false }
            m.response = text
        }
        m.check()
        return true
    }

    private static func relayCandidates(_ m: RelayModel) -> [String] {
        let a = m.relay.answerEn
        var out = [m.answerText].compactMap { $0 }
        switch (a.type, a.value) {
        case (.price, .number(let v)?): out += [String(format: "%.2f", v), String(v)]
        case (.number, .number(let v)?): out += [String(Int(v.rounded()))]
        case (_, .string(let s)?): out += [s]
        default: break
        }
        return out + (a.accept ?? [])
    }

    // MARK: - Tapped formats

    private static func choice(_ m: ChoiceModel, _ mode: Mode) -> Bool {
        guard !m.isDone else { return false }
        switch mode {
        case .correct:
            m.select(m.correctIndex)
        case .wrong:
            guard let wrong = m.options.first(where: { $0.id != m.correctIndex && !m.markedWrong.contains($0.id) })
            else { return false }
            m.select(wrong.id)
        }
        return true
    }

    private static func match(_ m: MatchModel, _ mode: Mode) -> Bool {
        guard !m.isDone else { return false }
        let n = m.pairs.count
        if m.isAssessment {
            // Check mode: every pairing is collected, then submitted together.
            for i in 0..<n {
                m.tapLeft(i)
                m.tapRight(mode == .correct || n < 2 ? i : (i + 1) % n)
            }
            m.submitAssessment()
            return true
        }
        let open = (0..<n).filter { m.locked[$0] == nil }
        switch mode {
        case .correct:
            for i in open {
                m.tapLeft(i)
                m.tapRight(i)
            }
        case .wrong:
            // One wrong pairing: that pair's outcome is `wrong` however it is matched afterwards.
            guard let i = open.first, let j = open.first(where: { $0 != i }) else { return false }
            m.tapLeft(i)
            m.tapRight(j)
        }
        return true
    }

    private static func building(_ m: SentenceBuildingModel, _ mode: Mode) -> Bool {
        guard !m.isDone else { return false }
        if case .answerShown = m.machine.state { return false }
        for tile in m.answerLine { m.remove(tile.id) }
        guard let order = tileOrder(m, mode) else { return false }
        order.forEach { m.place($0) }
        m.check()
        return true
    }

    /// Tile IDs spelling the first accepted order, or (wrong) that order reversed when no answer accepts it.
    private static func tileOrder(_ m: SentenceBuildingModel, _ mode: Mode) -> [Int]? {
        guard case .sentenceBuilding(let s) = m.payload.body, let answer = s.answers.first else { return nil }
        var free = m.tiles
        var ids: [Int] = []
        for word in answer.split(separator: " ").map(String.init) {
            guard let i = free.firstIndex(where: { $0.word == word }) else { return nil }
            ids.append(free.remove(at: i).id)
        }
        guard mode == .wrong else { return ids }
        let reversed = Array(ids.reversed())
        let words = reversed.compactMap { id in m.tiles.first { $0.id == id }?.word }.joined(separator: " ")
        if !s.answers.contains(words) { return reversed }
        return ids.count > 1 ? Array(ids.dropLast()) : nil  // a palindrome: leave a word out instead
    }

    // MARK: - Speaking formats

    private static func repeatAfterMe(_ m: RepeatModel, _ mode: Mode) -> Bool {
        guard !m.isDone else { return false }
        guard !m.isListenOnly else {
            // Listen-and-repeat without speech recognition: ungraded, Continue ends it (docs/06 §11).
            m.finish()
            return true
        }
        let matcher = TranscriptMatcher(profile: m.env.profile, letterNames: m.env.letterNames)
        var patterns: [AnswerPattern] = []
        if case .repeat(let r) = m.payload.body, let p = try? r.accept.parsed() { patterns = [p] }
        let heard: String
        switch mode {
        case .wrong:
            heard = wrongText
        case .correct:
            let candidates = [m.say.text] + patterns.flatMap { candidateTexts($0, profile: m.env.profile) }
            heard =
                candidates.first { matcher.match(transcripts: [$0], accepted: patterns)?.passed == true } ?? m.say.text
        }
        m.submit(spoken(heard))
        return true
    }

    private static func conversation(_ m: ConversationModel, _ mode: Mode) -> Bool {
        guard !m.isFinished else { return false }
        switch mode {
        case .wrong:
            say(wrongText, in: m)
            return true
        case .correct:
            // Turn after turn to an end node, taking the branch that ticks a goal not yet ticked.
            var turns = 0
            while !m.isFinished, turns < 40, let node = m.node {
                turns += 1
                let open = node.expect.first { $0.goal.map { !m.goalsDone.contains($0) } ?? false }
                guard let text = conversationAnswer(m, preferring: open ?? node.expect.first) else { return turns > 1 }
                say(text, in: m)
            }
            return true
        }
    }

    /// A line the node accepts for an intent: typed when typing is allowed, else as the recogniser would hear it.
    private static func conversationAnswer(
        _ m: ConversationModel, preferring first: ExerciseBody.Expectation?
    ) -> String? {
        let grader = TypedAnswerGrader(knownForms: m.env.knownForms, profile: m.env.profile)
        let matcher = TranscriptMatcher(profile: m.env.profile, letterNames: m.env.letterNames)
        let intents = [first].compactMap { $0 } + (m.node?.expect ?? [])
        for intent in intents {
            let patterns = intent.accept.compactMap { try? $0.parsed() }
            let found = correctText(patterns: patterns, profile: m.env.profile) { text in
                if m.canType { return grader.grade(text, accepted: patterns).outcome }
                return matcher.match(transcripts: [text], accepted: patterns)?.passed == true ? .correct : .wrong
            }
            if let found { return found }
        }
        return nil
    }

    private static func say(_ text: String, in m: ConversationModel) {
        if m.canType {
            m.response = text
            m.submitTyped()
        } else {
            m.submitSpoken(spoken(text))
        }
    }

    private static func talk(_ m: TalkModel, _ mode: Mode) -> Bool {
        guard !(m.isAssessment && m.result != nil) else { return false }
        if mode == .correct, m.result?.passed == true { return false }
        let spokenAnswer = m.env.canSpeak || !m.canType
        let text: String
        switch mode {
        case .wrong:
            text = wrongText
        case .correct:
            let points = m.talk.points.compactMap { try? $0.matcherPoint() }
            let matcher = ContentPointMatcher(profile: m.env.profile, letterNames: m.env.letterNames)
            let candidates = [m.talk.model.text, joinedPoints(m.talk.points, profile: m.env.profile)]
            text =
                candidates.first {
                    matcher.match(response: $0, points: points, pass: m.talk.pass, spoken: spokenAnswer).passed
                } ?? m.talk.model.text
        }
        if spokenAnswer { m.submitSpoken(spoken(text)) } else { m.submit(transcript: text, mode: .typed) }
        return true
    }

    // MARK: - Writing

    private static func writing(_ m: WritingModel, _ mode: Mode) -> Bool {
        guard !(m.isAssessment && m.submitted) else { return false }
        // Practice allows another submission, but not once everything was right.
        let passed = m.isForm ? m.credit == 1 : (m.result?.passed == true && m.wordCountOK)
        if mode == .correct, m.submitted, passed { return false }
        if m.isForm, let fields = m.writing.fields {
            m.fieldValues = fields.map { mode == .correct ? fieldValue($0, env: m.env) : "" }
        } else {
            m.text = mode == .correct ? freeText(m) : wrongText
        }
        m.submit()
        return true
    }

    /// A value the field's check accepts: its pattern's answer, or one that fits the field's type.
    private static func fieldValue(_ field: ExerciseBody.FormField, env: ExerciseEnvironment) -> String {
        let patterns = (field.accept ?? []).compactMap { try? $0.parsed() }
        if !patterns.isEmpty {
            return correctText(patterns: patterns, profile: env.profile) {
                WritingModel.validate($0, field: field, env: env) ? .correct : .wrong
            } ?? slotFiller
        }
        switch field.type {
        case .email: return "alex@example.com"
        case .number, .phone: return "3331234567"
        case .date: return "1/1/2000"
        case .text: return learnerName(env.profile)
        }
    }

    private static func freeText(_ m: WritingModel) -> String {
        let points = (m.writing.points ?? []).compactMap { try? $0.matcherPoint() }
        let matcher = ContentPointMatcher(profile: m.env.profile)
        let candidates = [m.writing.model?.text, joinedPoints(m.writing.points ?? [], profile: m.env.profile)]
            .compactMap { $0 }
        return candidates.first { text in
            let words = WritingChecker.wordCount(text)
            let fits = m.writing.words.map { ($0.min...$0.max).contains(words) } ?? true
            return fits && matcher.match(response: text, points: points, pass: m.writing.pass ?? 0).passed
        } ?? candidates.first ?? wrongText
    }

    // MARK: - Answers from patterns

    /// The first candidate the grader marks `correct`, else the first it accepts at all (`correctWithNote`,
    /// `almost`), else nil.
    static func correctText(
        patterns: [AnswerPattern], profile: LearnerProfile, grade: (String) -> AttemptOutcome
    ) -> String? {
        var fallback: String?
        var tried: Set<String> = []
        for pattern in patterns {
            for text in candidateTexts(pattern, profile: profile) where tried.insert(text).inserted {
                let outcome = grade(text)
                if outcome == .correct { return text }
                if fallback == nil, outcome.isSuccess { fallback = text }
            }
        }
        return fallback
    }

    /// The pattern's model answer for this learner, then every expansion they may give, with open slots filled.
    static func candidateTexts(_ pattern: AnswerPattern, profile: LearnerProfile) -> [String] {
        let model = pattern.modelAnswer(profile: profile, style: .canonical).text
        let expansions = pattern.expansions(profile: profile).filter { profile.accepts($0.gender) }.map(\.raw)
        return ([model] + expansions).map { fillSlots($0, profile: profile) }
    }

    /// Open slots get the learner's own answer where there is one, a number for `{NUMBER}`, a filler otherwise.
    static func fillSlots(_ text: String, profile: LearnerProfile) -> String {
        var out = text.replacingOccurrences(of: AnswerPattern.numberPlaceholder, with: "3")
        for slot in PatternSlot.allCases {
            let value: String
            switch slot {
            case .name: value = learnerName(profile)
            case .number: value = "3"
            case .nationality:
                value = profile.country.map { profile.forms == .f ? $0.nationalityF : $0.nationalityM } ?? slotFiller
            case .home: value = profile.country?.homePhrase ?? slotFiller
            case .country: value = profile.country?.nameIt ?? slotFiller
            }
            out = out.replacingOccurrences(of: slot.placeholder, with: value)
        }
        return out
    }

    /// The learner's name, or the filler when they gave none.
    private static func learnerName(_ profile: LearnerProfile) -> String {
        let name = profile.name?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return name.isEmpty ? slotFiller : name
    }

    /// Each point's first accepted answer, as sentences: content that ticks every point (talk, free writing).
    private static func joinedPoints(_ points: [ExerciseBody.Point], profile: LearnerProfile) -> String {
        points.compactMap { point in
            point.accept.lazy.compactMap { try? $0.parsed() }.first.flatMap {
                candidateTexts($0, profile: profile).first
            }
        }.joined(separator: ". ")
    }

    /// What `SimulatedSpeechRecognizer` hands over for typed "speech".
    private static func spoken(_ text: String) -> SpeechResult {
        SpeechResult(transcript: text, alternatives: [], confidence: nil)
    }
}

extension ExerciseHostModel {
    /// The exercise ended and its view shows nothing to continue from, so the player moves on by itself: a typed
    /// answer in a check, the final check or placement (docs/06 § Unit check).
    var movesOnWithoutFeedback: Bool {
        if case .typed(let m) = self { return m.movesOnWithoutFeedback }
        return false
    }
}

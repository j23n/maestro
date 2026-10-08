import Foundation
import Testing

@testable import LearningCore

/// docs/05 § Stepped feedback: every transition of the diagram, the hint order, tapped formats, single-attempt
/// contexts, and the `attempt` fields (attemptIndex, outcome, feedbackShown) each graded answer produces.
@Suite struct FeedbackMachineTests {
    typealias Machine = FeedbackMachine
    typealias Record = FeedbackMachine.AttemptRecord

    static let correct = GradedAnswer(outcome: .correct)
    static let withNote = GradedAnswer(outcome: .correctWithNote, hintKind: .spelling, mismatches: [2])
    static let almost = GradedAnswer(outcome: .almost, hintKind: .spelling, mismatches: [2])
    static let wrong = GradedAnswer(outcome: .wrong, hintKind: .ending, mismatches: [1])

    // MARK: awaitingFirst

    @Test(arguments: [AttemptContext.lesson, .review])
    func firstCorrectIsSuccess(_ context: AttemptContext) {
        for answer in [Self.correct, Self.withNote] {
            var m = Machine(context: context)
            #expect(m.state == .awaitingFirst)
            #expect(m.submit(answer) == Record(attemptIndex: 1, outcome: answer.outcome, feedbackShown: .none))
            #expect(m.state == .done(.success))
            #expect(m.lastAnswer == answer)
            #expect(m.isDone)
        }
    }

    @Test func firstAlmostIsSuccessWithCorrection() {
        var m = Machine(context: .lesson)
        #expect(m.submit(Self.almost) == Record(attemptIndex: 1, outcome: .almost, feedbackShown: .none))
        #expect(m.state == .done(.successWithCorrection))
    }

    @Test func firstWrongIsHinted() {
        var m = Machine(context: .lesson)
        #expect(m.submit(Self.wrong) == Record(attemptIndex: 1, outcome: .wrong, feedbackShown: .none))
        #expect(m.state == .hinted(.generic(.ending)))
        #expect(m.lastAnswer?.mismatches == [1])
        #expect(m.canShowAnswer)
    }

    // MARK: hinted → awaitingSecond

    @Test func tryAgainThenSecondAttempt() {
        for second in [Self.correct, Self.withNote, Self.almost] {
            var m = Machine(context: .review, exerciseHint: "Cappuccino is masculine.")
            m.submit(Self.wrong)
            m.tryAgain()
            #expect(m.state == .awaitingSecond(.exercise("Cappuccino is masculine.")))
            #expect(m.submit(second) == Record(attemptIndex: 2, outcome: second.outcome, feedbackShown: .hint))
            #expect(m.state == .done(.successAfterHint))
        }
    }

    @Test func secondWrongShowsTheAnswerThenFails() {
        var m = Machine(context: .lesson)
        m.submit(Self.wrong)
        m.tryAgain()
        #expect(m.submit(Self.wrong) == Record(attemptIndex: 2, outcome: .wrong, feedbackShown: .hint))
        #expect(m.state == .answerShown(.missedTwice))
        #expect(!m.canShowAnswer)
        #expect(m.submit(Self.correct) == nil)  // no third attempt
        m.acknowledgeAnswer()
        #expect(m.state == .done(.failed))
    }

    @Test func answeringStraightFromHintedCountsAsTheSecondAttempt() {
        var m = Machine(context: .lesson)
        m.submit(Self.wrong)
        #expect(m.submit(Self.correct)?.attemptIndex == 2)
        #expect(m.state == .done(.successAfterHint))
    }

    // MARK: Show answer (any time)

    @Test func showAnswerBeforeAnswering() {
        var m = Machine(context: .lesson)
        #expect(m.showAnswer() == Record(attemptIndex: 1, outcome: .revealed, feedbackShown: .answer))
        #expect(m.state == .answerShown(.revealed))
        #expect(m.showAnswer() == nil)
        m.acknowledgeAnswer()
        #expect(m.state == .done(.failed))
    }

    @Test func showAnswerAfterAHint() {
        var hinted = Machine(context: .lesson)
        hinted.submit(Self.wrong)
        #expect(hinted.showAnswer() == Record(attemptIndex: 2, outcome: .revealed, feedbackShown: .answer))
        #expect(hinted.state == .answerShown(.revealed))

        var second = Machine(context: .lesson)
        second.submit(Self.wrong)
        second.tryAgain()
        #expect(second.showAnswer()?.attemptIndex == 2)
        second.acknowledgeAnswer()
        #expect(second.state == .done(.failed))
    }

    @Test func aRevealedOutcomeIsShowAnswer() {
        var m = Machine(context: .lesson)
        #expect(m.submit(GradedAnswer(outcome: .revealed))?.outcome == .revealed)
        #expect(m.state == .answerShown(.revealed))
    }

    @Test func nothingHappensOnceDone() {
        var m = Machine(context: .lesson)
        m.submit(Self.correct)
        #expect(m.submit(Self.wrong) == nil)
        #expect(m.showAnswer() == nil)
        #expect(m.skip() == nil)
        m.tryAgain()
        m.acknowledgeAnswer()
        #expect(m.state == .done(.success))
        #expect(m.requestHint() == nil)
    }

    // MARK: Hints

    @Test func hintOrderIsNearMissThenExerciseThenGeneric() {
        let near = GradedAnswer(outcome: .wrong, hintKind: .ending, nearHint: "Una is for feminine nouns.")
        var a = Machine(context: .lesson, exerciseHint: "Cappuccino is masculine.")
        a.submit(near)
        #expect(a.state == .hinted(.nearMiss("Una is for feminine nouns.")))

        var b = Machine(context: .lesson, exerciseHint: "Cappuccino is masculine.")
        b.submit(Self.wrong)
        #expect(b.state == .hinted(.exercise("Cappuccino is masculine.")))

        var c = Machine(context: .lesson, exerciseHint: "")
        c.submit(Self.wrong)
        #expect(c.state == .hinted(.generic(.ending)))
        #expect(Machine.Hint.generic(.ending).text == "Check the ending.")
    }

    @Test func genericHintsByFirstMismatch() {
        let expected: [HintKind: String] = [
            .realWord: "That's a real word, but not the one we need here.",
            .spelling: "Check the spelling.",
            .ending: "Check the ending.",
            .missing: "Something's missing.",
            .extra: "There's an extra word.",
        ]
        for kind in HintKind.allCases {
            var m = Machine(context: .lesson)
            m.submit(GradedAnswer(outcome: .wrong, hintKind: kind))
            #expect(m.state == .hinted(.generic(kind)))
            #expect(Machine.Hint.generic(kind).text == expected[kind])
        }
    }

    @Test func typedGradeDrivesTheHint() throws {
        let forms = KnownForms(["te": ["w:te"], "tè": ["w:te~tea"]])
        let grade = TypedAnswerGrader(knownForms: forms).grade(
            "vorrei un te", accepted: try AnswerPattern("vorrei un tè"))
        var m = Machine(context: .lesson)
        m.submit(grade.answer)
        #expect(m.state == .hinted(.generic(.realWord)))
        #expect(m.lastAnswer?.mismatches == [2])
    }

    @Test func requestingAHintBeforeAnswering() {
        var m = Machine(context: .lesson, exerciseHint: "Spremuta ends in -a.")
        #expect(m.canRequestHint)
        #expect(m.requestHint() == .exercise("Spremuta ends in -a."))
        #expect(m.hintRequested)
        #expect(!m.canRequestHint)
        #expect(m.state == .awaitingFirst)
        #expect(m.submit(Self.correct) == Record(attemptIndex: 1, outcome: .correct, feedbackShown: .hint))

        var none = Machine(context: .lesson)
        #expect(!none.canRequestHint)
        #expect(none.requestHint() == nil)
        #expect(none.submit(Self.wrong)?.feedbackShown == FeedbackMachine.FeedbackShown.none)
    }

    // MARK: Tapped formats

    @Test func tappedWrongChoiceIsMarkedAndOneMoreChoiceAllowed() {
        var m = Machine(context: .lesson, exerciseHint: "Listen for the double c.")
        #expect(
            m.submit(ChoiceGrader.grade(selected: 2, answer: 0))
                == Record(attemptIndex: 1, outcome: .wrong, feedbackShown: .none))
        #expect(m.markedWrongChoices == [2])
        #expect(m.state == .hinted(.exercise("Listen for the double c.")))
        m.tryAgain()
        #expect(m.submit(ChoiceGrader.grade(selected: 0, answer: 0))?.attemptIndex == 2)
        #expect(m.state == .done(.successAfterHint))

        var twice = Machine(context: .review)
        twice.submit(ChoiceGrader.grade(selected: 1, answer: 0))
        #expect(twice.state == .hinted(nil))  // no authored hint, and choices have no mismatch kind
        twice.tryAgain()
        twice.submit(ChoiceGrader.grade(selected: 2, answer: 0))
        #expect(twice.markedWrongChoices == [1, 2])
        #expect(twice.state == .answerShown(.missedTwice))
    }

    // MARK: Check, final and placement: one attempt, no hint, no "Show answer"

    /// No feedback in assessments (docs/06 § Unit check): every answer is recorded with its outcome and the
    /// machine ends in `done(recorded)`, never in a state the UI would show as right or wrong.
    @Test(arguments: [AttemptContext.check, .final, .placement])
    func singleAttemptContexts(_ context: AttemptContext) {
        var wrong = Machine(context: context, exerciseHint: "A hint.")
        #expect(wrong.isSingleAttempt)
        #expect(!wrong.canRequestHint)
        #expect(wrong.requestHint() == nil)
        #expect(!wrong.canShowAnswer)
        #expect(wrong.showAnswer() == nil)
        #expect(wrong.submit(Self.wrong) == Record(attemptIndex: 1, outcome: .wrong, feedbackShown: .none))
        #expect(wrong.state == .done(.recorded))
        #expect(wrong.markedWrongChoices.isEmpty)
        #expect(wrong.submit(Self.correct) == nil)

        for answer in [Self.correct, Self.withNote, Self.almost, ChoiceGrader.grade(selected: 1, answer: 0)] {
            var m = Machine(context: context)
            #expect(m.submit(answer) == Record(attemptIndex: 1, outcome: answer.outcome, feedbackShown: .none))
            #expect(m.state == .done(.recorded))
            #expect(m.lastAnswer == answer)
            #expect(m.markedWrongChoices.isEmpty)
        }
    }

    // MARK: Skip (speaking)

    @Test func skipEndsWithSkipped() {
        var m = Machine(context: .lesson)
        #expect(m.skip() == Record(attemptIndex: 1, outcome: .skipped, feedbackShown: .none))
        #expect(m.state == .done(.skipped))

        var after = Machine(context: .lesson)
        after.submit(Self.wrong)
        after.tryAgain()
        #expect(
            after.submit(GradedAnswer(outcome: .skipped))
                == Record(attemptIndex: 2, outcome: .skipped, feedbackShown: .hint))
        #expect(after.state == .done(.skipped))
    }

    @Test func skipStraightFromHinted() {
        var m = Machine(context: .lesson, exerciseHint: "Say it with un.")
        m.submit(Self.wrong)
        #expect(m.state == .hinted(.exercise("Say it with un.")))
        #expect(m.skip() == Record(attemptIndex: 2, outcome: .skipped, feedbackShown: .hint))
        #expect(m.state == .done(.skipped))
        #expect(m.skip() == nil)
    }

    // MARK: "Show a hint" after a miss

    @Test func requestingAHintAfterAMissReturnsTheHintOnScreen() {
        var m = Machine(context: .lesson, exerciseHint: "Cappuccino is masculine.")
        m.submit(Self.wrong)
        #expect(m.requestHint() == .exercise("Cappuccino is masculine."))
        #expect(m.state == .hinted(.exercise("Cappuccino is masculine.")))
        #expect(!m.canRequestHint)
        #expect(!m.hintRequested)  // only "Show a hint" before answering sets it
        m.tryAgain()
        #expect(m.requestHint() == .exercise("Cappuccino is masculine."))
        #expect(m.state == .awaitingSecond(.exercise("Cappuccino is masculine.")))
        #expect(m.submit(Self.correct) == Record(attemptIndex: 2, outcome: .correct, feedbackShown: .hint))

        // A near-miss hint outranks the exercise's, and stays the one on screen.
        var near = Machine(context: .lesson, exerciseHint: "Cappuccino is masculine.")
        near.submit(GradedAnswer(outcome: .wrong, nearHint: "Una is for feminine nouns."))
        #expect(near.requestHint() == .nearMiss("Una is for feminine nouns."))
        near.tryAgain()
        #expect(near.requestHint() == .nearMiss("Una is for feminine nouns."))

        // No exercise hint: the generic hint on screen, or nothing.
        var generic = Machine(context: .lesson)
        generic.submit(Self.wrong)
        #expect(generic.requestHint() == .generic(.ending))
        var none = Machine(context: .review)
        none.submit(ChoiceGrader.grade(selected: 1, answer: 0))
        none.tryAgain()
        #expect(none.requestHint() == nil)
        #expect(none.state == .awaitingSecond(nil))
    }

    // MARK: Records feed the rating policy as specified

    @Test func onlyFirstAttemptsReachFSRS() {
        var m = Machine(context: .lesson)
        let first = m.submit(Self.wrong)
        m.tryAgain()
        let second = m.submit(Self.correct)
        #expect(
            first.map {
                RatingPolicy.rating(
                    format: .cloze, outcome: $0.outcome, mode: .typed, attemptIndex: $0.attemptIndex, context: .lesson)
            } == .again)
        #expect(
            second.map {
                RatingPolicy.rating(
                    format: .cloze, outcome: $0.outcome, mode: .typed, attemptIndex: $0.attemptIndex, context: .lesson)
            } == .some(nil))
    }
}

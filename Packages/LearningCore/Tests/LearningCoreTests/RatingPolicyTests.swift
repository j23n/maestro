import Testing

@testable import LearningCore

/// docs/05 § Rating policy, one test per row.
@Suite struct RatingPolicyTests {
    func r(_ f: ExerciseFormat, _ o: AttemptOutcome, _ m: AnswerMode = .typed, index: Int = 1,
           context: AttemptContext = .lesson) -> FSRSRating?
    {
        RatingPolicy.rating(format: f, outcome: o, mode: m, attemptIndex: index, context: context)
    }

    @Test(arguments: [ExerciseFormat.cloze, .recall, .dictation, .sentenceBuilding])
    func typedFormats(_ f: ExerciseFormat) {
        #expect(r(f, .correct) == .good)
        #expect(r(f, .correctWithNote) == .good)
        #expect(r(f, .almost) == .hard)
        #expect(r(f, .wrong) == .again)
        #expect(r(f, .revealed) == .again)
        #expect(r(f, .skipped) == nil)
    }

    @Test(arguments: [ExerciseFormat.choice, .match, .trueFalse, .soundPair])
    func tappedFormats(_ f: ExerciseFormat) {
        #expect(r(f, .correct, .tapped) == .good)
        #expect(r(f, .wrong, .tapped) == .again)
        #expect(r(f, .skipped, .tapped) == nil)
    }

    @Test func spokenPassIsGoodAndFailNeverUpdates() {
        #expect(r(.repeat, .correct, .spoken) == .good)
        #expect(r(.repeat, .wrong, .spoken) == nil)
        #expect(r(.repeat, .skipped, .spoken) == nil)
        #expect(r(.recall, .correct, .spoken) == .good)
        #expect(r(.recall, .wrong, .spoken) == nil)  // ADR-08: a failed speaking attempt is never a lapse
    }

    @Test(arguments: [ExerciseFormat.conversation, .talk, .writing, .relay])
    func taskFormatsNeverUpdate(_ f: ExerciseFormat) {
        for o in AttemptOutcome.allCases {
            #expect(r(f, o) == nil)
            #expect(r(f, o, .spoken) == nil)
        }
    }

    @Test func onlyFirstAttemptsCount() {
        #expect(r(.cloze, .correct, index: 2) == nil)
        #expect(r(.choice, .wrong, .tapped, index: 2) == nil)
    }

    @Test func placementNeverUpdatesButChecksDo() {
        #expect(r(.recall, .correct, context: .placement) == nil)
        #expect(r(.recall, .correct, context: .check) == .good)
        #expect(r(.cloze, .almost, context: .final) == .hard)
        #expect(r(.choice, .wrong, .tapped, context: .review) == .again)
    }

    @Test func easyIsNeverProduced() {
        for f in ExerciseFormat.allCases {
            for o in AttemptOutcome.allCases {
                for m in [AnswerMode.typed, .tapped, .spoken] {
                    #expect(r(f, o, m) != .easy)
                }
            }
        }
    }
}

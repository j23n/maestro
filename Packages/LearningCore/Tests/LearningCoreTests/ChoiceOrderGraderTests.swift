import Foundation
import Testing

@testable import LearningCore

/// docs/05 § Other graders: choice, true-false, sound-pair, match and sentence building.
@Suite struct ChoiceOrderGraderTests {
    @Test func choiceTrueFalseAndSoundPair() {
        #expect(ChoiceGrader.grade(selected: 0, answer: 0).outcome == .correct)
        #expect(ChoiceGrader.grade(selected: 2, answer: 0) == GradedAnswer(outcome: .wrong, selectedIndex: 2))
        #expect(ChoiceGrader.grade(selected: true, answer: true).outcome == .correct)
        #expect(ChoiceGrader.grade(selected: false, answer: true).outcome == .wrong)
        #expect(ChoiceGrader.grade(selected: "double", answer: "double").outcome == .correct)
        #expect(ChoiceGrader.grade(selected: "single", answer: "double").outcome == .wrong)
    }

    @Test func matchScoresEachPair() {
        let result = MatchGrader.grade(selections: [0: 0, 1: 2, 2: 1, 3: 3], pairCount: 5)
        #expect(result.pairOutcomes == [.correct, .wrong, .wrong, .correct, .wrong])
        #expect(result.outcome == .wrong)
        #expect(MatchGrader.grade(selections: [0: 0, 1: 1], pairCount: 2).outcome == .correct)
        #expect(MatchGrader.isMatch(left: 3, right: 3))
        #expect(!MatchGrader.isMatch(left: 3, right: 1))
    }

    let accepted = ["oggi vorrei un caffè", "vorrei un caffè oggi"]

    @Test func sentenceBuildingAcceptsAnyAcceptedOrder() {
        let a = OrderGrader.grade(placed: ["Oggi", "vorrei", "un", "caffè"], accepted: accepted)
        #expect(a.outcome == .correct)
        #expect(a.closestAnswer == 0)
        #expect(a.firstMisplaced == nil)
        #expect(OrderGrader.grade(placed: ["vorrei", "un", "caffè", "oggi"], accepted: accepted).closestAnswer == 1)
    }

    @Test func sentenceBuildingPointsAtTheFirstMisplacedTile() {
        let wrong = OrderGrader.grade(placed: ["vorrei", "una", "caffè", "oggi"], accepted: accepted)
        #expect(wrong.outcome == .wrong)
        #expect(wrong.closestAnswer == 1)
        #expect(wrong.firstMisplaced == 1)
        #expect(!wrong.isIncomplete)
        let swapped = OrderGrader.grade(placed: ["un", "vorrei", "caffè", "oggi"], accepted: accepted)
        #expect(swapped.firstMisplaced == 0)
        let short = OrderGrader.grade(placed: ["vorrei", "un"], accepted: accepted)
        #expect(short.outcome == .wrong)
        #expect(short.firstMisplaced == nil)
        #expect(short.isIncomplete)
        // Multi-word tiles: the misplaced position is a tile position.
        let tiles = OrderGrader.grade(
            placed: ["ecco", "un cornetto", "e", "un caffè"], accepted: ["ecco un cappuccino e un cornetto"])
        #expect(tiles.firstMisplaced == 1)
        let extra = OrderGrader.grade(placed: ["vorrei", "un", "caffè", "oggi", "una"], accepted: accepted)
        #expect(extra.outcome == .wrong)
        #expect(extra.firstMisplaced == 4)
    }

    /// Elided tiles join the next word as the normaliser joins them (`l'` + `acqua` = `l'acqua`); hints still point
    /// at tiles.
    @Test func elidedTilesJoinTheNextWord() {
        let water = ["L'acqua è fredda.", "È fredda l'acqua."]
        let right = OrderGrader.grade(placed: ["l'", "acqua", "è", "fredda"], accepted: water)
        #expect(right.outcome == .correct)
        #expect(right.closestAnswer == 0)
        #expect(OrderGrader.grade(placed: ["è", "fredda", "l'", "acqua"], accepted: water).outcome == .correct)
        #expect(OrderGrader.grade(placed: ["l'acqua", "è", "fredda"], accepted: water).outcome == .correct)
        let swapped = OrderGrader.grade(placed: ["l'", "è", "acqua", "fredda"], accepted: water)
        #expect(swapped.outcome == .wrong)
        #expect(swapped.firstMisplaced == 1)
        let first = OrderGrader.grade(placed: ["acqua", "l'", "è", "fredda"], accepted: water)
        #expect(first.firstMisplaced == 0)
        let short = OrderGrader.grade(placed: ["l'"], accepted: water)
        #expect(short.isIncomplete)
        #expect(short.firstMisplaced == nil)
        #expect(OrderGrader.pieces("Un po' di pane, dell'acqua") == ["un", "po'", "di", "pane", "dell'", "acqua"])
    }
}

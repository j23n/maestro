import Foundation
import Testing
import PackKit
@testable import PracticeKit

private func gap(answers: [String], near: [String: String] = [:]) -> Drill {
    Drill(id: "d1", kind: "gap", recipe: "participle", topic: "passato-prossimo", sentence: "s1",
          prompt: "Type the past participle.", before: "Ho ", after: " la borsa.", cue: "prendere",
          answers: answers, near: near, rule: "prendere → preso.")
}

@Suite struct GraderTests {
    @Test func acceptsTheAnswerWhateverTheCaseAndPunctuation() {
        let drill = gap(answers: ["preso"])
        #expect(DrillGrader.grade("preso", for: drill) == .correct)
        #expect(DrillGrader.grade("  Preso. ", for: drill) == .correct)
    }

    @Test func acceptsAMissingAccentButSaysSo() {
        let drill = gap(answers: ["perché"])
        #expect(DrillGrader.grade("perche", for: drill) == .accentSlip(expected: "perché"))
        #expect(DrillGrader.grade("perché", for: drill) == .correct)
    }

    @Test func germanWithoutUmlautKeysOrEszettIsAnAccentSlip() {
        let drill = gap(answers: ["Häuser", "Straße"])
        #expect(DrillGrader.grade("haeuser", for: drill) == .accentSlip(expected: "Häuser"))
        #expect(DrillGrader.grade("hauser", for: drill) == .accentSlip(expected: "Häuser"))
        #expect(DrillGrader.grade("strasse", for: drill) == .accentSlip(expected: "Straße"))
        #expect(DrillGrader.grade("häuser", for: drill) == .correct)
    }

    @Test func nearMissesGetTheirOwnHint() {
        let drill = gap(answers: ["preso"], near: ["prenduto": "prendere has an irregular participle."])
        #expect(DrillGrader.grade("prenduto", for: drill) == .wrong(hint: "prendere has an irregular participle."))
    }

    @Test func unexpectedAnswersGetAGenericHint() {
        let drill = gap(answers: ["andavamo"])
        #expect(DrillGrader.grade("andavate", for: drill) == .wrong(hint: "Check the ending."))
        #expect(DrillGrader.grade("mangiavo", for: drill) == .wrong(hint: "That's not the word we need here."))
        #expect(DrillGrader.grade("", for: drill) == .wrong(hint: "Type an answer first."))
    }

    @Test func nearKeysIgnoreAccentsAndApostrophes() {
        let drill = Drill(id: "d1", kind: "choice", recipe: "contraction", topic: "preposition-contractions",
                          sentence: "s1", prompt: "Pick the preposition.", options: ["dal", "dall’"],
                          answers: ["dal"], near: ["dall'": "formaggiaio takes il."])
        #expect(DrillGrader.grade(option: "dall’", for: drill) == .wrong(hint: "formaggiaio takes il."))
        #expect(DrillGrader.grade(option: "dal", for: drill) == .correct)
    }

    @Test func buildChecksOrderMissingWordsAndDistractors() {
        let drill = Drill(id: "d5", kind: "build", recipe: "order", topic: "passato-prossimo", sentence: "s4",
                          prompt: "Put the words in order.", answers: ["il nonno ha mangiato"],
                          tiles: ["il", "nonno", "ha", "mangiato"], distractors: ["è"])
        #expect(DrillGrader.grade(tiles: ["il", "nonno", "ha", "mangiato"], for: drill) == .correct)
        #expect(DrillGrader.grade(tiles: ["il", "nonno", "è", "mangiato"], for: drill)
            == .wrong(hint: "One of those words doesn't belong in the sentence."))
        #expect(DrillGrader.grade(tiles: ["il", "nonno", "ha"], for: drill) == .wrong(hint: "Something's missing."))
        #expect(DrillGrader.grade(tiles: ["nonno", "il", "ha", "mangiato"], for: drill)
            == .wrong(hint: "Check the word order."))
    }
}

@Suite struct StepFeedbackTests {
    @Test func rightFirstTime() {
        var f = StepFeedback()
        f.record(accepted: true)
        #expect(f.outcome == .firstTry)
    }

    @Test func aMissGivesOneMoreTry() {
        var f = StepFeedback()
        #expect(f.record(accepted: false) == .retrying)
        #expect(f.sawHint)
        #expect(f.record(accepted: true) == .done(.afterHint))
    }

    @Test func twoMissesShowTheAnswer() {
        var f = StepFeedback()
        f.record(accepted: false)
        #expect(f.record(accepted: false) == .done(.shown))
        f.record(accepted: true)
        #expect(f.outcome == .shown)
    }

    @Test func askingForAHintIsNotAFirstTry() {
        var f = StepFeedback()
        f.showHint()
        f.record(accepted: true)
        #expect(f.outcome == .afterHint)
    }

    @Test func showAnswerEndsTheDrill() {
        var f = StepFeedback()
        f.reveal()
        #expect(f.outcome == .shown)
    }

    @Test func matchFinishesWithOrWithoutMisses() {
        var clean = StepFeedback()
        clean.finish(missed: false)
        #expect(clean.outcome == .firstTry)
        var missed = StepFeedback()
        missed.finish(missed: true)
        #expect(missed.outcome == .afterHint)
    }
}

@Suite struct PracticeSetTests {
    @Test func shuffleIsStableForASeed() {
        let options = ["ho", "sono"]
        let a = SeededShuffle.shuffled(options, seed: "vita-quotidiana-01.d1")
        #expect(a == SeededShuffle.shuffled(options, seed: "vita-quotidiana-01.d1"))
        #expect(Set(a) == Set(options))
    }

    @Test func eitherOptionCanComeFirst() {
        // The answer's place must not be predictable: across seeds, both orders of two options appear.
        let orders = Set((0..<40).map { SeededShuffle.shuffled(["ho", "sono"], seed: "t.d\($0)") })
        #expect(orders == [["ho", "sono"], ["sono", "ho"]])
    }

    @Test func matchPairsNeverStartLinedUp() {
        let participles = ["preso", "andato", "dato"]
        for n in 0..<40 {
            let s = SeededShuffle.shuffled(participles, seed: "t.d\(n)", avoidingGivenOrder: true)
            #expect(s != participles && Set(s) == Set(participles))
        }
    }

    @Test func tilesNeverReadInTheAnswerOrderWhereverTheDistractorLands() {
        let tiles = ["il", "nonno", "ha", "mangiato"]
        for n in 0..<200 {
            let bank = SeededShuffle.tileBank(tiles: tiles, distractors: ["è"], seed: "t.d\(n)")
            #expect(bank.sorted() == (tiles + ["è"]).sorted())
            #expect(bank.filter { $0 != "è" } != tiles)
        }
        for n in 0..<40 {
            #expect(SeededShuffle.tileBank(tiles: tiles, distractors: [], seed: "t.d\(n)") != tiles)
        }
    }

    @Test func fnvMatchesTheReferenceValue() {
        #expect(SeededShuffle.fnv1a("") == 0xcbf2_9ce4_8422_2325)
        #expect(SeededShuffle.fnv1a("a") == 0xaf63_dc4c_8601_ec8c)
    }

    @Test func keepSuggestionsAreOnePerTopicNeedingHelp() {
        let drills = [
            Drill(id: "d1", kind: "choice", recipe: "aux", topic: "passato-prossimo", sentence: "s2", prompt: ""),
            Drill(id: "d2", kind: "gap", recipe: "participle", topic: "passato-prossimo", sentence: "s4", prompt: ""),
            Drill(id: "d3", kind: "gap", recipe: "form", topic: "imperfetto", sentence: "s1", prompt: ""),
            Drill(id: "d4", kind: "choice", recipe: "article", topic: "articles", sentence: "s5", prompt: ""),
        ]
        let outcomes: [String: Outcome] = ["d1": .firstTry, "d2": .shown, "d3": .afterHint, "d4": .firstTry]
        let keep = PracticeSummary.keepSuggestions(drills, outcomes: outcomes)
        #expect(keep.map(\.topic) == ["passato-prossimo", "imperfetto"])
        #expect(keep.first?.drill.id == "d2")
        #expect(PracticeSummary.firstTries(drills, outcomes: outcomes) == 2)
    }

    @Test func packDrillsDecode() throws {
        let json = """
        {"id": "t", "title": "T", "level": "A2", "collection": "c", "blocks": [], "questions": [],
         "drills": [
          {"id": "d1", "kind": "choice", "recipe": "aux", "topic": "passato-prossimo", "sentence": "s2",
           "prompt": "Pick the auxiliary.", "before": "Ho preso la borsa e ", "after": " andata al mercato.",
           "r": [20, 4], "cue": "andare", "options": ["sono", "ho"], "answers": ["sono"],
           "near": {"ho": "andare takes essere."}, "rule": "andare takes essere: sono andata."},
          {"id": "d2", "kind": "match", "recipe": "participles", "topic": "passato-prossimo", "sentence": "s2",
           "prompt": "Match each verb to its participle.", "pairs": [["prendere", "preso"], ["dare", "dato"]]},
          {"id": "d3", "kind": "speak", "recipe": "future", "topic": "x", "sentence": "s1", "prompt": "?"}
         ]}
        """
        let text = try JSONDecoder().decode(ReadingText.self, from: Data(json.utf8))
        #expect(text.drills?.count == 3)
        #expect(text.practice.map(\.id) == ["d1", "d2"])
        let first = try #require(text.practice.first)
        #expect(first.format == .choice && first.r?.start == 20 && first.answer == "sono")
        #expect(text.practice[1].pairs?.first == ["prendere", "preso"])
    }

    @Test func textsWithoutDrillsStillDecode() throws {
        let json = #"{"id": "t", "title": "T", "level": "A2", "collection": "c", "blocks": [], "questions": []}"#
        let text = try JSONDecoder().decode(ReadingText.self, from: Data(json.utf8))
        #expect(text.drills == nil && text.practice.isEmpty)
    }
}

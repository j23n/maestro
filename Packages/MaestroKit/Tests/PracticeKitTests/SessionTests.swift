import Foundation
import Testing
import LanguageCore
import PackKit
@testable import PracticeKit

private func drill(_ id: String, _ strand: Strand, topic: String = "x", core: Bool = false, kind: String = "gap") -> Drill {
    Drill(id: id, kind: kind, recipe: "r", topic: topic, sentence: "s1", prompt: "", strand: strand.rawValue,
          core: core, key: "k\(id)")
}

@Suite struct SessionBuilderTests {
    let drills = [
        drill("d1", .grammar, topic: "futuro-semplice", core: true, kind: "find"),
        drill("d2", .grammar, topic: "futuro-semplice", core: true),
        drill("d3", .grammar, topic: "articles"),
        drill("d4", .words, topic: "words", core: true),
        drill("d5", .words, topic: "words"),
        drill("d6", .verbs, topic: "futuro-semplice", core: true),
        drill("d7", .verbs, topic: "presente-indicativo"),
        drill("d8", .say, topic: "functions", core: true, kind: "roleplay"),
    ]

    func build(_ settings: SessionSettings = SessionSettings(), review: [SessionDrill] = []) -> [SessionStage] {
        SessionBuilder.stages(textID: "t", drills: drills, hasQuestions: true, introduces: ["futuro-semplice"],
                              settings: settings, review: review)
    }

    @Test func stagesRunInOrderAfterTheQuestions() {
        #expect(build().map(\.kind) == [.questions, .words, .grammar, .verbs, .say])
        #expect(build()[2].drills.map(\.drill.id) == ["d1", "d2", "d3"])
    }

    @Test func shortKeepsTheCoreDrills() {
        let stages = build(SessionSettings(length: .short))
        #expect(stages.flatMap(\.drills).map(\.drill.id) == ["d4", "d1", "d2", "d6", "d8"])
        let counts = SessionBuilder.counts(drills)
        #expect(counts[.grammar]?.short == 2 && counts[.grammar]?.full == 3)
    }

    @Test func aStrandWithoutCoreDrillsKeepsItsFirstTwoInShort() {
        let plain = (1...4).map { drill("w\($0)", .words) }
        let stages = SessionBuilder.stages(textID: "t", drills: plain, hasQuestions: false, introduces: [],
                                           settings: SessionSettings(length: .short))
        #expect(stages.map { $0.drills.map(\.drill.id) } == [["w1", "w2"]])
    }

    @Test func strandsCanBeSwitchedOff() {
        var settings = SessionSettings()
        settings.strands = [.grammar, .say]
        settings.questions = false
        #expect(build(settings).map(\.kind) == [.grammar, .say])
    }

    @Test func theIntroducedTopicNeverComesBeforeItsIntro() {
        // A drill on the new topic in the Words strand moves after the Grammar stage.
        var mixed = drills
        mixed.append(drill("d9", .words, topic: "futuro-semplice"))
        let stages = SessionBuilder.stages(textID: "t", drills: mixed, hasQuestions: false, introduces: ["futuro-semplice"],
                                           settings: SessionSettings())
        let words = stages.first { $0.kind == .words }
        #expect(!(words?.drills.contains { $0.drill.id == "d9" } ?? true))
        #expect(stages.first { $0.kind == .verbs }?.drills.first?.drill.id == "d9")
        #expect(stages.allSatisfy { !$0.introducesGrammar })
    }

    @Test func aMovedDrillIsLeftOutWhenVerbsIsOff() {
        let mixed = [drill("w1", .words, topic: "words"), drill("w2", .words, topic: "futuro-semplice"),
                     drill("g1", .grammar, topic: "futuro-semplice")]
        var settings = SessionSettings()
        settings.strands = [.words, .grammar]
        let stages = SessionBuilder.stages(textID: "t", drills: mixed, hasQuestions: false,
                                           introduces: ["futuro-semplice"], settings: settings)
        #expect(stages.map(\.kind) == [.words, .grammar])
        #expect(stages.flatMap(\.drills).map(\.drill.id) == ["w1", "g1"])
    }

    @Test func withoutGrammarTheFirstStageOnTheTopicIntroducesIt() {
        var settings = SessionSettings()
        settings.strands = [.words, .verbs, .say]
        let stages = build(settings)
        #expect(stages.first { $0.kind == .verbs }?.introducesGrammar == true)
        #expect(stages.first { $0.kind == .words }?.introducesGrammar == false)
    }

    @Test func reviewComesLastAndIsCapped() {
        let earlier = (1...5).map { SessionDrill(textID: "other", drill: drill("r\($0)", .grammar)) }
        let stages = build(review: earlier)
        #expect(stages.last?.kind == .review && stages.last?.drills.count == SessionBuilder.reviewLimit)
        var off = SessionSettings()
        off.review = false
        #expect(!build(off, review: earlier).contains { $0.kind == .review })
    }

    @Test func drillsOfUnknownKindsAreLeftOut() {
        let odd = [drill("d1", .words, kind: "speak"), drill("d2", .words)]
        let stages = SessionBuilder.stages(textID: "t", drills: odd, hasQuestions: false, introduces: [],
                                           settings: SessionSettings())
        #expect(stages.flatMap(\.drills).map(\.drill.id) == ["d2"])
    }

    @Test func drillsFromOlderPacksAreGrammar() {
        let old = Drill(id: "d1", kind: "gap", recipe: "form", topic: "imperfetto", sentence: "s1", prompt: "")
        #expect(old.strandKind == .grammar && old.stableKey == "d1" && !old.isCore)
    }
}

@Suite struct ReviewPickerTests {
    let t0 = Date(timeIntervalSince1970: 1_000_000)

    @Test func picksWhatNeededHelpNewestFirst() {
        let records = [
            DrillRecord(textID: "a", drillKey: "k1", outcome: .shown, at: t0),
            DrillRecord(textID: "a", drillKey: "k2", outcome: .afterHint, at: t0.addingTimeInterval(60)),
            DrillRecord(textID: "b", drillKey: "k3", outcome: .firstTry, at: t0),
            DrillRecord(textID: "here", drillKey: "k4", outcome: .shown, at: t0),
        ]
        #expect(ReviewPicker.pick(records, excluding: "here").map(\.drillKey) == ["k2", "k1"])
    }

    @Test func aFirstTryInReviewDropsTheDrill() {
        let records = [
            DrillRecord(textID: "a", drillKey: "k1", outcome: .shown, at: t0),
            DrillRecord(textID: "a", drillKey: "k1", outcome: .firstTry, at: t0.addingTimeInterval(60)),
            DrillRecord(textID: "a", drillKey: "k2", outcome: .shown, at: t0),
            DrillRecord(textID: "a", drillKey: "k2", outcome: .afterHint, at: t0.addingTimeInterval(60)),
        ]
        #expect(ReviewPicker.pick(records, excluding: "x").map(\.drillKey) == ["k2"])
    }

    @Test func atMostThree() {
        let records = (0..<6).map { DrillRecord(textID: "a", drillKey: "k\($0)", outcome: .shown, at: t0.addingTimeInterval(Double($0))) }
        #expect(ReviewPicker.pick(records, excluding: "x").map(\.drillKey) == ["k5", "k4", "k3"])
    }

    @Test func onlyKeyedDrillsOtherThanRoleplaysComeBack() {
        #expect(ReviewPicker.canReview(drill("d1", .grammar)))
        #expect(!ReviewPicker.canReview(drill("d2", .say, kind: "roleplay")))
        let unkeyed = Drill(id: "d3", kind: "gap", recipe: "form", topic: "imperfetto", sentence: "s1", prompt: "")
        #expect(!ReviewPicker.canReview(unkeyed))
    }
}

@Suite struct PatternGraderTests {
    @Test func expandsChoicesAndOptionalWords() {
        #expect(PatternGrader.expand("{Volentieri|Con piacere}!") == ["Volentieri!", "Con piacere!"])
        #expect(PatternGrader.expand("Credo di sì(, perché)?") == ["Credo di sì?", "Credo di sì, perché?"])
        #expect(PatternGrader.expand("{Ci vediamo|Vediamoci} (prima)").count == 4)
        #expect(PatternGrader.expand("(E) anche una brioche.") == ["anche una brioche.", "E anche una brioche."])
        #expect(PatternGrader.expand("{a|{b|c}d}") == ["a", "bd", "cd"])
    }

    @Test func aBrokenPatternAcceptsItself() {
        #expect(PatternGrader.expand("{a|b") == ["{a|b"])
    }

    @Test func gradesWithAccentTolerance() {
        let patterns = ["{Volentieri|Con piacere}! A che ora {comincia|inizia}?"]
        #expect(PatternGrader.grade("con piacere, a che ora inizia", patterns: patterns, german: false) == .correct)
        #expect(PatternGrader.grade("Volentieri! A che ora comincia?", patterns: patterns, german: false) == .correct)
        #expect(!PatternGrader.grade("Sì", patterns: patterns, german: false).isAccepted)
        #expect(PatternGrader.grade("Credo di si", patterns: ["Credo di sì"], german: false)
            == .accentSlip(expected: "Credo di sì"))
        #expect(PatternGrader.grade("Die Idee gefaellt mir", patterns: ["Die Idee gefällt mir!"], german: true)
            == .accentSlip(expected: "Die Idee gefällt mir!"))
    }
}

@Suite struct NewFormatGraderTests {
    @Test func findWantsEveryTargetAndNoOthers() {
        let targets = [DrillTarget(s: "s1", t: 2), DrillTarget(s: "s3", t: 0)]
        let d = Drill(id: "d1", kind: "find", recipe: "find-forms", topic: "futuro-semplice", sentence: "s1", prompt: "",
                      targets: targets)
        #expect(DrillGrader.grade(selection: Set(targets), for: d) == .correct)
        #expect(DrillGrader.grade(selection: [targets[0]], for: d) == .wrong(hint: "There's one more."))
        #expect(DrillGrader.grade(selection: Set(targets + [DrillTarget(s: "s1", t: 5)]), for: d)
            == .wrong(hint: "One of those isn't one."))
    }

    @Test func rowCellsAcceptAnyFormAndSlips() {
        let d = Drill(id: "d1", kind: "row", recipe: "tense-row", topic: "futuro-semplice", sentence: "s1", prompt: "")
        let cell = RowCell(p: "1s", label: "io", forms: ["porterò"], given: false)
        #expect(DrillGrader.grade("porterò", cell: cell, for: d) == .correct)
        #expect(DrillGrader.grade("portero", cell: cell, for: d) == .accentSlip(expected: "porterò"))
        #expect(!DrillGrader.grade("porterai", cell: cell, for: d).isAccepted)
        #expect(DrillGrader.grade("", cell: cell, for: d) == .wrong(hint: "Type an answer first."))
    }

    @Test func germanWordsKeepUmlautsByTheirLemma() {
        let d = Drill(id: "d1", kind: "gap", recipe: "word-recall", topic: "de:words", sentence: "s1", prompt: "",
                      answers: ["Küche"], lemma: "de:Küche:n")
        #expect(d.isGerman)
        #expect(DrillGrader.grade("kueche", for: d) == .accentSlip(expected: "Küche"))
        #expect(!DrillGrader.grade("kuche", for: d).isAccepted)
    }
}

@Suite struct RoleplayTests {
    let drill = Drill(id: "d1", kind: "roleplay", recipe: "roleplay", topic: "functions", sentence: "s1", prompt: "",
                      speaker: "Sara", other: "Chiara",
                      goals: [RoleplayGoal(id: "accept", label: "Accept")],
                      turns: [
                        RoleplayTurn(who: "Chiara", s: ["s1"]),
                        RoleplayTurn(who: "Sara", s: ["s2"], chips: ["Volentieri!", "Quanto costa?", "Un caffè."],
                                     answers: ["Volentieri!"], accept: ["{Volentieri|Con piacere}!"], goal: "accept"),
                        RoleplayTurn(who: "Chiara", s: ["s3"]),
                        RoleplayTurn(who: "Sara", s: ["s4"], chips: ["A venerdì!", "Ecco a lei.", "Tenga."],
                                     answers: ["A venerdì!"], accept: ["A venerdì!"]),
                      ])
    let lines = ["s1": "Vieni con me?", "s2": "Volentieri!", "s3": "Alle nove.", "s4": "A venerdì!"]

    func start() -> RoleplayState {
        let lines = self.lines
        return RoleplayState(drill: drill) { ids in ids.compactMap { lines[$0] }.joined(separator: " ") }
    }

    @Test func theOtherSideSpeaksFirst() {
        let state = start()
        #expect(state.transcript.map(\.text) == ["Vieni con me?"])
        #expect(state.current == 1 && state.chips(seed: "x").count == 3)
    }

    @Test func hitsReachGoalsAndEndFirstTry() {
        var state = start()
        state.pick("Volentieri!")
        #expect(state.reached == ["accept"])
        #expect(state.transcript.map(\.text) == ["Vieni con me?", "Volentieri!", "Alle nove."])
        state.say("a venerdi")
        #expect(state.isDone && state.outcome == .firstTry)
    }

    @Test func oneMissGivesAHintAndAnotherTry() {
        var state = start()
        state.pick("Quanto costa?")
        #expect(state.hint != nil && state.wrongChips == ["Quanto costa?"] && state.current == 1)
        state.say("Con piacere!")
        #expect(state.current == 3 && state.transcript[1].text == "Con piacere!")
        state.pick("A venerdì!")
        #expect(state.outcome == .afterHint)
    }

    @Test func twoMissesShowTheLineAndGoOn() {
        var state = start()
        state.pick("Quanto costa?")
        state.pick("Un caffè.")
        #expect(state.transcript[1] == RoleplayState.Line(who: "Sara", text: "Volentieri!", isLearner: true, shown: true))
        #expect(state.current == 3 && state.hint == nil && !state.reached.contains("accept"))
        state.reveal()
        #expect(state.isDone && state.outcome == .shown)
    }
}

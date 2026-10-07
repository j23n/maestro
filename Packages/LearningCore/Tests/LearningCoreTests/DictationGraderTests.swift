import Foundation
import Testing

@testable import LearningCore

/// docs/05 § Other graders (dictation); `fixtures/grading/dictation.json`.
@Suite struct DictationGraderTests {
    struct Fixture: Decodable {
        struct Case: Decodable {
            let target: String
            let response: String
            let outcome: AttemptOutcome
            let marks: [DictationGrader.Mark]
        }
        let cases: [Case]
    }

    @Test func everyDictationCase() throws {
        let fixture = try JSONDecoder().decode(Fixture.self, from: Fixtures.data("fixtures/grading/dictation.json"))
        #expect(fixture.cases.count >= 10)
        for c in fixture.cases {
            let result = DictationGrader.grade(target: c.target, response: c.response)
            #expect(result.outcome == c.outcome, "\(c.response) for \(c.target)")
            #expect(result.marks == c.marks, "\(c.response) for \(c.target)")
        }
    }

    @Test func doublingNoteNamesTheConsonant() {
        let r = DictationGrader.grade(target: "Vorrei un cornetto.", response: "vorrei un corneto")
        let word = r.words[2]
        #expect(word.mark == .doubling)
        #expect(word.consonant == "t")
        #expect(word.targetIsDouble == true)
        let single = DictationGrader.grade(target: "Il capello.", response: "il cappello")
        #expect(single.words[1].mark == .doubling)
        #expect(single.words[1].consonant == "p")
        #expect(single.words[1].targetIsDouble == false)
    }

    @Test func typosNeedFourLetters() {
        #expect(DictationGrader.grade(target: "Ecco Sara.", response: "ecco sars").marks == [.correct, .typo])
        #expect(DictationGrader.grade(target: "un tè", response: "un te").marks == [.correct, .wrong])
        #expect(DictationGrader.grade(target: "per favore", response: "pre favore").marks == [.wrong, .correct])
    }

    @Test func extraWordsMakeItWrong() {
        let r = DictationGrader.grade(target: "Vorrei un cornetto.", response: "vorrei un un cornetto")
        #expect(r.marks == [.correct, .correct, .correct])
        #expect(r.extraWords == ["un"])
        #expect(r.outcome == .wrong)
    }

    @Test func accentPlusDoublingIsATypoAndInflectionIsWrong() {
        // cafe for caffè: not only accents, not only length, but one edit from caffe.
        #expect(DictationGrader.grade(target: "un caffè", response: "un cafe").marks == [.correct, .typo])
        let forms = KnownForms(["cornetto": ["w:cornetto"], "cornetti": ["w:cornetto"]])
        let r = DictationGrader.grade(target: "un cornetto", response: "un cornetti", knownForms: forms)
        #expect(r.marks == [.correct, .wrong])
    }
}

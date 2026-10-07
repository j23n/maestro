import Foundation
import Testing

@testable import LearningCore

/// docs/05 § Typed answers; `fixtures/grading/typed-answers.json`.
@Suite struct TypedAnswerGraderTests {
    /// `knownForms` values may be one item ID or a list of them.
    struct ItemIDs: Decodable {
        let ids: Set<ItemID>
        init(from decoder: Decoder) throws {
            let c = try decoder.singleValueContainer()
            if let one = try? c.decode(String.self) {
                ids = [ItemID(one)]
            } else {
                ids = Set(try c.decode([String].self).map { ItemID($0) })
            }
        }
    }

    struct Fixture: Decodable {
        struct Defaults: Decodable {
            let forms: LearnerForms
            let strictForms: Bool
            let knownForms: [String: ItemIDs]
        }
        struct Near: Decodable {
            let answer: String
            let outcome: AttemptOutcome?
            let hint: String?
        }
        struct Case: Decodable {
            let id: Int
            let pattern: String
            let response: String
            let near: [Near]?
            let forms: LearnerForms?
            let strictForms: Bool?
            let outcome: AttemptOutcome
            let mismatches: [Int]?
            let hint: String?
            let hintKind: HintKind?
        }
        let defaults: Defaults
        let cases: [Case]
    }

    static func fixture() throws -> Fixture {
        try JSONDecoder().decode(Fixture.self, from: Fixtures.data("fixtures/grading/typed-answers.json"))
    }

    @Test func everyTypedAnswerCase() throws {
        let fixture = try Self.fixture()
        #expect(fixture.cases.count >= 27)
        let forms = KnownForms(fixture.defaults.knownForms.mapValues(\.ids))
        for c in fixture.cases {
            let profile = LearnerProfile(
                forms: c.forms ?? fixture.defaults.forms, strictForms: c.strictForms ?? fixture.defaults.strictForms)
            let grader = TypedAnswerGrader(knownForms: forms, profile: profile)
            let near = try (c.near ?? []).map {
                try TypedAnswerGrader.NearMiss(answer: $0.answer, outcome: $0.outcome ?? .wrong, hint: $0.hint)
            }
            let grade = grader.grade(c.response, accepted: try AnswerPattern(c.pattern), near: near)
            #expect(grade.outcome == c.outcome, "case \(c.id): \(c.response) vs \(c.pattern)")
            if let mismatches = c.mismatches {
                #expect(grade.mismatches == mismatches, "case \(c.id) mismatches")
            }
            if let hint = c.hint {
                #expect(grade.nearHint == hint, "case \(c.id) hint")
                #expect(grade.matchedNear)
            }
            if let kind = c.hintKind {
                #expect(grade.hintKind == kind, "case \(c.id) hint kind")
            }
            if c.outcome == .correct {
                #expect(grade.mismatches.isEmpty && grade.hintKind == nil, "case \(c.id) has no mismatch")
            }
        }
    }

    let grader = TypedAnswerGrader()

    @Test func outcomeClasses() throws {
        let p = try AnswerPattern("vorrei un cappuccino per favore")
        #expect(grader.grade("vorrei un cappuccino per favore", accepted: p).outcome == .correct)
        // Accent-only → correctWithNote; accent + typo → almost; typo + substitution → wrong.
        let q = try AnswerPattern("perché lui è più alto")
        #expect(grader.grade("perche lui è più alto", accepted: q).outcome == .correctWithNote)
        #expect(grader.grade("perche lui è piu alto", accepted: q).mismatches == [0, 3])
        #expect(grader.grade("perhce lui è piu alto", accepted: q).outcome == .almost)
        #expect(grader.grade("perhce lei è piu alto", accepted: q).outcome == .wrong)
    }

    @Test func typoNeedsFourLettersAndANonFocusToken() throws {
        // "una" has three letters: no typo tolerance.
        #expect(
            grader.grade("vorrei unaa spremuta", accepted: try AnswerPattern("vorrei una spremuta")).outcome == .wrong)
        // Accent tolerance applies inside focus tokens; typo tolerance doesn't.
        let focus = try AnswerPattern("un [caffè]")
        #expect(grader.grade("un caffe", accepted: focus).outcome == .correctWithNote)
        #expect(grader.grade("un cafè", accepted: focus).outcome == .wrong)
        #expect(grader.grade("un cafè", accepted: try AnswerPattern("un caffè")).outcome == .almost)
    }

    @Test func inflectionErrorsAreNeverTyposOrAccentSlips() throws {
        let forms = KnownForms([
            "parlo": ["w:parlare"], "parlò": ["w:parlare"], "spremuta": ["w:spremuta"], "spremute": ["w:spremuta"],
        ])
        let g = TypedAnswerGrader(knownForms: forms)
        let accent = g.grade("io parlò", accepted: try AnswerPattern("io parlo"))
        #expect(accent.outcome == .wrong)
        #expect(accent.hintKind == .ending)
        let plural = g.grade("una spremute", accepted: try AnswerPattern("una spremuta"))
        #expect(plural.outcome == .wrong)
        #expect(plural.hintKind == .ending)
    }

    @Test func cheapestExpansionWinsAndFirstOnTies() throws {
        let p = try AnswerPattern("{vorrei|prendo} un caffè")
        let g = grader.grade("prendo un caffe", accepted: p)
        #expect(g.outcome == .correctWithNote)
        #expect(g.expansion?.text == "prendo un caffè")
        let tie = grader.grade("voglio un caffè", accepted: p)
        #expect(tie.expansion?.text == "vorrei un caffè")
        #expect(tie.mismatches == [0])
    }

    @Test func severalAcceptedPatternsAndEmptyResponses() throws {
        let accept = [try AnswerPattern("(vorrei )un cornetto( per favore)"), try AnswerPattern("no grazie")]
        #expect(grader.grade("No, grazie!", accepted: accept).outcome == .correct)
        let empty = grader.grade("", accepted: accept)
        #expect(empty.outcome == .wrong)
        #expect(empty.hintKind == .missing)
        #expect(grader.grade("ciao", accepted: []).outcome == .wrong)
    }

    @Test func insertionIsReportedOnTheResponse() throws {
        let g = grader.grade("vorrei un caffè grazie", accepted: try AnswerPattern("vorrei un caffè"))
        #expect(g.outcome == .wrong)
        #expect(g.hintKind == .extra)
        #expect(g.mismatches.isEmpty)
        #expect(g.responseMismatches == [3])
    }

    @Test func nearMissStillUnderlinesAgainstTheAnswer() throws {
        let near = try TypedAnswerGrader.NearMiss(answer: "una", hint: "Una is for feminine nouns.")
        let g = grader.grade("una", accepted: try AnswerPattern.clozeGap("un"), near: [near])
        #expect(g.outcome == .wrong)
        #expect(g.matchedNear)
        #expect(g.nearHint == "Una is for feminine nouns.")
        #expect(g.mismatches == [0])
        #expect(g.answer.nearHint == "Una is for feminine nouns.")
    }

    @Test func nearPatternsExpand() throws {
        let near = try TypedAnswerGrader.NearMiss(answer: "(ecco )(grazie )ciao", hint: "Giulia says Lei to you.")
        let accept = try AnswerPattern("(ecco )(grazie )(e ){arrivederci|buona giornata}")
        #expect(grader.grade("Grazie, ciao!", accepted: accept, near: [near]).nearHint == "Giulia says Lei to you.")
        #expect(grader.grade("Grazie, arrivederci!", accepted: accept, near: [near]).outcome == .correct)
    }

    @Test func slotsTakeTheirWordCounts() throws {
        let name = try AnswerPattern("mi chiamo {NAME}")
        #expect(grader.grade("mi chiamo", accepted: name).outcome == .wrong)
        #expect(grader.grade("mi chiamo Anna Maria de Rossi", accepted: name).outcome == .wrong)
        let number = try AnswerPattern("ho {NUMBER} anni")
        #expect(grader.grade("ho ventitré anni", accepted: number).outcome == .correct)
        #expect(grader.grade("ho ventitre anni", accepted: number).outcome == .correct)
        #expect(grader.grade("ho molti anni", accepted: number).outcome == .wrong)
        let filled = grader.grade("Mi chiamo Anna Maria", accepted: name)
        #expect(filled.correction == "mi chiamo anna maria")
    }

    static let us = LearnerProfile.Country(
        id: "us", nameIt: "Stati Uniti", homePhrase: "negli Stati Uniti", altHomePhrases: ["in America"],
        nationalityM: "americano", nationalityF: "americana")

    @Test func personalSlotsUseTheProfile() throws {
        let home = try AnswerPattern("abito {ME.home}")
        let mine = TypedAnswerGrader(profile: LearnerProfile(forms: .m, country: Self.us))
        #expect(mine.grade("Abito negli Stati Uniti.", accepted: home).outcome == .correct)
        #expect(mine.grade("abito in America", accepted: home).outcome == .correct)
        #expect(mine.grade("abito in Canada", accepted: home).outcome == .wrong)
        // "Another country": any 1–4 words for home, one word for the nationality.
        let other = TypedAnswerGrader(profile: LearnerProfile(forms: .m, country: nil))
        #expect(other.grade("abito in Nuova Caledonia", accepted: home).outcome == .correct)
        let nationality = try AnswerPattern("sono {ME.nationality}")
        #expect(other.grade("sono caledoniano", accepted: nationality).outcome == .correct)
        #expect(other.grade("sono di Nuova Caledonia", accepted: nationality).outcome == .wrong)
    }

    @Test func strictFormsApplyToNationalities() throws {
        let p = try AnswerPattern("sono {ME.nationality}")
        let lenient = TypedAnswerGrader(profile: LearnerProfile(forms: .m, strictForms: false, country: Self.us))
        #expect(lenient.grade("sono americana", accepted: p).outcome == .correct)
        let strict = TypedAnswerGrader(profile: LearnerProfile(forms: .m, strictForms: true, country: Self.us))
        #expect(strict.grade("sono americana", accepted: p).outcome == .almost)  // a typo of americano, no forms known
        #expect(strict.grade("sono americano", accepted: p).outcome == .correct)
        // Both forms: strict has no effect.
        let both = TypedAnswerGrader(profile: LearnerProfile(forms: .both, strictForms: true, country: Self.us))
        #expect(both.grade("sono americana", accepted: p).outcome == .correct)
    }

    @Test func gradedAnswerCarriesWhatFeedbackNeeds() throws {
        let forms = KnownForms(["un": ["g:indefinite-article"], "una": ["g:indefinite-article"]])
        let g = TypedAnswerGrader(knownForms: forms).grade("un spremuta", accepted: try AnswerPattern("una [spremuta]"))
        #expect(g.answer == GradedAnswer(outcome: .wrong, hintKind: .ending, mismatches: [0]))
    }
}

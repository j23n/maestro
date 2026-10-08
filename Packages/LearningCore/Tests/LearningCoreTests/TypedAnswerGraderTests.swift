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
        #expect(fixture.cases.count >= 34)
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
        #expect(filled.correction == "mi chiamo Anna Maria")
    }

    /// The correction is the model answer as the author wrote it (case, punctuation), the learner's words in slots.
    @Test func correctionKeepsTheAuthorsCaseAndTheLearnersWords() throws {
        let formal = grader.grade("lei parla italano", accepted: try AnswerPattern("Lei parla italiano?"))
        #expect(formal.outcome == .almost)
        #expect(formal.correction == "Lei parla italiano?")
        let name = grader.grade("mi chiamo ANNA maria", accepted: try AnswerPattern("Mi chiamo {NAME}."))
        #expect(name.correction == "Mi chiamo ANNA maria.")
        let escaped = grader.grade("{NAME} anna", accepted: try AnswerPattern("\\{NAME\\} {NAME}"))
        #expect(escaped.correction == "{NAME} anna")
        let home = TypedAnswerGrader(profile: LearnerProfile(forms: .m, country: Self.us))
            .grade("abito negli stati uniti", accepted: try AnswerPattern("Abito {ME.home}."))
        #expect(home.correction == "Abito negli Stati Uniti.")
    }

    /// A slot never takes a word that an expected literal matches exactly: the slot is what's missing.
    @Test func aSlotNeverSwallowsTheLiteralBeforeIt() throws {
        let name = grader.grade("mi chiamo", accepted: try AnswerPattern("mi chiamo {NAME}"))
        #expect(name.mismatches == [2])
        #expect(name.hintKind == .missing)
        #expect(name.correction == "mi chiamo {NAME}")
        let country = grader.grade("vengo dagli", accepted: try AnswerPattern("vengo dagli {ME.country}"))
        #expect(country.mismatches == [2])
        #expect(country.correction == "vengo dagli {ME.country}")
        let filled = grader.grade("mi chiamo Anna", accepted: try AnswerPattern("mi chiamo {NAME}"))
        #expect(filled.outcome == .correct)
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
        // The other gender's form is another form of the same item even when the pack's forms don't list it: an
        // inflection error (ending), never a typo.
        let other = strict.grade("sono americana", accepted: p)
        #expect(other.outcome == .wrong)
        #expect(other.hintKind == .ending)
        #expect(other.mismatches == [1])
        #expect(strict.grade("sono americano", accepted: p).outcome == .correct)
        // A real typo of the learner's form is still a typo.
        #expect(strict.grade("sono amerciano", accepted: p).outcome == .almost)
        // Both forms: strict has no effect.
        let both = TypedAnswerGrader(profile: LearnerProfile(forms: .both, strictForms: true, country: Self.us))
        #expect(both.grade("sono americana", accepted: p).outcome == .correct)
    }

    @Test func strictFormsMakeTheOtherGenderAnEndingError() throws {
        let strictM = TypedAnswerGrader(profile: LearnerProfile(forms: .m, strictForms: true))
        let nata = strictM.grade("sono nata a Toronto", accepted: try AnswerPattern("sono {m:nato|f:nata} a Toronto"))
        #expect(nata.outcome == .wrong)
        #expect(nata.hintKind == .ending)
        // Alternatives of the same length pair word by word: la/il, mia/mio, amica/amico.
        let strictF = TypedAnswerGrader(profile: LearnerProfile(forms: .f, strictForms: true))
        let friend = try AnswerPattern("è {m:il mio amico|f:la mia amica}")
        let g = strictF.grade("è la mia amico", accepted: friend)
        #expect(g.outcome == .wrong)
        #expect(g.mismatches == [3])
        #expect(g.hintKind == .ending)
        #expect(
            friend.genderFormPairs() == [FormPair("il", "la"), FormPair("mio", "mia"), FormPair("amico", "amica")])
        // Different lengths: every differing word of one with every differing word of the other.
        #expect(
            try AnswerPattern("{m:un amico|f:un'amica}").genderFormPairs()
                == [FormPair("un", "un'amica"), FormPair("amico", "un'amica")])
        // A nationality with one form for both genders (canadese) has no pair.
        let canada = LearnerProfile.Country(
            id: "ca", nameIt: "Canada", homePhrase: "in Canada", nationalityM: "canadese", nationalityF: "canadese")
        let nationality = try AnswerPattern("sono {ME.nationality}")
        #expect(nationality.genderFormPairs(profile: LearnerProfile(country: canada)).isEmpty)
        #expect(
            nationality.genderFormPairs(profile: LearnerProfile(country: Self.us))
                == [FormPair("americano", "americana")])
    }

    /// Accent-sensitive words: leaving the accent off (or adding one) makes another word; the wrong accent is a slip.
    @Test func theWrongAccentOnAnAccentSensitiveWordIsAlmost() throws {
        let gap = try AnswerPattern.clozeGap("è")
        let wrongAccent = grader.grade("é", accepted: gap)
        #expect(wrongAccent.outcome == .almost)
        #expect(wrongAccent.hintKind == .spelling)
        #expect(wrongAccent.mismatches == [0])
        #expect(grader.grade("e", accepted: gap).outcome == .wrong)
        #expect(grader.grade("Lei é americano", accepted: try AnswerPattern("Lei è americano")).outcome == .almost)
        #expect(grader.grade("si", accepted: try AnswerPattern("sì")).outcome == .wrong)
        #expect(grader.grade("sí", accepted: try AnswerPattern("sì")).outcome == .almost)
        // Other words keep accent tolerance either way.
        #expect(grader.grade("perchè", accepted: try AnswerPattern("perché")).outcome == .correctWithNote)
    }

    /// The generic hint is about what makes the answer wrong, not an accent slip before it.
    @Test func hintKindComesFromTheFirstHardMismatch() throws {
        let forms = KnownForms(["lui": ["w:lui"], "lei": ["w:lei"]])
        let g = TypedAnswerGrader(knownForms: forms)
            .grade("perche lei è piu alto", accepted: try AnswerPattern("perché lui è più alto"))
        #expect(g.outcome == .wrong)
        #expect(g.mismatches == [0, 1, 3])
        #expect(g.hintKind == .realWord)
        // Without a hard mismatch, the first mismatch.
        #expect(grader.grade("perche lui è piu alto", accepted: try AnswerPattern("perché lui è più alto")).hintKind
            == .spelling)
    }

    @Test func gradedAnswerCarriesWhatFeedbackNeeds() throws {
        let forms = KnownForms(["un": ["g:indefinite-article"], "una": ["g:indefinite-article"]])
        let g = TypedAnswerGrader(knownForms: forms).grade("un spremuta", accepted: try AnswerPattern("una [spremuta]"))
        #expect(g.answer == GradedAnswer(outcome: .wrong, hintKind: .ending, mismatches: [0]))
    }
}


/// docs/02 budget: Check → feedback under 50 ms. The largest pattern allowed (512 expansions) with a 13-token
/// answer took about 380 ms in a debug build before pairings were cached per token (about 45 ms after; 225 ms →
/// 10 ms in release). The bound is generous so a slow CI machine passes, but the old cost per cell fails it.
@Suite struct TypedAnswerGraderPerformanceTests {
    @Test func aFullSizePatternGradesWellWithinBudget() throws {
        let p = try AnswerPattern(
            "(buongiorno )(vorrei ){un caffè|un cappuccino|una spremuta|un cornetto} {e|con} "
                + "{un caffè|un cappuccino|una spremuta|un cornetto}( per favore)( grazie)")
        #expect(p.expansionCount == AnswerPattern.expansionLimit)
        let response = "buongiorno io vorrei un capuccino con una spremutta per favore e grazie mille"
        #expect(Normalizer.tokens(response).count == 13)
        let grader = TypedAnswerGrader()
        let clock = ContinuousClock()
        var fastest = Duration.seconds(60)
        var grade: TypedGrade?
        for _ in 0..<3 {
            fastest = min(fastest, clock.measure { grade = grader.grade(response, accepted: p) })
        }
        #expect(grade?.outcome == .wrong)
        #expect(grade?.expansion?.text == "buongiorno vorrei un cappuccino con una spremuta per favore grazie")
        #expect(fastest < .milliseconds(200), "took \(fastest)")
    }
}

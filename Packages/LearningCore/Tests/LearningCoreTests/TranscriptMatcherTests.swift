import Foundation
import Testing

@testable import LearningCore

/// docs/05 § Speech transcripts; `fixtures/grading/transcripts.json`.
@Suite struct TranscriptMatcherTests {
    struct Fixture: Decodable {
        struct Case: Decodable {
            let accept: String
            /// What the pack builder writes for a pattern that spells (CL40).
            let spelling: [SpellingName]?
            let transcript: String
            let pass: Bool
        }
        let functionWords: [String]
        /// The letter items' names as the pack carries them (`items.letter` → `items.it`).
        let letterNames: [String: String]
        /// The doubling word (`c:doppia`'s `it`).
        let doubling: String
        /// The letters whose names the pack also has as ordinary words (`LetterNames(alsoWords:)`).
        let alsoWords: Set<String>
        /// A slice of the pack's `forms` table: [form, item].
        let forms: [[String]]
        let cases: [Case]

        var knownForms: KnownForms {
            KnownForms(rows: forms.compactMap { $0.count == 2 ? (form: $0[0], itemID: ItemID($0[1])) : nil })
        }
    }

    static func fixture() throws -> Fixture {
        try JSONDecoder().decode(Fixture.self, from: Fixtures.data("fixtures/grading/transcripts.json"))
    }

    @Test func functionWordsAreTheNormativeList() throws {
        #expect(TranscriptMatcher.functionWordList == (try Self.fixture().functionWords))
        #expect(TranscriptMatcher.functionWords.count == TranscriptMatcher.functionWordList.count)
    }

    @Test func everyTranscriptCase() throws {
        let fixture = try Self.fixture()
        #expect(fixture.cases.count >= 56)
        #expect(fixture.letterNames.count == 26)
        let matcher = TranscriptMatcher(letterNames: try Self.letters(), knownForms: fixture.knownForms)
        for c in fixture.cases {
            var accepted = try AnswerPattern(c.accept)
            accepted.spelling = c.spelling
            let match = try #require(matcher.match(transcript: c.transcript, accepted: accepted))
            #expect(match.passed == c.pass, "\(c.transcript) for \(c.accept)")
        }
    }

    let matcher = TranscriptMatcher()

    @Test func resultSaysWhatWasHeardAndFound() throws {
        let accept = try AnswerPattern("vorrei un cappuccino( per favore)")
        let match = try #require(matcher.match(transcript: "  Vorrei un caffè ", accepted: accept))
        #expect(!match.passed)
        #expect(match.heard == "Vorrei un caffè")
        #expect(match.heardTokens == ["vorrei", "un", "caffè"])
        #expect(match.foundWords == ["vorrei", "un"])
        #expect(match.answer.outcome == .wrong)
        // The learner said something else (caffè): no "Something's missing." hint; the UI shows "I heard: …".
        #expect(match.answer.hintKind == nil)
        #expect(match.answer.mismatches == [2])
        // The full expansion and the short one both miss cappuccino; the short one has the better ratio.
        #expect(match.expansion.text == "vorrei un cappuccino")
        #expect(match.contentHeard == 1 && match.contentTotal == 2)
    }

    @Test func eightyPercentOfContentTokens() throws {
        // Five content words; four heard is 80% and passes, three is 60% and fails.
        let accept = try AnswerPattern("domani mattina prendo treno presto")
        #expect(matcher.match(transcript: "domani mattina prendo il treno", accepted: accept)?.passed == true)
        #expect(matcher.match(transcript: "domani prendo il treno", accepted: accept)?.passed == false)
        // Function words don't count either way.
        let fn = try AnswerPattern("vado a Bologna con il treno")
        #expect(matcher.match(transcript: "vado Bologna treno", accepted: fn)?.passed == true)
    }

    @Test func focusTokensMustBeHeard() throws {
        let accept = try AnswerPattern("vorrei [un] cornetto per favore")
        #expect(matcher.match(transcript: "vorrei una cornetto per favore", accepted: accept)?.passed == false)
        #expect(matcher.match(transcript: "vorrei un cornetto per favore", accepted: accept)?.passed == true)
        #expect(matcher.match(transcript: "vorei un corneto per favore", accepted: accept)?.missingFocus == [])
    }

    @Test func bestAlternativeWins() throws {
        let accept = try AnswerPattern("sono di Toronto")
        let match = try #require(
            matcher.match(transcripts: ["sono di toro", "sono di Toronto", "sono Toronto"], accepted: [accept]))
        #expect(match.passed)
        #expect(match.transcriptIndex == 1)
        #expect(matcher.match(transcripts: [], accepted: [accept]) == nil)
    }

    @Test func numbersAndTimesInTranscripts() throws {
        #expect(matcher.match(transcript: "ho 30 anni", accepted: try AnswerPattern("ho trenta anni"))?.passed == true)
        #expect(
            matcher.match(transcript: "ho 30 anni", accepted: try AnswerPattern("ho {NUMBER} anni"))?.passed == true)
        let time = try AnswerPattern("alle quindici e trenta")
        #expect(matcher.match(transcript: "alle 15:30", accepted: time)?.passed == true)
        #expect(matcher.match(transcript: "alle 15.30", accepted: time)?.passed == true)
        // H.MM with no cue: either reading.
        let price = try AnswerPattern("sei euro e venti")
        let clock = try AnswerPattern("sono le sei e venti")
        #expect(matcher.match(transcript: "6.20", accepted: price)?.passed == true)
        #expect(matcher.match(transcript: "sono 6.20", accepted: try AnswerPattern("sono sei e venti"))?.passed == true)
        #expect(matcher.match(transcript: "sono le 6.20", accepted: clock)?.passed == true)
        // (The price reading holds every word of the time reading but for una/un, and extra words don't count.)
        let one = try AnswerPattern("[una] e trenta")
        let heard = try #require(matcher.match(transcript: "all'incirca 1.30", accepted: one))
        #expect(heard.passed)
        #expect(heard.heardTokens == ["all'incirca", "una", "e", "trenta"])
    }

    @Test func aOneBeforeAWordIsAnyArticle() throws {
        let one = try AnswerPattern("[un] caffè e [una] spremuta")
        #expect(matcher.match(transcript: "1 caffè e 1 spremuta", accepted: one)?.passed == true)
        #expect(matcher.match(transcript: "2 caffè e 1 spremuta", accepted: one)?.passed == false)
        let uno = try AnswerPattern("ne voglio [uno]")
        #expect(matcher.match(transcript: "ne voglio 1", accepted: uno)?.passed == true)
    }

    @Test func strictFormsApply() throws {
        let accept = try AnswerPattern("sono {m:nato|f:nata} a Toronto")
        let strict = TranscriptMatcher(profile: LearnerProfile(forms: .m, strictForms: true))
        #expect(
            strict.match(transcript: "sono nata a Toronto", accepted: accept)?.expansion.text == "sono nato a toronto")
        #expect(matcher.match(transcript: "sono nata a Toronto", accepted: accept)?.missing == [])
    }

    // MARK: - Spoken spelling (CL25)

    static func letters() throws -> LetterNames {
        let fixture = try fixture()
        return LetterNames(fixture.letterNames, doubling: fixture.doubling, alsoWords: fixture.alsoWords)
    }

    /// A pattern as the pack gives it when it spells: `spelling` names every letter it uses (CL40).
    static func spelled(_ source: String, _ names: [String: String?]) throws -> AnswerPattern {
        var pattern = try AnswerPattern(source)
        pattern.spelling = names.map { SpellingName(name: $0.key, letter: $0.value) }.sorted { $0.name < $1.name }
        return pattern
    }

    @Test func spelledLettersBecomeTheirNames() throws {
        let spelling = TranscriptMatcher(letterNames: try Self.letters())
        let marco = try AnswerPattern("emme, a, erre, ci, o")
        // However the recogniser writes the letters (case, hyphens, periods, commas), they read as the names.
        let variants = ["M A R C O", "m a r c o", "M-A-R-C-O", "m-a-r-c-o", "m. a. r. c. o.", "M,A,R,C,O", "M.A.R.C.O."]
        for transcript in variants {
            let match = try #require(spelling.match(transcript: transcript, accepted: marco))
            #expect(match.passed, "\(transcript)")
            #expect(match.heardTokens == ["emme", "a", "erre", "ci", "o"], "\(transcript)")
            // "I heard: …" shows what the recogniser wrote, not the names.
            #expect(match.heard == transcript)
        }
        let double = try #require(spelling.match(transcript: "Doppia S", accepted: try AnswerPattern("doppia esse")))
        #expect(double.passed && double.heardTokens == ["doppia", "esse"])
        // J and W have two-word names.
        let jw = try #require(spelling.match(transcript: "J W", accepted: try AnswerPattern("i lunga, doppia vu")))
        #expect(jw.passed && jw.heardTokens == ["i", "lunga", "doppia", "vu"])
    }

    @Test func withoutLetterNamesNoSpokenSpellingPasses() throws {
        let marco = try AnswerPattern("emme, a, erre, ci, o")
        #expect(matcher.match(transcript: "M A R C O", accepted: marco)?.passed == false)
        #expect(matcher.match(transcript: "M A R C O", accepted: marco)?.heardTokens == ["m", "a", "r", "c", "o"])
    }

    @Test func ordinarySentencesAreUnchanged() throws {
        let spelling = TranscriptMatcher(letterNames: try Self.letters())
        // A vowel's name is the vowel itself, so a, e, i, o as words stay as they are; a hyphenated word isn't spelled.
        for transcript in [
            "Vado a Roma e poi a Milano.", "I ragazzi e le ragazze o i bambini?", "Mi scrivi una e-mail?",
            "Sì, è di Bologna.",
        ] {
            let accepted = try AnswerPattern(Normalizer.normalize(transcript))
            let match = try #require(spelling.match(transcript: transcript, accepted: accepted))
            #expect(match.passed, "\(transcript)")
            let unmapped = try #require(matcher.match(transcript: transcript, accepted: accepted))
            #expect(match.heardTokens == unmapped.heardTokens, "\(transcript)")
        }
    }

    // MARK: - Spelled answers (CL40)

    static let luca: [String: String?] = ["elle": "L", "u": "U", "ci": "C", "a": "A"]

    @Test func aSpellingIsRightOnlyLetterForLetter() throws {
        let spelling = TranscriptMatcher(letterNames: try Self.letters())
        let luca = try Self.spelled("elle, u, ci, a", Self.luca)
        let right = try #require(spelling.match(transcript: "L U C A", accepted: luca))
        #expect(right.passed && right.found == [0, 1, 2, 3])
        // Letters are content tokens, never function words: ci and a count.
        #expect(right.contentTotal == 4 && right.contentHeard == 4)
        for wrong in ["L U C O", "L U A", "L U C C A", "L U C A S", "U L C A"] {
            let miss = try #require(spelling.match(transcript: wrong, accepted: luca))
            #expect(!miss.passed, "\(wrong)")
            #expect(miss.missing == [0, 1, 2, 3] && miss.contentHeard == 0, "\(wrong)")
        }
        // Without the pack's spelling the same pattern is words: ci and a are function words, so L U C O passed.
        #expect(spelling.match(transcript: "L U C O", accepted: try AnswerPattern("elle, u, ci, a"))?.passed == true)
    }

    @Test func wordsAroundASpellingFollowTheUsualRule() throws {
        let spelling = TranscriptMatcher(letterNames: try Self.letters())
        let marco = try Self.spelled(
            "Mi chiamo Marco: emme, a, erre, ci, o", ["emme": "M", "a": "A", "erre": "R", "ci": "C", "o": "O"])
        // chiamo and marco are two content words: one heard is 50%, so the words fail even with every letter.
        #expect(spelling.match(transcript: "Mi chiamo Luigi, M A R C O", accepted: marco)?.passed == false)
        let heard = try #require(spelling.match(transcript: "chiamo Marco. M A R C O e tu?", accepted: marco))
        #expect(heard.passed && heard.missing == [0])  // mi is a function word
        #expect(heard.contentTotal == 7 && heard.contentHeard == 7)
        // The letters must be heard as letters: Marco said again is not a spelling.
        #expect(spelling.match(transcript: "Mi chiamo Marco, Marco", accepted: marco)?.passed == false)
    }

    @Test func acceptedVariantsAndDoubleLettersReadAsTheSameLetters() throws {
        let spelling = TranscriptMatcher(letterNames: try Self.letters())
        let rossi = try Self.spelled(
            "erre, o, doppia esse, i", ["erre": "R", "o": "O", "doppia": nil, "esse": "S", "i": "I"])
        for heard in ["R O S S I", "erre o doppia esse i", "R, O, doppia S, I", "R-O-S-S-I"] {
            #expect(spelling.match(transcript: heard, accepted: rossi)?.passed == true, "\(heard)")
        }
        #expect(spelling.match(transcript: "R O S I", accepted: rossi)?.passed == false)
        #expect(spelling.match(transcript: "R O S S S I", accepted: rossi)?.passed == false)
        let jones = try Self.spelled(
            "i lunga, o, enne, e, esse", ["i lunga": "J", "o": "O", "enne": "N", "e": "E", "esse": "S"])
        #expect(spelling.match(transcript: "J O N E S", accepted: jones)?.passed == true)
        #expect(spelling.match(transcript: "I O N E S", accepted: jones)?.passed == false)  // I is not J
        let venti = try Self.spelled(
            "{vu|vi}, e, enne, ti, i", ["vu": "V", "vi": "V", "e": "E", "enne": "N", "ti": "T", "i": "I"])
        #expect(spelling.match(transcript: "vi e enne ti i", accepted: venti)?.passed == true)
        #expect(spelling.match(transcript: "V E N T I", accepted: venti)?.passed == true)
    }

    @Test func ordinaryWordsStayFunctionWords() throws {
        let spelling = TranscriptMatcher(letterNames: try Self.letters())
        let sentence = try AnswerPattern("vado a Roma e poi a Milano o a Torino")
        let heard = try #require(spelling.match(transcript: "vado Roma poi Milano Torino", accepted: sentence))
        #expect(heard.passed && heard.contentTotal == 5)
    }

    // MARK: - Elisions (CL31)

    @Test func anElidedFormAndItsFullFormAreTheSame() throws {
        let forms = try Self.fixture().knownForms
        #expect(forms.elisions == ["anch'": "anche", "c'": "ci"])  // l' has several full forms: none
        let matcher = TranscriptMatcher(knownForms: forms)
        let model = try AnswerPattern("anche io sono di Bologna")
        let heard = try #require(matcher.match(transcript: "Anch'io sono di Bologna.", accepted: model))
        #expect(heard.passed && heard.heardTokens == ["anche", "io", "sono", "di", "bologna"])
        #expect(heard.heard == "Anch'io sono di Bologna.")
        let elided = try AnswerPattern("anch'io sono di Bologna")
        #expect(matcher.match(transcript: "anche io sono di Bologna", accepted: elided)?.passed == true)
        // Without the forms table a repeat of the model failed: anch'io is neither anche nor io.
        #expect(TranscriptMatcher().match(transcript: "Anch'io sono di Bologna.", accepted: model)?.passed == false)
    }

    @Test func otherElisionsAreUnchanged() throws {
        let forms = try Self.fixture().knownForms
        #expect(forms.elisionReadings(["l'amico", "di", "marco"]) == [["l'amico", "di", "marco"]])
        // The transcript as heard always comes first: c'è stays c'è.
        #expect(forms.elisionReadings(["c'è", "un", "bar"]).first == ["c'è", "un", "bar"])
        let matcher = TranscriptMatcher(knownForms: forms)
        let bar = try #require(matcher.match(transcript: "C'è un bar.", accepted: try AnswerPattern("c'è un bar")))
        #expect(bar.passed && bar.heardTokens == ["c'è", "un", "bar"])
        #expect(KnownForms.empty.elisionReadings(["anch'io"]) == [["anch'io"]])
    }
}


import Foundation
import Testing

@testable import LearningCore

/// docs/05 § Speech transcripts; `fixtures/grading/transcripts.json`.
@Suite struct TranscriptMatcherTests {
    struct Fixture: Decodable {
        struct Case: Decodable {
            let accept: String
            let transcript: String
            let pass: Bool
        }
        let functionWords: [String]
        /// The letter items' names as the pack carries them (`items.letter` → `items.it`).
        let letterNames: [String: String]
        let cases: [Case]
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
        #expect(fixture.cases.count >= 27)
        #expect(fixture.letterNames.count == 26)
        let matcher = TranscriptMatcher(letterNames: LetterNames(fixture.letterNames))
        for c in fixture.cases {
            let match = try #require(matcher.match(transcript: c.transcript, accepted: try AnswerPattern(c.accept)))
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

    static func letters() throws -> LetterNames { LetterNames(try fixture().letterNames) }

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
}


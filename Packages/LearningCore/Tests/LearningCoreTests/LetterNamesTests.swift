import Foundation
import Testing

@testable import LearningCore

/// Spoken spelling (docs/05 § Speech transcripts, step 2; CL25): the table the pack's letter items give.
@Suite struct LetterNamesTests {
    @Test func namesAreNormalisedAndKeysTakeEitherCase() {
        let names = LetterNames(["M": "Emme", "j": "I lunga", "W": "doppia vu"])
        #expect(names.count == 3)
        #expect(names.name(of: "m") == ["emme"])
        #expect(names.name(of: "M") == ["emme"])
        #expect(names.name(of: "J") == ["i", "lunga"])
        #expect(names.name(of: "x") == nil)
        #expect(names.name(of: "mm") == nil)
    }

    @Test func entriesThatArentOneLetterWithANameAreLeftOut() {
        let names = LetterNames(["MM": "emme emme", "1": "uno", "è": "e", "Q": " … ", "": "niente", "B": "bi"])
        #expect(names.count == 1)
        #expect(names.name(of: "b") == ["bi"])
        #expect(LetterNames.none.isEmpty)
        #expect(LetterNames.key("Z") == "z" && LetterNames.key("ß") == nil && LetterNames.key("-") == nil)
    }

    @Test func applyReplacesStandaloneLettersOnly() throws {
        let names = try TranscriptMatcherTests.letters()
        #expect(names.count == 26)
        #expect(names.apply(["m", "a", "r", "c", "o"]) == ["emme", "a", "erre", "ci", "o"])
        #expect(names.apply(["m-a-r-c-o"]) == ["emme", "a", "erre", "ci", "o"])
        #expect(names.apply(["doppia", "s"]) == ["doppia", "esse"])
        #expect(names.apply(["j", "w"]) == ["i", "lunga", "doppia", "vu"])
        // Words, hyphenated words, elisions, accented vowels and digits stay as they are.
        let words = ["e-mail", "l'acqua", "è", "sì", "marco", "a1", "c'è", "di", "ma-rco", "u"]
        #expect(names.apply(words) == words)
        #expect(LetterNames.none.apply(["m", "a"]) == ["m", "a"])
    }

    @Test func vowelsAreTheirOwnNames() throws {
        let names = try TranscriptMatcherTests.letters()
        for vowel in ["a", "e", "i", "o", "u"] { #expect(names.name(of: vowel) == [vowel]) }
    }
}

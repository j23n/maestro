import Foundation
import Testing

@testable import LearningCore

/// docs/05 § Normalisation; `fixtures/grading/normalizer.json` is shared with the Python pipeline.
@Suite struct NormalizerTests {
    struct Fixture: Decodable {
        struct Case: Decodable {
            let `in`: String
            let out: String
        }
        let cases: [Case]
        let stripAccents: [Case]
        let accentSensitive: [String]
    }

    static func fixture() throws -> Fixture {
        try JSONDecoder().decode(Fixture.self, from: Fixtures.data("fixtures/grading/normalizer.json"))
    }

    @Test func everyNormalizerCase() throws {
        let fixture = try Self.fixture()
        #expect(fixture.cases.count >= 18)
        for c in fixture.cases {
            let out = Normalizer.normalize(c.in)
            #expect(out == c.out, "normalize(\(c.in.debugDescription))")
            // Byte-for-byte NFC, not just canonically equivalent (Swift's == ignores normalisation form).
            #expect(Array(out.unicodeScalars) == Array(c.out.precomposedStringWithCanonicalMapping.unicodeScalars))
        }
    }

    @Test func nfdInputBecomesNFC() {
        let nfd = "perche\u{0301}"
        let out = Normalizer.normalize(nfd)
        #expect(Array(out.unicodeScalars) == Array("perch\u{00E9}".unicodeScalars))
    }

    @Test func everyStripAccentsCase() throws {
        for c in try Self.fixture().stripAccents {
            #expect(Normalizer.stripAccents(c.in) == c.out)
        }
        #expect(Normalizer.stripAccents("perche\u{0301}") == "perche")
        #expect(Normalizer.stripAccents("PERCHÉ") == "PERCHE")
    }

    @Test func accentSensitiveSetMatchesFixture() throws {
        #expect(Normalizer.accentSensitiveWords == Set(try Self.fixture().accentSensitive))
        #expect(Normalizer.isAccentSensitive("è"))
        #expect(!Normalizer.isAccentSensitive("perché"))
    }

    @Test func tokensAreTheSpaceSeparatedParts() {
        #expect(Normalizer.tokens("Vorrei un caffè, per favore.") == ["vorrei", "un", "caffè", "per", "favore"])
        #expect(Normalizer.tokens("  ") == [])
        #expect(Normalizer.tokens("Un' amica") == ["un'amica"])
    }

    @Test func displayTokensKeepTheCaseAndMatchTheTokens() {
        let texts = ["Mi chiamo  ANNA Maria, e Lei?", "PERCHE\u{0301} l’ Acqua", "Sono 6,20 Euro.", "E-MAIL - Ciao", ""]
        for text in texts {
            let display = Normalizer.displayTokens(text)
            #expect(display.map(Normalizer.lowercase) == Normalizer.tokens(text), "\(text)")
        }
        #expect(Normalizer.displayTokens(texts[0]) == ["Mi", "chiamo", "ANNA", "Maria", "e", "Lei"])
        #expect(Normalizer.displayTokens("PERCHE\u{0301} l’ Acqua") == ["PERCHÉ", "l'Acqua"])
    }

    @Test func otherAccentSensitiveWord() {
        #expect(Normalizer.isOtherAccentSensitiveWord("e", "è"))
        #expect(Normalizer.isOtherAccentSensitiveWord("sì", "si"))
        #expect(!Normalizer.isOtherAccentSensitiveWord("é", "è"))
        #expect(!Normalizer.isOtherAccentSensitiveWord("perche", "perché"))
    }

    @Test func lowercasingIsLocaleIndependent() {
        // Default Unicode case mapping, the same as it_IT: no Turkish dotless-i rules.
        #expect(Normalizer.normalize("ÈCCO IL CAFFÈ") == "ècco il caffè")
        #expect(Normalizer.normalize("ITALIA") == "italia")
        #expect(Normalizer.lowercase("I") == "i")
    }

    @Test func digitSeparatorsAndHyphens() {
        #expect(Normalizer.normalize("Alle 10:15.") == "alle 10:15")
        #expect(Normalizer.normalize("6.20") == "6.20")
        #expect(Normalizer.normalize("ore 10: bene") == "ore 10 bene")
        #expect(Normalizer.normalize("-ciao-") == "ciao")
        #expect(Normalizer.normalize("anni 20-30") == "anni 20 30")
        #expect(Normalizer.normalize("l ’ acqua") == "l'acqua")
        #expect(Normalizer.normalize("dov`è") == "dov'è")
    }
}

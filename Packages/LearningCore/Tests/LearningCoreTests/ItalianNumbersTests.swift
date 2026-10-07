import Foundation
import Testing

@testable import LearningCore

/// `ItalianNumbers` (docs/05 § Speech transcripts): words, prices and times.
@Suite struct ItalianNumbersTests {
    @Test func integersToWords() {
        let cases: [(Int, String)] = [
            (0, "zero"), (1, "uno"), (3, "tre"), (11, "undici"), (17, "diciassette"), (20, "venti"), (21, "ventuno"),
            (23, "ventitré"), (28, "ventotto"), (31, "trentuno"), (33, "trentatré"), (38, "trentotto"),
            (40, "quaranta"), (99, "novantanove"), (100, "cento"), (101, "centouno"), (103, "centotré"),
            (108, "centootto"), (150, "centocinquanta"), (200, "duecento"), (999, "novecentonovantanove"),
            (1000, "mille"), (1001, "milleuno"), (1003, "milletré"), (1100, "millecento"), (2000, "duemila"),
            (2023, "duemilaventitré"), (2026, "duemilaventisei"), (9999, "novemilanovecentonovantanove"),
        ]
        for (n, words) in cases {
            #expect(ItalianNumbers.words(n) == words, "\(n)")
        }
        #expect(ItalianNumbers.words(-1) == nil)
        #expect(ItalianNumbers.words(10_000) == nil)
    }

    @Test func wordsRoundTripForTheWholeRange() {
        for n in ItalianNumbers.range {
            guard let words = ItalianNumbers.words(n) else {
                Issue.record("no words for \(n)")
                continue
            }
            #expect(ItalianNumbers.integerValue(of: words) == n, "\(words)")
        }
    }

    @Test func wordsToIntegers() {
        #expect(ItalianNumbers.integerValue(of: "trenta") == 30)
        #expect(ItalianNumbers.integerValue(of: "Ventitre") == 23)
        #expect(ItalianNumbers.integerValue(of: "un") == 1)
        #expect(ItalianNumbers.integerValue(of: "una") == 1)
        #expect(ItalianNumbers.integerValue(of: "ventun") == 21)
        #expect(ItalianNumbers.integerValue(of: "centuno") == 101)
        #expect(ItalianNumbers.integerValue(of: "centotto") == 108)
        #expect(ItalianNumbers.integerValue(of: "centottanta") == 180)
        #expect(ItalianNumbers.integerValue(of: "30") == 30)
        #expect(ItalianNumbers.integerValue(of: "trentaa") == nil)
        #expect(ItalianNumbers.integerValue(of: "6,20") == nil)
        #expect(ItalianNumbers.integerValue(of: "") == nil)
    }

    @Test func prices() {
        #expect(ItalianNumbers.priceWords(euros: 6, cents: 20) == "sei euro e venti")
        #expect(ItalianNumbers.priceWords(euros: 1, cents: 60) == "un euro e sessanta")
        #expect(ItalianNumbers.priceWords(euros: 3, cents: 0) == "tre euro")
        #expect(ItalianNumbers.priceWords(euros: 0, cents: 50) == "cinquanta centesimi")
        #expect(ItalianNumbers.priceWords(euros: 2, cents: 5) == "due euro e cinque")
        #expect(ItalianNumbers.priceWords(euros: 1, cents: 100) == nil)
        #expect(ItalianNumbers.spellOut("6,20 €") == "sei euro e venti")
        #expect(ItalianNumbers.spellOut("6.20") == "sei euro e venti")
        #expect(ItalianNumbers.spellOut("€ 6,20") == "sei euro e venti")
        #expect(ItalianNumbers.spellOut("€6.20") == "sei euro e venti")
        #expect(ItalianNumbers.spellOut("1,60") == "un euro e sessanta")
        #expect(ItalianNumbers.spellOut("sono 3 euro") == "sono tre euro")
        #expect(ItalianNumbers.spellOut("sono 3 €") == "sono tre euro")
        #expect(ItalianNumbers.spellOut("1 euro") == "un euro")
        #expect(ItalianNumbers.spellOut("costa 1,50 euro, grazie") == "costa un euro e cinquanta , grazie")
        #expect(ItalianNumbers.spellOut("2,5 €") == "due euro e cinquanta")
    }

    @Test func times() {
        #expect(ItalianNumbers.timeWords(hour: 10, minute: 15) == "dieci e quindici")
        #expect(ItalianNumbers.timeWords(hour: 13, minute: 30) == "tredici e trenta")
        #expect(ItalianNumbers.timeWords(hour: 8, minute: 0) == "otto")
        #expect(ItalianNumbers.timeWords(hour: 1, minute: 0) == "una")
        #expect(ItalianNumbers.timeWords(hour: 21, minute: 45) == "ventuno e quarantacinque")
        #expect(ItalianNumbers.timeWords(hour: 25, minute: 0) == nil)
        #expect(ItalianNumbers.timeWords(hour: 10, minute: 60) == nil)
        #expect(ItalianNumbers.spellOut("alle 10:15") == "alle dieci e quindici")
        #expect(ItalianNumbers.spellOut("Il treno parte alle 13:30.") == "Il treno parte alle tredici e trenta .")
        #expect(ItalianNumbers.spellOut("all'1:00") == "all' una")
    }

    @Test func plainNumbersAndThingsLeftAlone() {
        #expect(ItalianNumbers.spellOut("ho 30 anni") == "ho trenta anni")
        #expect(ItalianNumbers.spellOut("nel 2026") == "nel duemilaventisei")
        #expect(ItalianNumbers.spellOut("1.500 persone") == "millecinquecento persone")
        #expect(ItalianNumbers.spellOut("livello A1") == "livello A1")
        #expect(ItalianNumbers.spellOut("12345 km") == "12345 km")
        #expect(ItalianNumbers.spellOut("6,2") == "6,2")
        #expect(ItalianNumbers.spellOut("nessun numero") == "nessun numero")
        #expect(ItalianNumbers.spellOut("") == "")
    }
}

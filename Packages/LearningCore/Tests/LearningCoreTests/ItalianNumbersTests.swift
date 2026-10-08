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
            (108, "centotto"), (150, "centocinquanta"), (180, "centottanta"), (188, "centottantotto"),
            (200, "duecento"), (280, "duecentottanta"), (308, "trecentotto"), (999, "novecentonovantanove"),
            (1000, "mille"), (1001, "milleuno"), (1003, "milletré"), (1008, "milleotto"), (1080, "milleottanta"),
            (1100, "millecento"), (1108, "millecentotto"), (2000, "duemila"),
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
        // The full forms are still understood.
        #expect(ItalianNumbers.integerValue(of: "centootto") == 108)
        #expect(ItalianNumbers.integerValue(of: "centoottanta") == 180)
        #expect(ItalianNumbers.integerValue(of: "duecentoottanta") == 280)
        #expect(ItalianNumbers.integerValue(of: "centouno") == 101)
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

    /// `H.MM` is how Italian writes times too: after a time cue it is a time, with a currency a price, and with
    /// neither the matchers try both readings.
    @Test func dottedTimesAndPrices() {
        #expect(ItalianNumbers.spellOut("alle 15.30") == "alle quindici e trenta")
        #expect(ItalianNumbers.spellOut("Il treno parte alle 15.30.") == "Il treno parte alle quindici e trenta .")
        #expect(ItalianNumbers.spellOut("dalle 9.00 alle 13.00") == "dalle nove alle tredici")
        #expect(ItalianNumbers.spellOut("sono le 6.20") == "sono le sei e venti")
        #expect(ItalianNumbers.spellOut("ore 8.15") == "ore otto e quindici")
        #expect(ItalianNumbers.spellOut("verso 7.45") == "verso sette e quarantacinque")
        #expect(ItalianNumbers.spellOut("all’1.30") == "all’ una e trenta")
        #expect(ItalianNumbers.spellOut("costa 6.20 €") == "costa sei euro e venti")
        #expect(ItalianNumbers.spellOut("alle 6.20 euro") == "alle sei euro e venti")  // a currency wins
        #expect(ItalianNumbers.spellOut("alle 6,20") == "alle sei euro e venti")  // a comma is never a time
        // A bare hour after a time cue: 1 is una.
        #expect(ItalianNumbers.spellOut("all'1") == "all' una")
        #expect(ItalianNumbers.spellOut("alle 3") == "alle tre")
        // Neither: both readings, the price first.
        #expect(ItalianNumbers.spellOutReadings("6.20") == ["sei euro e venti", "sei e venti"])
        #expect(ItalianNumbers.spellOutReadings("costa 1.50") == ["costa un euro e cinquanta", "costa una e cinquanta"])
        #expect(ItalianNumbers.spellOutReadings("costa 1.60") == ["costa un euro e sessanta"])  // not a time
        #expect(ItalianNumbers.spellOutReadings("alle 15.30") == ["alle quindici e trenta"])
        #expect(ItalianNumbers.spellOutReadings("6,20") == ["sei euro e venti"])
        #expect(ItalianNumbers.spellOutReadings("99.99") == ["novantanove euro e novantanove"])  // not a time
        #expect(ItalianNumbers.spellOutReadings("ho 30 anni") == ["ho trenta anni"])
    }

    /// A `1` before a word is an article whose gender the digit doesn't say: it stays, and matches un/uno/una/un'.
    @Test func oneBeforeAWordIsAnyArticle() {
        #expect(ItalianNumbers.spellOut("1 caffè e 1 spremuta") == "1 caffè e 1 spremuta")
        #expect(ItalianNumbers.spellOut("ne voglio 1") == "ne voglio uno")
        #expect(ItalianNumbers.spellOut("1 euro") == "un euro")
        #expect(ItalianNumbers.spellOut("2 caffè") == "due caffè")
        for article in ["un", "uno", "una", "un'"] {
            #expect(ItalianNumbers.matchesSpoken(expected: article, heard: "1"))
        }
        #expect(!ItalianNumbers.matchesSpoken(expected: "due", heard: "1"))
        #expect(!ItalianNumbers.matchesSpoken(expected: "un", heard: "una"))
        #expect(ItalianNumbers.matchesSpoken(expected: "caffè", heard: "caffè"))
    }

    @Test func plainNumbersAndThingsLeftAlone() {
        #expect(ItalianNumbers.spellOut("ho 30 anni") == "ho trenta anni")
        #expect(ItalianNumbers.spellOut("nel 2026") == "nel duemilaventisei")
        #expect(ItalianNumbers.spellOut("1.500 persone") == "millecinquecento persone")
        #expect(ItalianNumbers.spellOut("livello A1") == "livello A1")
        // Digits followed by a letter or an ordinal or degree mark stay too.
        #expect(ItalianNumbers.spellOut("la 3a classe") == "la 3a classe")
        #expect(ItalianNumbers.spellOut("il 1º maggio") == "il 1º maggio")
        #expect(ItalianNumbers.spellOut("la 2ª volta") == "la 2ª volta")
        #expect(ItalianNumbers.spellOut("fa 20° oggi") == "fa 20° oggi")
        #expect(ItalianNumbers.spellOut("alle 3pm") == "alle 3pm")
        #expect(ItalianNumbers.spellOut("3,50euro") == "tre euro e cinquanta")
        #expect(ItalianNumbers.spellOut("12345 km") == "12345 km")
        #expect(ItalianNumbers.spellOut("6,2") == "6,2")
        #expect(ItalianNumbers.spellOut("nessun numero") == "nessun numero")
        #expect(ItalianNumbers.spellOut("") == "")
    }
}

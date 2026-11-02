import Foundation
import Testing
import LanguageCore
import LexiconKit
@testable import GrammarKit

func germanDatabase() throws -> ContentDatabase {
    let url = try #require(Bundle.module.url(forResource: "content-de", withExtension: "sqlite", subdirectory: "Fixtures"))
    return try ContentDatabase(path: url.path)
}

@Suite struct GermanConjugatorTests {
    func table(_ id: String) throws -> ConjugationTable {
        try #require(Conjugator(content: try germanDatabase()).table(for: id))
    }

    @Test func simpleTensesFromTheDatabase() throws {
        let gehen = try table("de:gehen:v")
        #expect(gehen.form(for: FormTag("ind.prat.1s")!)?.text == "ging")
        #expect(gehen.form(for: FormTag("ind.prat.1s")!)?.isIrregular == true)
        #expect(gehen.form(for: FormTag("ind.pres.2s")!)?.isIrregular == false)
        #expect(gehen.row(for: FormTag("k2.prat.1s")!) == "ginge, gingest, ginge, gingen, ginget, gingen")
        #expect(gehen.blocks.first?.title == "Präsens")
    }

    @Test func weakVerbsAreRegular() throws {
        let machen = try table("de:machen:v")
        #expect(!machen.isIrregular)
        #expect(GermanRegularConjugator.forms(infinitive: "arbeiten", tag: FormTag("ind.pres.3s")!) == ["arbeitet"])
        #expect(GermanRegularConjugator.forms(infinitive: "reisen", tag: FormTag("ind.pres.2s")!) == ["reist"])
        // An e after a consonant and m or n, not after l, r, a lengthening h or a doubled consonant.
        #expect(GermanRegularConjugator.forms(infinitive: "öffnen", tag: FormTag("ind.pres.3s")!) == ["öffnet"])
        #expect(GermanRegularConjugator.forms(infinitive: "öffnen", tag: FormTag("ind.prat.1s")!) == ["öffnete"])
        #expect(GermanRegularConjugator.forms(infinitive: "rechnen", tag: FormTag("ind.pres.2s")!) == ["rechnest"])
        #expect(GermanRegularConjugator.forms(infinitive: "atmen", tag: FormTag("ind.pres.3s")!) == ["atmet"])
        #expect(GermanRegularConjugator.forms(infinitive: "lernen", tag: FormTag("ind.pres.2s")!) == ["lernst"])
        #expect(GermanRegularConjugator.forms(infinitive: "wohnen", tag: FormTag("ind.pres.3s")!) == ["wohnt"])
        #expect(GermanRegularConjugator.forms(infinitive: "kommen", tag: FormTag("ind.pres.2s")!) == ["kommst"])
        // -eln and -ern verbs may drop the stem's e in the 1s.
        #expect(GermanRegularConjugator.forms(infinitive: "sammeln", tag: FormTag("ind.pres.1s")!) == ["sammele", "sammle"])
        #expect(GermanRegularConjugator.forms(infinitive: "sammeln", tag: FormTag("ind.pres.3s")!) == ["sammelt"])
        #expect(GermanRegularConjugator.forms(infinitive: "sammeln", tag: FormTag("k1.pres.1p")!) == ["sammeln"])
        #expect(GermanRegularConjugator.forms(infinitive: "wandern", tag: FormTag("ind.pres.1s")!).contains("wandre"))
    }

    @Test func compoundTensesTakeTheirAuxiliary() throws {
        let c = Conjugator(content: try germanDatabase())
        #expect(c.text(lemmaID: "de:gehen:v", tag: FormTag("ind.perf.1s")!) == "bin gegangen")
        #expect(c.text(lemmaID: "de:machen:v", tag: FormTag("ind.perf.3s")!) == "hat gemacht")
        #expect(c.text(lemmaID: "de:machen:v", tag: FormTag("ind.pqp.1p")!) == "hatten gemacht")
        #expect(c.text(lemmaID: "de:gehen:v", tag: FormTag("ind.fut1.2s")!) == "wirst gehen")
        #expect(c.text(lemmaID: "de:gehen:v", tag: FormTag("ind.fut2.3s")!) == "wird gegangen sein")
        #expect(c.text(lemmaID: "de:machen:v", tag: FormTag("k2.wuerde.1s")!) == "würde machen")
        #expect(c.text(lemmaID: "de:gehen:v", tag: FormTag("k2.pqp.1s")!) == "wäre gegangen")
    }

    @Test func verbsTakingEitherAuxiliaryShowSeinAndSayWhich() throws {
        let fahren = try table("de:fahren:v")
        #expect(fahren.auxiliary == "both")
        #expect(fahren.form(for: FormTag("ind.perf.3s+s")!)?.text == "ist gefahren")
    }

    @Test func separableVerbsShowTheMainClauseOrder() throws {
        let anrufen = try table("de:anrufen:v")
        #expect(anrufen.form(for: FormTag("ind.pres.1s")!)?.text == "rufe an")
        #expect(anrufen.form(for: FormTag("imp.pres.2p")!)?.text == "ruft an")
        #expect(anrufen.form(for: FormTag("ind.perf.1s")!)?.text == "habe angerufen")
        #expect(anrufen.form(for: FormTag("ind.fut1.1s")!)?.text == "werde anrufen")
        #expect(Conjugator.separableParticle(infinitive: "anrufen", zuInfinitive: "anzurufen") == "an")
        #expect(Conjugator.separableParticle(infinitive: "besuchen", zuInfinitive: "zu besuchen") == nil)
        #expect(Conjugator.separableParticle(infinitive: "gehen", zuInfinitive: nil) == nil)
    }

    @Test func nounDeclension() throws {
        let haus = try #require(Decliner(content: try germanDatabase()).noun("de:Haus:n"))
        let gen = try #require(haus.rows.first { $0.grammaticalCase == .gen })
        #expect(gen.singular == "des Hauses")
        #expect(gen.plural == "der Häuser")
        #expect(haus.rows.first { $0.grammaticalCase == .dat }?.plural == "den Häusern")
    }

    @Test func adjectiveDeclension() throws {
        let gut = try #require(Decliner(content: try germanDatabase()).adjective("de:gut:adj"))
        #expect(gut.comparative == "besser")
        let strong = try #require(gut.blocks.first { $0.declension == .str })
        #expect(strong.forms[.nom]?[.ms] == "guter")
        #expect(strong.title == "stark")
    }

    @Test func italianTablesAreUnchanged() throws {
        let table = try #require(Conjugator(content: try fixtureDatabase()).table(for: "it:andare:v"))
        #expect(table.blocks.first?.title == "presente")
    }
}

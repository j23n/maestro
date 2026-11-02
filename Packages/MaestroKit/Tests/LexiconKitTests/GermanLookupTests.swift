import Foundation
import Testing
import LanguageCore
@testable import LexiconKit

func germanDatabase() throws -> ContentDatabase {
    let url = try #require(Bundle.module.url(forResource: "content-de", withExtension: "sqlite", subdirectory: "Fixtures"))
    return try ContentDatabase(path: url.path)
}

@Suite struct GermanLookupTests {
    func readings(_ query: String) throws -> [Reading] {
        guard case .readings(let readings) = Lookup(content: try germanDatabase()).lookup(query) else { return [] }
        return readings
    }

    @Test func databaseKnowsItsLanguage() throws {
        #expect(try germanDatabase().language == .de)
        #expect(try fixtureDatabase().language == .it)
    }

    @Test func nounsAreFoundWhateverTheCaseTyped() throws {
        #expect(try readings("haus").first?.lemma.id == "de:Haus:n")
        #expect(try readings("Haus").first?.lemma.id == "de:Haus:n")
    }

    @Test func nounAndVerbHomographsBothShow() throws {
        #expect(Set(try readings("essen").map(\.lemma.id)) == ["de:essen:v", "de:Essen:n"])
    }

    @Test func inflectedNounShowsItsCase() throws {
        let r = try #require(try readings("häusern").first)
        #expect(r.lemma.id == "de:Haus:n")
        #expect(r.caseTag == CaseTag("dat.pl"))
        #expect(r.analysis == "Haus · noun, Dativ Plural")
    }

    @Test func verbFormsUseGermanLabels() throws {
        let r = try #require(try readings("ging").first)
        #expect(r.lemma.id == "de:gehen:v")
        #expect(r.formTag?.description == "ind.prat.1s" || r.formTag?.description == "ind.prat.3s")
        #expect(try readings("ginge").contains { $0.analysis == "gehen · Konjunktiv II Präteritum · ich" })
    }

    @Test func umlautsTypedAsTwoLetters() throws {
        #expect(try readings("haeuser").first?.lemma.id == "de:Haus:n")
    }

    @Test func eszettTypedAsDoubleS() throws {
        guard case .suggestions(let found) = Lookup(content: try germanDatabase()).lookup("strasse") else {
            Issue.record("expected suggestions"); return
        }
        #expect(found.first?.id == "de:Straße:n")
    }

    @Test func compoundsReadThroughTheirLastPart() throws {
        let r = try #require(try readings("Haustür").first)
        #expect(r.lemma.id == "de:Tür:n")
        #expect(r.via == .compound(parts: ["Haus", "Tür"]))
        #expect(try readings("Gifttür").first?.lemma.id == "de:Tür:n")
        #expect(try readings("Xyzqtür").isEmpty, "the first part must be a word too")
    }

    @Test func separableVerbsJoinTheirParticle() throws {
        let lookup = Lookup(content: try germanDatabase())
        let r = try #require(lookup.readings(verb: "rufe", particle: "an").first)
        #expect(r.lemma.id == "de:anrufen:v")
        #expect(r.formTag?.description == "ind.pres.1s")
        #expect(r.via == .separable(particle: "an"))
    }

    @Test func italianStepsDoNotRunForGerman() throws {
        // "machen" ends like an Italian clitic cluster (-ne); German lookup finds the verb itself.
        #expect(try readings("machen").first?.lemma.id == "de:machen:v")
    }

    @Test func articlesAndGenders() throws {
        let entry = try #require(try germanDatabase().entry("de:Haus:n"))
        #expect(entry.headwordWithArticle == "das Haus")
        #expect(entry.genderLabel == "neuter")
        #expect(entry.plural == "Häuser")
    }
}

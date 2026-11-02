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

    @Test func aNounSpelledAlikeInSeveralCasesShowsOnce() throws {
        // Haus is nominative, accusative and dative: one row, labeled as the headword.
        let haus = try readings("Haus").filter { $0.lemma.id == "de:Haus:n" }
        #expect(haus.count == 1)
        #expect(haus.first?.formLine == nil)
        // Häuser is nominative, accusative and genitive plural: one row, labeled Plural.
        let hauser = try readings("häuser").filter { $0.lemma.id == "de:Haus:n" }
        #expect(hauser.count == 1)
        #expect(hauser.first?.formLine == "Plural")
        #expect(try readings("häusern").first?.formLine == "Dativ Plural")
    }

    @Test func formsThatAreNoNominativeKeepEveryCase() throws {
        let lemma = try #require(try germanDatabase().lemmas(headword: "Haus").first)
        func reading(_ tag: String, _ surface: String) -> Reading {
            Reading(lemma: lemma, formTag: nil, genderNumber: nil, surface: surface, via: .form, caseTag: CaseTag(tag))
        }
        let weak = Lookup.collapsingCases(["acc.ms", "dat.ms", "gen.ms", "nom.pl", "acc.pl"].map { reading($0, "Menschen") })
        #expect(weak.compactMap(\.caseTag?.description) == ["acc.ms", "dat.ms", "gen.ms", "nom.pl"])
        // An article's cases group by gender and number: der's feminine and plural cases stay beside nom.ms.
        let article = Lookup.collapsingCases(["nom.ms", "gen.fs", "dat.fs", "gen.pl"].map { reading($0, "der") })
        #expect(article.compactMap(\.caseTag?.description) == ["nom.ms", "gen.fs", "dat.fs", "gen.pl"])
    }

    @Test func formLinesNameOnlyWhatTheHeadwordDoesNot() throws {
        let lemma = try #require(try germanDatabase().lemmas(headword: "Haus").first)
        func line(_ tag: String, _ surface: String = "Haus") -> String? {
            Reading(lemma: lemma, formTag: nil, genderNumber: nil, surface: surface, via: .form, caseTag: CaseTag(tag)).formLine
        }
        #expect(line("nom.ns") == nil)
        #expect(line("nom.ns", "haus") == nil)
        #expect(line("nom.fs", "die") == "feminin Singular")
        #expect(line("acc.ns") == "Akkusativ neutral Singular")
        #expect(line("nom.pl") == "Plural")
        #expect(line("wk.nom.ms") == "schwach, Nominativ maskulin Singular")
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

    @Test func compoundsTypedWithoutUmlauts() throws {
        #expect(try readings("haustuer").first?.lemma.id == "de:Tür:n")
    }

    @Test func separableVerbsJoinTheirParticle() throws {
        #expect(try readings("rufe an").first?.lemma.id == "de:anrufen:v")
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

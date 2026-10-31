import Foundation
import Testing
import ItalianCore
@testable import LexiconKit

func fixtureDatabase() throws -> ContentDatabase {
    let url = try #require(Bundle.module.url(forResource: "content", withExtension: "sqlite", subdirectory: "Fixtures"))
    return try ContentDatabase(path: url.path)
}

@Suite struct LookupTests {
    @Test func exactHeadword() throws {
        let lookup = Lookup(content: try fixtureDatabase())
        guard case .readings(let readings) = lookup.lookup("treno") else {
            Issue.record("expected readings"); return
        }
        #expect(readings.first?.lemma.id == "it:treno:n")
    }

    @Test func inflectedFormShowsParse() throws {
        let lookup = Lookup(content: try fixtureDatabase())
        guard case .readings(let readings) = lookup.lookup("andavamo") else {
            Issue.record("expected readings"); return
        }
        let r = try #require(readings.first)
        #expect(r.lemma.id == "it:andare:v")
        #expect(r.formTag?.description == "ind.impf.1p")
        #expect(r.analysis == "andare · indicativo imperfetto · noi")
    }

    @Test func ambiguousFormListsEveryReading() throws {
        let lookup = Lookup(content: try fixtureDatabase())
        guard case .readings(let readings) = lookup.lookup("pesche") else {
            Issue.record("expected readings"); return
        }
        #expect(Set(readings.map(\.lemma.id)) == ["it:pesca:n", "it:pesca:n:2"])
    }

    @Test func accentInsensitiveSuggestion() throws {
        let lookup = Lookup(content: try fixtureDatabase())
        switch lookup.lookup("ando") {
        case .readings(let r): #expect(r.contains { $0.lemma.id == "it:andare:v" })
        case .suggestions(let s): #expect(s.contains { $0.id == "it:andare:v" })
        default: Issue.record("expected a hit for ando")
        }
    }

    @Test func severalWordsOfferTranslation() throws {
        let lookup = Lookup(content: try fixtureDatabase())
        #expect(lookup.lookup("il treno parte presto") == .phrase("il treno parte presto"))
    }

    @Test func emptyInput() throws {
        #expect(Lookup(content: try fixtureDatabase()).lookup("   ") == .empty)
    }

    @Test func englishSearch() throws {
        let db = try fixtureDatabase()
        #expect(db.englishMatches("grandfather").contains { $0.id == "it:nonno:n" })
    }

    @Test func entryHasSenses() throws {
        let entry = try #require(try fixtureDatabase().entry("it:andare:v"))
        #expect(entry.senses.first?.gloss == "to go")
        #expect(entry.auxiliary == "essere")
    }

    @Test func cliticCandidates() {
        let c = CliticSplitter.candidates(for: "dammelo")
        #expect(c.contains { $0.base == "da'" && $0.clitics == ["me", "lo"] })
    }
}

import Foundation
import Testing
import ItalianCore
import LexiconKit
@testable import GrammarKit

func fixtureDatabase() throws -> ContentDatabase {
    let url = try #require(Bundle.module.url(forResource: "content", withExtension: "sqlite", subdirectory: "Fixtures"))
    return try ContentDatabase(path: url.path)
}

@Suite struct ConjugatorTests {
    @Test func simpleTensesFromTheDatabase() throws {
        let table = try #require(Conjugator(content: try fixtureDatabase()).table(for: "it:andare:v"))
        #expect(table.form(for: FormTag("ind.pres.1s")!)?.text == "vado")
        #expect(table.form(for: FormTag("ind.pres.1s")!)?.isIrregular == true)
        #expect(table.form(for: FormTag("ind.impf.1p")!)?.isIrregular == false)
        #expect(table.isIrregular)
    }

    @Test func compoundTensesWithEssereAgree() throws {
        let c = Conjugator(content: try fixtureDatabase())
        #expect(c.text(lemmaID: "it:andare:v", tag: FormTag("cond.pass.1p")!) == "saremmo andati/e")
        #expect(c.text(lemmaID: "it:andare:v", tag: FormTag("ind.pp.3s")!) == "è andato/a")
    }

    @Test func compoundTensesWithAvere() throws {
        let c = Conjugator(content: try fixtureDatabase())
        #expect(c.text(lemmaID: "it:mangiare:v", tag: FormTag("ind.pp.1s")!) == "ho mangiato")
    }

    @Test func rowForCardBack() throws {
        let table = try #require(Conjugator(content: try fixtureDatabase()).table(for: "it:andare:v"))
        #expect(table.row(for: FormTag("cond.pres.1s")!) == "andrei, andresti, andrebbe, andremmo, andreste, andrebbero")
    }

    @Test func regularParadigms() {
        #expect(RegularConjugator.forms(infinitive: "parlare", tag: FormTag("ind.pres.1p")!).contains("parliamo"))
        #expect(RegularConjugator.forms(infinitive: "cercare", tag: FormTag("ind.fut.1s")!).contains("cercherò"))
        #expect(RegularConjugator.forms(infinitive: "finire", tag: FormTag("ind.pres.1s")!).contains("finisco"))
    }

    @Test func nonVerbsHaveNoTable() throws {
        #expect(Conjugator(content: try fixtureDatabase()).table(for: "it:treno:n") == nil)
    }
}

@Suite struct MarkdownBlockTests {
    @Test func parsesTopicBody() {
        let body = """
        ## When it's used

        For a *completed* action.
        Second line.

        - one
        - two

        | | parlare |
        | --- | --- |
        | io | parlo |
        """
        let blocks = MarkdownBlock.parse(body)
        #expect(blocks == [
            .heading("When it's used"),
            .paragraph("For a *completed* action. Second line."),
            .list(["one", "two"]),
            .table(header: ["", "parlare"], rows: [["io", "parlo"]]),
        ])
    }
}

import Foundation
import Testing
@testable import PackKit

@Suite struct PackKitTests {
    func library() throws -> PackLibrary {
        let dir = try #require(Bundle.module.url(forResource: "Fixtures", withExtension: nil))
        return PackLibrary(directories: [dir])
    }

    @Test func loadsManifestAndText() throws {
        let lib = try library()
        #expect(lib.packs.map(\.id) == ["racconti-brevi"])
        let text = try lib.load("racconti-brevi-03")
        #expect(text.title == "Il treno per Bologna")
        #expect(!text.sentences.isEmpty)
    }

    @Test func rangesSliceTheText() throws {
        let text = try library().load("racconti-brevi-03")
        for block in text.blocks {
            for sentence in block.sentences {
                #expect(block.text.substring(sentence.r) == sentence.text)
                for token in sentence.tokens {
                    #expect(sentence.text.substring(token.r) == token.t)
                }
            }
        }
    }

    @Test func tokensCarryAnalyses() throws {
        let text = try library().load("racconti-brevi-03")
        let first = try #require(text.sentence("s1"))
        let eravamo = try #require(first.tokens.first { $0.t == "eravamo" })
        #expect(eravamo.formTag?.description == "ind.impf.1p")
        #expect(eravamo.lemmaID == "it:essere:v")
        #expect(first.tokenIndex(at: 8) == 1)
    }

    @Test func questions() throws {
        let text = try library().load("racconti-brevi-03")
        let q1 = try #require(text.questions.first)
        #expect(q1.isCorrect(1))
        #expect(!q1.isCorrect(0))
        #expect(q1.choices(english: true).count == 3)
    }

    @Test func knownWords() {
        let counts = ["a": 8, "b": 1, "c": 1]
        #expect(KnownWords.fraction(lemmaCounts: counts, known: ["a", "b"]) == 0.9)
        let known = KnownWords.knownLemmas(kept: ["k"], finishedTexts: [["a": 1, "b": 2], ["a": 3]])
        #expect(known == ["k", "a"])
    }
}

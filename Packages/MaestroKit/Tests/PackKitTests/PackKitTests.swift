import Foundation
import Testing
import LanguageCore
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

    @Test func germanTokensCarryCase() throws {
        let json = #"""
        {"id": "s1", "r": [0, 13], "text": "im neuen Haus", "translation": "in the new house", "tokens": [
          {"t": "im", "r": [0, 2], "parts": [{"t": "in", "pos": "ADP", "lemmaID": "de:in:prep"},
                                             {"t": "dem", "pos": "DET", "lemmaID": "de:der:art", "case": "dat", "gn": "ns"}]},
          {"t": "neuen", "r": [3, 5], "pos": "ADJ", "lemmaID": "de:neu:adj", "case": "dat", "gn": "ns", "decl": "wk"},
          {"t": "Haus", "r": [9, 4], "pos": "NOUN", "lemmaID": "de:Haus:n", "case": "dat", "gn": "ns"}]}
        """#
        let sentence = try JSONDecoder().decode(Sentence.self, from: Data(json.utf8))
        #expect(sentence.tokens[2].caseTag?.label == "Dativ neutral Singular")
        #expect(sentence.tokens[1].caseTag?.description == "wk.dat.ns")
        #expect(sentence.tokens[0].parts?[1].caseTag?.description == "dat.ns")
        #expect(sentence.tokens[2].genderNumber == nil, "German numbers aren't Italian gender-number")
    }

    @Test func yesNoChoicesFollowTheTextLanguage() throws {
        let json = #"{"id": "q1", "type": "yesNoNotStated", "prompt": "Ist es kalt?", "promptEN": "Is it cold?", "answer": "yes", "answerSentences": ["s1"]}"#
        let question = try JSONDecoder().decode(Question.self, from: Data(json.utf8))
        #expect(question.choices(english: false, language: .de) == ["Ja", "Nein", "Steht nicht im Text"])
        #expect(question.choices(english: false) == ["Sì", "No", "Non si dice"])
    }

    @Test func knownWords() {
        let counts = ["a": 8, "b": 1, "c": 1]
        #expect(KnownWords.fraction(lemmaCounts: counts, known: ["a", "b"]) == 0.9)
        let known = KnownWords.knownLemmas(kept: ["k"], finishedTexts: [["a": 1, "b": 2], ["a": 3]])
        #expect(known == ["k", "a"])
    }
}

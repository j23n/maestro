import Foundation
import Testing

@testable import LearningCore

/// docs/03 § The answer-pattern language; `fixtures/grading/patterns.json` is shared with the Python pipeline.
@Suite struct AnswerPatternTests {
    struct Fixture: Decodable {
        struct Case: Decodable {
            let pattern: String
            let expansions: [String]?
            let focus: [[Int]]?
            let gender: [String]?
            let count: Int?
            let first: String?
            let slots: [String]?
            let error: String?
        }
        let cases: [Case]
    }

    @Test func everyPatternCase() throws {
        let fixture = try JSONDecoder().decode(Fixture.self, from: Fixtures.data("fixtures/grading/patterns.json"))
        #expect(fixture.cases.count >= 20)
        for c in fixture.cases {
            if let expectedError = c.error {
                do {
                    _ = try AnswerPattern(c.pattern)
                    Issue.record("\(c.pattern) must fail with \(expectedError)")
                } catch {
                    #expect(error.description == expectedError)
                }
                continue
            }
            let pattern = try AnswerPattern(c.pattern)
            let expansions = pattern.expansions()
            if let expected = c.expansions {
                #expect(expansions.map(\.text) == expected, "\(c.pattern)")
            }
            if let focus = c.focus {
                #expect(expansions.map(\.focus) == focus, "\(c.pattern)")
            }
            if let gender = c.gender {
                #expect(expansions.map { $0.gender?.rawValue ?? "" } == gender, "\(c.pattern)")
            }
            if let count = c.count {
                #expect(expansions.count == count, "\(c.pattern)")
                #expect(pattern.expansionCount == count)
            }
            if let first = c.first {
                #expect(expansions.first?.text == first, "\(c.pattern)")
            }
            if let slots = c.slots {
                #expect(pattern.slots.map(\.rawValue) == slots, "\(c.pattern)")
            }
        }
    }

    @Test func expansionLimitReportsTheCount() {
        let source = String(repeating: "{a|b}", count: 10)
        #expect(throws: PatternError.expansionLimit(limit: 512, count: 1024)) { try AnswerPattern(source) }
        // Exactly 512 is allowed.
        #expect((try? AnswerPattern(String(repeating: "{a|b}", count: 9)))?.expansionCount == 512)
        // Counting never overflows, however large the pattern.
        let huge = String(repeating: "{a|b|c|d}", count: 40)
        #expect(throws: PatternError.self) { try AnswerPattern(huge) }
    }

    @Test func optionalPresentBeforeAbsentAndNesting() throws {
        let p = try AnswerPattern("un caffè( {per favore|grazie})")
        #expect(p.expansions().map(\.text) == ["un caffè per favore", "un caffè grazie", "un caffè"])
        let q = try AnswerPattern("{vorrei|io vorrei} un cappuccino( {per favore|grazie})")
        #expect(q.expansionCount == 6)
        #expect(q.expansions().first?.text == "vorrei un cappuccino per favore")
    }

    @Test func focusSpansMapToNormalisedTokens() throws {
        let p = try AnswerPattern("{una [spremuta]|una [spremuta] d'arancia}")
        #expect(p.expansions().map(\.focus) == [[1], [1]])
        let q = try AnswerPattern("[Vorrei un] caffè, per favore.")
        #expect(q.expansions().first?.focus == [0, 1])
        let gap = try AnswerPattern.clozeGap("un'")
        #expect(gap.expansions().map(\.text) == ["un'"])
        #expect(gap.expansions().first?.focus == [0])
        let multi = try AnswerPattern.clozeGap("{vorrei|prendo} un")
        #expect(multi.expansions().map(\.focus) == [[0, 1], [0, 1]])
        #expect(AnswerPattern.clozeGapContent(in: "Vorrei [[un]] cappuccino, per favore.") == "un")
        #expect(AnswerPattern.clozeGapContent(in: "Giulia è [[un']]amica di Sara.") == "un'")
        #expect(AnswerPattern.clozeGapContent(in: "no gap") == nil)
    }

    @Test func escapes() throws {
        #expect(try AnswerPattern("a \\[b\\] \\(c\\) \\| d").expansions().map(\.text) == ["a b c | d"])
        #expect(try AnswerPattern("\\{x\\}").expansions().map(\.raw) == ["{x}"])
    }

    @Test func parseErrors() throws {
        #expect(throws: PatternError.self) { try AnswerPattern("{a|b") }
        #expect(throws: PatternError.self) { try AnswerPattern("(a") }
        #expect(throws: PatternError.self) { try AnswerPattern("[a") }
        #expect(throws: PatternError.self) { try AnswerPattern("a}") }
        #expect(throws: PatternError.self) { try AnswerPattern("a|b") }
        #expect(throws: PatternError.self) { try AnswerPattern("a\\") }
        #expect(throws: PatternError.unknownSlot("NOME")) { try AnswerPattern("mi chiamo {NOME}") }
        #expect(throws: PatternError.unknownSlot("ME.city")) { try AnswerPattern("{ME.city}") }
        #expect(throws: PatternError.unknownSlot("Name")) { try AnswerPattern("mi chiamo {Name}") }
        #expect(throws: PatternError.unknownSlot("me.home")) { try AnswerPattern("abito {me.home}") }
        #expect(throws: PatternError.unknownSlot("Me.Country")) { try AnswerPattern("vengo da {Me.Country}") }
        #expect(throws: PatternError.unknownSlot("NAME2")) { try AnswerPattern("{NAME2}") }
        #expect(throws: PatternError.unknownSlot("ME_HOME")) { try AnswerPattern("{ME_HOME}") }
        #expect(PatternError.unknownSlot("Name").description == "unknown slot {Name}")
        // Not slot-like: literals.
        #expect(try AnswerPattern("{Ciao}").expansions().map(\.text) == ["ciao"])
        #expect(try AnswerPattern("{è}").expansions().map(\.text) == ["è"])
        #expect(try AnswerPattern("{Nome|NOME}").expansions().map(\.text) == ["nome", "nome"])
        #expect(throws: PatternError.self) { try AnswerPattern("{m:nato|nata}") }
    }

    @Test func genderedExpansionsStayConsistent() throws {
        let p = try AnswerPattern("sono {m:americano|f:americana} e sono {m:nato|f:nata} a Toronto")
        let e = p.expansions()
        #expect(e.map(\.text) == ["sono americano e sono nato a toronto", "sono americana e sono nata a toronto"])
        #expect(e.map(\.gender) == [.m, .f])
        #expect(p.expansionCount == 2)
    }

    @Test func slotsAreTokensWithPositions() throws {
        let p = try AnswerPattern("ho {NUMBER} anni e abito {ME.home}")
        let e = try #require(p.expansions().first)
        #expect(e.text == "ho {NUMBER} anni e abito {ME.home}")
        #expect(e.slots == [.init(tokenIndex: 1, slot: .number), .init(tokenIndex: 5, slot: .home)])
        #expect(p.slots == [.number, .home])
    }

    static let us = LearnerProfile.Country(
        id: "us", nameIt: "Stati Uniti", homePhrase: "negli Stati Uniti", altHomePhrases: ["in America"],
        nationalityM: "americano", nationalityF: "americana")
    static let canada = LearnerProfile.Country(
        id: "ca", nameIt: "Canada", homePhrase: "in Canada", nationalityM: "canadese", nationalityF: "canadese")
    static let examples = LearnerProfile.Examples(nameM: "Marco", nameF: "Sara", country: canada)

    @Test func personalSlotsAreFilledFromTheCountry() throws {
        let profile = LearnerProfile(forms: .f, country: Self.us)
        let home = try AnswerPattern("abito {ME.home}").expansions(profile: profile)
        #expect(home.map(\.text) == ["abito negli stati uniti", "abito in america"])
        let nationality = try AnswerPattern("sono {ME.nationality}").expansions(profile: profile)
        #expect(nationality.map(\.text) == ["sono americano", "sono americana"])
        #expect(nationality.map(\.gender) == [.m, .f])
        let country = try AnswerPattern("vengo dagli {ME.country}").expansions(profile: profile)
        #expect(country.map(\.text) == ["vengo dagli stati uniti"])
        // "Another country": the slots stay wildcards.
        let other = try AnswerPattern("abito {ME.home}").expansions(profile: LearnerProfile(country: nil))
        #expect(other.map(\.text) == ["abito {ME.home}"])
    }

    @Test func modelAnswerUsesTheLearnersForms() throws {
        let p = try AnswerPattern("Sono {m:nato|f:nata} a Toronto.")
        #expect(p.modelAnswer(profile: LearnerProfile(forms: .m)).text == "Sono nato a Toronto.")
        #expect(p.modelAnswer(profile: LearnerProfile(forms: .f)).text == "Sono nata a Toronto.")
        // Both forms: the model answer itself is masculine (docs/03); feedback joins them (docs/05).
        #expect(p.modelAnswer(profile: LearnerProfile(forms: .both), style: .canonical).text == "Sono nato a Toronto.")
        #expect(
            p.modelAnswer(profile: LearnerProfile(forms: .both), style: .display).text == "Sono nato/nata a Toronto.")
        #expect(!p.modelAnswer().isExample)
    }

    @Test func modelAnswerFillsPersonalSlots() throws {
        let p = try AnswerPattern("Mi chiamo {NAME}, sono {ME.nationality} e abito {ME.home}.")
        let mine = p.modelAnswer(
            profile: LearnerProfile(forms: .f, name: "Anna", country: Self.us), examples: Self.examples)
        #expect(
            mine == ModelAnswer(text: "Mi chiamo Anna, sono americana e abito negli Stati Uniti.", isExample: false))
        let both = p.modelAnswer(profile: LearnerProfile(forms: .both, name: "Sam", country: Self.us))
        #expect(both.text == "Mi chiamo Sam, sono americano/americana e abito negli Stati Uniti.")
        let canonical = p.modelAnswer(
            profile: LearnerProfile(forms: .both, name: "Sam", country: Self.us), style: .canonical)
        #expect(canonical.text == "Mi chiamo Sam, sono americano e abito negli Stati Uniti.")
        // No name and "Another country": the story's examples, labelled "for example".
        let masculine = p.modelAnswer(profile: LearnerProfile(forms: .m), examples: Self.examples)
        #expect(masculine == ModelAnswer(text: "Mi chiamo Marco, sono canadese e abito in Canada.", isExample: true))
        let feminine = p.modelAnswer(profile: LearnerProfile(forms: .f, name: "  "), examples: Self.examples)
        #expect(feminine.text == "Mi chiamo Sara, sono canadese e abito in Canada.")
        #expect(feminine.isExample)
        // Without examples the placeholders stay.
        #expect(p.modelAnswer().text == "Mi chiamo {NAME}, sono {ME.nationality} e abito {ME.home}.")
        #expect(try AnswerPattern("Ho {NUMBER} anni.").modelAnswer().text == "Ho … anni.")
    }

    @Test func modelAnswerTakesFirstAlternativesAndOptionalParts() throws {
        let p = try AnswerPattern("(Buongiorno, )vorrei {un [cappuccino]|una spremuta}( per favore).")
        #expect(p.modelAnswer().text == "Buongiorno, vorrei un cappuccino per favore.")
    }
}

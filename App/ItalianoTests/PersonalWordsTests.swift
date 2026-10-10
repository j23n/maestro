import LearningCore
import Testing

@testable import Italiano

/// What a feedback screenshot hides of the learner's own (ADR-23).
struct PersonalWordsTests {
    private let canada = LearnerProfile.Country(
        id: "ca", nameIt: "Canada", homePhrase: "in Canada", nationalityM: "canadese", nationalityF: "canadese")

    @Test func theNameAsAWholeWord() {
        let words = PersonalWords(LearnerProfile(name: "Al"))
        #expect(words.occur(in: "Mi chiamo Al."))
        #expect(words.occur(in: "al, piacere"))
        #expect(!words.occur(in: "Alla stazione"))
        #expect(!words.occur(in: "Mi chiamo Marco."))
    }

    @Test func theCountryInEveryForm() {
        let words = PersonalWords(LearnerProfile(country: canada))
        #expect(words.occur(in: "Sono canadese."))
        #expect(words.occur(in: "Abito in Canada."))
        #expect(!words.occur(in: "Sono italiano."))
    }

    @Test func accentsAndCaseAreIgnored() {
        let words = PersonalWords(LearnerProfile(name: "José"))
        #expect(words.occur(in: "Mi chiamo JOSE."))
    }

    @Test func nothingWithoutAProfile() {
        #expect(PersonalWords(LearnerProfile()).words.isEmpty)
        #expect(PersonalWords(LearnerProfile(name: "  ")).words.isEmpty)
        #expect(!PersonalWords.empty.occur(in: "Mi chiamo Marco."))
    }

    @Test func eachWordOnce() {
        #expect(PersonalWords(LearnerProfile(country: canada)).words == ["Canada", "in Canada", "canadese"])
    }
}

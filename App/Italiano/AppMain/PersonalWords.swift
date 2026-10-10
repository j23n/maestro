import Foundation
import LearningCore

/// The learner's own words that a model answer, a hint or a transcript can show: their name and their country's
/// Italian name, home phrase and nationality, which the graders put into model answers (docs/03 § Personal slots).
/// A feedback screenshot hides a text that holds one (ADR-23); the course's own text stays visible.
struct PersonalWords: Sendable, Equatable {
    let words: [String]

    init(words: [String]) {
        var seen = Set<String>()
        self.words = words.map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty && seen.insert($0.lowercased()).inserted }
    }

    init(_ profile: LearnerProfile) {
        var words = [profile.name ?? ""]
        if let country = profile.country {
            words += [country.nameIt, country.homePhrase, country.nationalityM, country.nationalityF]
            words += country.altHomePhrases
        }
        self.init(words: words)
    }

    static let empty = PersonalWords(words: [])

    /// Whether `text` holds one of the words as a whole word, ignoring case and accents: the name *Al* is in
    /// *Sono Al.* but not in *Alla stazione*.
    func occur(in text: String) -> Bool {
        words.contains { word in
            var start = text.startIndex
            while let range = text.range(
                of: word, options: [.caseInsensitive, .diacriticInsensitive], range: start..<text.endIndex)
            {
                let before = range.lowerBound == text.startIndex ? nil : text[text.index(before: range.lowerBound)]
                let after = range.upperBound == text.endIndex ? nil : text[range.upperBound]
                if !(before?.isLetter ?? false) && !(after?.isLetter ?? false) { return true }
                start = text.index(after: range.lowerBound)
            }
            return false
        }
    }
}

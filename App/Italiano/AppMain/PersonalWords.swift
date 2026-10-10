import Foundation
import LearningCore

/// The learner's own words that a model answer or a hint can show: their name and their country's Italian name, home
/// phrases and nationality, which the graders put into model answers (docs/03 § Personal slots). A feedback
/// screenshot hides a text that holds one (ADR-23). It hides course text with the same words too (*inglese* for a
/// learner in England): the safe side. What the learner typed or said is hidden whatever it holds.
struct PersonalWords: Sendable, Equatable {
    let words: [String]

    init(words: [String]) {
        var seen = Set<String>()
        self.words = words.map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty && seen.insert($0.lowercased()).inserted }
    }

    /// The whole name and each part of it, so *Mi chiamo Mary* hides *Mary Ann*'s first name.
    init(_ profile: LearnerProfile) {
        let name = profile.name ?? ""
        var words = [name] + name.split(whereSeparator: { !$0.isLetter && $0 != "'" }).map(String.init)
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

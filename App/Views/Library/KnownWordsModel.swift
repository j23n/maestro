import Foundation
import SwiftData
import PackKit

/// Known % per text (HANDOFF.md 3.5, 5.1): from the catalog's lemma counts, the learner's active
/// Word and Verb form cards, and the texts they finished.
@MainActor struct KnownWordsModel {
    let fractions: [String: Double]

    init(model: AppModel, cards: [Card], progress: [TextProgress]) {
        let kept = Set(cards.filter { $0.isActive && !$0.lemmaID.isEmpty }.map(\.lemmaID))
        let finishedIDs = Set(progress.filter { $0.finishedAt != nil }.map(\.textID))
        let finished = finishedIDs.compactMap { model.textLemmas[$0] }
        let known = KnownWords.knownLemmas(kept: kept, finishedTexts: finished, baseline: Self.functionWords(model))
        var result: [String: Double] = [:]
        for (textID, counts) in model.textLemmas {
            result[textID] = KnownWords.fraction(lemmaCounts: counts, known: known)
        }
        fractions = result
    }

    /// Until frequency lists land (HANDOFF.md 9), articles, prepositions, pronouns and
    /// conjunctions count as known, so a beginner's Known % isn't dominated by "il" and "di".
    static func functionWords(_ model: AppModel) -> Set<String> {
        var set = Set<String>()
        for counts in model.textLemmas.values {
            for lemma in counts.keys {
                let pos = lemma.split(separator: ":").dropFirst(2).first.map(String.init) ?? ""
                if ["art", "prep", "pron", "conj", "det"].contains(pos) { set.insert(lemma) }
            }
        }
        return set
    }

    func percent(_ textID: String) -> Int? {
        fractions[textID].map { Int(($0 * 100).rounded()) }
    }

    func isGoodFit(_ textID: String) -> Bool {
        fractions[textID].map { KnownWords.goodFit.contains($0) } ?? false
    }
}

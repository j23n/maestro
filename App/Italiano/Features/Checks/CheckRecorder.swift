import Foundation
import LearningCore

// The unit check (docs/05 § Checks, docs/06 § 18): one attempt per exercise, no feedback, scored at the end by the
// engine. Platform-neutral and tested.

/// Collects each exercise's check answer from the attempts the event sink records (its `onRecord`): the first
/// attempt's outcome, or the latest points or goals a task exercise reports.
@MainActor
final class CheckRecorder {
    private(set) var answers: [ExerciseID: CheckAnswer] = [:]

    func record(_ draft: AttemptDraft) {
        if let answer = draft.checkAnswer {
            answers[draft.exerciseID] = answer
        } else if answers[draft.exerciseID] == nil {
            answers[draft.exerciseID] = .outcome(draft.outcome)
        }
    }
}

/// The check result screen's words (docs/06 § 18): pass or not yet, the overall score, each section, the words to
/// practise (focus items for the next days) and Retake.
struct CheckResultContent: Sendable, Equatable {
    struct Section: Sendable, Equatable {
        let title: String
        /// "4.5 of 6", or "Skipped" for an excluded section
        let score: String
        let fraction: Double
    }

    let passed: Bool
    let headline: String
    let overall: String
    let sections: [Section]
    /// Italian display forms of the items answered wrong: they come back first in reviews (focus).
    let practise: [String]

    init(result: CheckResult, titles: [String: String], words: [ItemID: WordInfo]) {
        passed = result.passed
        headline = result.passed ? "You passed the unit check." : "Not yet: a little more practice first."
        overall = "\(Int((result.overall * 100).rounded()))%"
        sections = result.sections.map { s in
            Section(
                title: titles[s.id] ?? s.id.capitalized,
                score: s.excluded ? "Skipped" : "\(Self.number(s.earned)) of \(Self.number(s.possible))",
                fraction: s.possible > 0 ? s.earned / s.possible : 0)
        }
        var seen: Set<ItemID> = []
        practise = result.wrongTargets.compactMap { pair in
            guard seen.insert(pair.itemId).inserted else { return nil }
            return words[pair.itemId]?.display
        }
    }

    /// "4.5", "6"
    static func number(_ x: Double) -> String {
        x == x.rounded() ? String(Int(x)) : String(format: "%.1f", x)
    }
}

extension ContentIndex.Check {
    /// Sections the device can't take: every exercise needs speech (conversation, talk, repeat) and speech is off
    /// or unavailable. They are excluded from the score (docs/05 § Checks).
    func speechOnlySections(content: ContentIndex) -> Set<String> {
        let spoken: Set<ExerciseFormat> = [.conversation, .talk, .repeat]
        return Set(
            sections.filter { section in
                !section.exerciseIds.isEmpty
                    && section.exerciseIds.allSatisfy {
                        content.exercise($0).map { spoken.contains($0.format) } ?? false
                    }
            }.map(\.id))
    }
}

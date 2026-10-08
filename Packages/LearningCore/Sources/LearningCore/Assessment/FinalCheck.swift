import Foundation

/// When the final A1 check can be taken (docs/05 § Final A1 check). Scoring is `CheckScoring.scoreFinal`.
public enum FinalCheck {
    /// Available once the last course unit (Unit 12) is completed, and in the final review unit (`u99`), which
    /// opens at the same moment (ADR-16).
    public static func isAvailable(state: LearnerState, content: ContentIndex) -> Bool {
        if let finalUnit = content.finalUnit, state.unitState(finalUnit.id) != .locked { return true }
        guard let last = content.courseUnits.last else { return false }
        return state.unitState(last.id) == .completed
    }

    /// The pack can run it: every section has exercises, and the pack has all of them (a skeleton or partial pack
    /// can't).
    public static func isRunnable(_ final: ContentIndex.FinalAssessment?, content: ContentIndex) -> Bool {
        guard let final, !final.sections.isEmpty else { return false }
        return final.sections.allSatisfy { section in
            !section.exerciseIds.isEmpty && section.exerciseIds.allSatisfy { content.exercise($0) != nil }
        }
    }

    /// Sections the device can't take: every exercise needs speech (conversation, talk, repeat) and speech is off
    /// or unavailable. They are left out of the sitting and excluded from the score (docs/05 § Unit check scoring).
    public static func speechOnlySections(_ final: ContentIndex.FinalAssessment, content: ContentIndex) -> Set<String> {
        let spoken: Set<ExerciseFormat> = [.conversation, .talk, .repeat]
        return Set(
            final.sections.filter { section in
                !section.exerciseIds.isEmpty
                    && section.exerciseIds.allSatisfy {
                        content.exercise($0).map { spoken.contains($0.format) } ?? false
                    }
            }.map(\.id))
    }

    /// What the sections taken require that the learner has never met (the eligibility rule, docs/05; CLAUDE.md
    /// hard rule 4). The app shows them in the mini-preview ("Before we go on") and introduces them `via: catchup`
    /// before the first item, as the lesson player does on entering a unit check. Sorted and unique.
    public static func missingRequirements(
        _ final: ContentIndex.FinalAssessment, excluded: Set<String> = [],
        state: LearnerState, content: ContentIndex
    ) -> [ItemSkillPair] {
        var all = Set<ItemSkillPair>()
        for section in final.sections where !excluded.contains(section.id) {
            for id in section.exerciseIds { all.formUnion(content.exercise(id)?.requires ?? []) }
        }
        return Eligibility.missing(Array(all), state: state)
    }
}

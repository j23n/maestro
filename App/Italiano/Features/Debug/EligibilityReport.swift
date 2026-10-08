import Foundation
import LearningCore

/// The Debug menu's "Show eligibility for the current screen" (docs/02): what the current step or exercise requires
/// (`text_requires`, `exercise_requires`; docs/05 § Introductions and eligibility) and whether each pair has an
/// introduction, with the `via` that introduced it.
struct EligibilityReport: Equatable, Sendable {
    struct Requirement: Equatable, Sendable {
        let pair: ItemSkillPair
        /// Nil when the pair has no introduction (the content would be ineligible).
        let via: IntroductionVia?

        var isIntroduced: Bool { via != nil }

        /// "w:caffe · read · story" or "w:caffe · read · MISSING".
        var line: String {
            "\(pair.itemId.rawValue) · \(pair.skill.rawValue) · \(via.map(\.rawValue) ?? "MISSING")"
        }
    }

    /// "Step u02.l1.step-story" or "Exercise u02.l1.ex04".
    let title: String
    let requirements: [Requirement]

    var missing: [ItemSkillPair] { requirements.filter { !$0.isIntroduced }.map(\.pair) }
    var isEligible: Bool { missing.isEmpty }

    /// "12 required · all introduced" or "12 required · 2 missing".
    var summary: String {
        let count = requirements.count
        let required = count == 1 ? "1 required" : "\(count) required"
        return missing.isEmpty ? "\(required) · all introduced" : "\(required) · \(missing.count) missing"
    }

    /// A step: everything its texts and exercises require, minus what it introduces itself (`Eligibility`).
    static func step(_ id: StepID, content: ContentIndex, state: LearnerState) -> EligibilityReport? {
        guard let step = content.step(id) else { return nil }
        return EligibilityReport(
            title: "Step \(id.rawValue)",
            requirements: requirements(Eligibility.requirements(of: step, content: content), state: state))
    }

    /// A bank exercise; nil for generated review cards (`gen:…`), which only ever use their own eligible target.
    static func exercise(_ id: ExerciseID, content: ContentIndex, state: LearnerState) -> EligibilityReport? {
        guard let exercise = content.exercise(id) else { return nil }
        return EligibilityReport(
            title: "Exercise \(id.rawValue)", requirements: requirements(exercise.requires, state: state))
    }

    private static func requirements(_ pairs: [ItemSkillPair], state: LearnerState) -> [Requirement] {
        Set(pairs).sorted().map { Requirement(pair: $0, via: state.introductions[$0]?.via) }
    }
}

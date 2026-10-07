import Foundation

/// What entering a step requires the player to do first (docs/05 § Introductions and eligibility, docs/06 § Shared
/// lesson-player behaviour).
public struct StepEntry: Hashable, Sendable {
    public let stepId: StepID
    /// The `via` of the step's own introductions (nil for kinds that never introduce).
    public let via: IntroductionVia?
    /// Pairs the step introduces at step start that the learner hasn't met: one `introduced` event.
    public let introductions: [ItemSkillPair]
    /// Pairs the step's texts and exercises need that are still missing after its own introductions. Not empty
    /// means the mini-preview ("Before we go on"), which writes `introduced` with `via: catchup`.
    public let missing: [ItemSkillPair]

    public init(stepId: StepID, via: IntroductionVia?, introductions: [ItemSkillPair], missing: [ItemSkillPair]) {
        self.stepId = stepId
        self.via = via
        self.introductions = introductions
        self.missing = missing
    }

    public var needsMiniPreview: Bool { !missing.isEmpty }

    /// One meet card per missing item, in item order.
    public var miniPreviewItems: [ItemID] {
        var seen = Set<ItemID>()
        return missing.map(\.itemId).filter { seen.insert($0).inserted }
    }

    /// The step-start `introduced` payload, or nil.
    public var introducedPayload: IntroducedPayload? {
        guard let via, !introductions.isEmpty else { return nil }
        return IntroducedPayload(pairs: introductions, via: via, stepId: stepId)
    }

    /// The mini-preview's `introduced` payload (`via: catchup`), or nil.
    public var catchupPayload: IntroducedPayload? {
        missing.isEmpty ? nil : IntroducedPayload(pairs: missing, via: .catchup, stepId: stepId)
    }
}

/// The eligibility rule: a text, exercise or review card is eligible if every (item, skill) in its requirements has
/// an introduction (docs/05; CLAUDE.md hard rule 4).
public enum Eligibility {
    /// The requirements that have no introduction, sorted and unique.
    public static func missing(_ requires: [ItemSkillPair], state: LearnerState) -> [ItemSkillPair] {
        Set(requires).filter { !state.isIntroduced($0) }.sorted()
    }

    public static func isEligible(_ requires: [ItemSkillPair], state: LearnerState) -> Bool {
        requires.allSatisfy { state.isIntroduced($0) }
    }

    public static func isEligible(exercise: ContentIndex.Exercise, state: LearnerState) -> Bool {
        isEligible(exercise.requires, state: state)
    }

    /// A text by ID; a text missing from the pack is never eligible.
    public static func isEligible(text id: TextID, state: LearnerState, content: ContentIndex) -> Bool {
        guard let text = content.text(id) else { return false }
        return isEligible(text.requires, state: state)
    }

    /// Everything a step's texts and exercises require, minus what the step itself introduces ("the step that
    /// introduces an item doesn't require it", docs/04 § Requirements). Sorted and unique.
    public static func requirements(of step: ContentIndex.Step, content: ContentIndex) -> [ItemSkillPair] {
        var all = Set<ItemSkillPair>()
        for id in step.textIds { all.formUnion(content.text(id)?.requires ?? []) }
        for id in step.exerciseIds { all.formUnion(content.exercise(id)?.requires ?? []) }
        // Only kinds that introduce at step start can cover their own requirements.
        if Introductions.via(for: step.kind) != nil { all.subtract(step.introduces) }
        return all.sorted()
    }

    /// Entering a step: its own introductions first, then the eligibility check of everything it shows.
    public static func enter(_ step: ContentIndex.Step, state: LearnerState, content: ContentIndex) -> StepEntry {
        let introductions = Introductions.pending(step: step, state: state)
        let introduced = Set(introductions)
        let missing = requirements(of: step, content: content).filter {
            !state.isIntroduced($0) && !introduced.contains($0)
        }
        return StepEntry(stepId: step.id, via: Introductions.via(for: step.kind), introductions: introductions,
                         missing: missing)
    }
}

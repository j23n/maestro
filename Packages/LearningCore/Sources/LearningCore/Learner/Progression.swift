import Foundation

/// Where "Continue" leads: the first incomplete step in the earliest available unit, and the exercise to resume at.
public struct ContinuePoint: Hashable, Sendable {
    public var unitId: UnitID
    public var stepId: StepID
    /// The derived resume cursor: the index (in presentation order) of the next unanswered exercise.
    public var cursor: Int

    public init(unitId: UnitID, stepId: StepID, cursor: Int) {
        self.unitId = unitId
        self.stepId = stepId
        self.cursor = cursor
    }
}

/// Unit progression (docs/05 § Unit progression, ADR-16).
///
/// `locked → available → in_progress → completed` (its check finished) or `skipped` (placement). The first unit is
/// available at start; Unit N+1 becomes available when Unit N is completed or skipped. Placement skips every unit
/// before its start unit (the latest `placementCompleted` counts), which makes the start unit available. A
/// completed unit stays completed. The final review unit completes with the final A1 check.
public enum Progression {
    /// Recomputes every unit's state from its facts, in course order.
    static func refreshUnitStates(_ state: inout LearnerState, content: ContentIndex) {
        let startOrd = state.placement.flatMap { content.unitOrd($0.startUnit) }
        var previousDone = true  // the first unit is available at start
        for unit in content.units {
            var progress = state.units[unit.id] ?? UnitProgress()
            progress.skipped = startOrd.map { unit.ord < $0 } ?? false
            let next: UnitState
            if progress.completedAt != nil {
                next = .completed
            } else if progress.skipped {
                next = .skipped
            } else if progress.startedAt != nil {
                next = .inProgress
            } else if previousDone {
                next = .available
            } else {
                next = .locked
            }
            progress.state = next
            state.units[unit.id] = progress
            previousDone = next == .completed || next == .skipped
        }
    }

    /// The length of the prefix of `order` whose exercises all have a final attempt.
    static func answeredPrefix(_ order: [ExerciseID], _ answered: Set<ExerciseID>) -> Int {
        var count = 0
        for id in order {
            guard answered.contains(id) else { break }
            count += 1
        }
        return count
    }

    /// Units a learner can work in (available or in progress), in course order.
    public static func openUnits(state: LearnerState, content: ContentIndex) -> [UnitID] {
        content.units.map(\.id).filter {
            let s = state.unitState($0)
            return s == .available || s == .inProgress
        }
    }

    /// The first incomplete step of a unit. Fluency replay is optional and never blocks (docs/05).
    public static func firstIncompleteStep(in unitId: UnitID, state: LearnerState, content: ContentIndex)
        -> ContentIndex.Step?
    {
        content.steps(in: unitId).first { $0.kind != .fluency && !state.isStepComplete($0.id) }
    }

    /// "Continue": the first incomplete step in the earliest available unit that has one (docs/05 § Today).
    public static func continuePoint(state: LearnerState, content: ContentIndex) -> ContinuePoint? {
        for unitId in openUnits(state: state, content: content) {
            if let step = firstIncompleteStep(in: unitId, state: state, content: content) {
                return ContinuePoint(unitId: unitId, stepId: step.id, cursor: state.cursor(step.id))
            }
        }
        return nil
    }

    /// Entering a step writes `stepStarted` only when it has no open start, so reopening a half-done step writes
    /// nothing and resumes at its cursor (docs/05 § Events).
    public static func shouldWriteStepStarted(_ stepId: StepID, state: LearnerState) -> Bool {
        !(state.stepProgress(stepId)?.isOpen ?? false)
    }

    /// The exercise to resume at in a step, or nil when every exercise has been answered since the open start.
    public static func resumeExercise(step: ContentIndex.Step, state: LearnerState) -> ExerciseID? {
        let cursor = state.cursor(step.id)
        return cursor < step.presentationOrder.count ? step.presentationOrder[cursor] : nil
    }

    /// Units 0–12 completed (the Today stat "units completed out of 13").
    public static func unitsCompleted(state: LearnerState, content: ContentIndex) -> Int {
        content.courseUnits.filter { state.unitState($0.id) == .completed }.count
    }
}

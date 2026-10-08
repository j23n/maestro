import Foundation
import LearningCore

// How stories show (docs/06 § Story, docs/08 § Settings): the `Aa` menu and Settings read and write the same
// synced settings.

extension AppModel {
    /// `display.speakerLabels` for a unit's texts: the learner's choice, else on in Units 0–4.
    func speakerLabels(unit: UnitID?) -> Bool {
        let number = unit.flatMap { id in outline.units.first { $0.id == id }?.number } ?? 0
        return settings.speakerLabels(unitOrd: number)
    }

    /// What Settings shows: the value for the unit the learner started most recently (cheap: no planner run).
    var speakerLabelsNow: Bool {
        let latest = state?.units.filter { $0.value.startedAt != nil && !$0.value.skipped }
            .max { ($0.value.startedAt ?? 0, $0.key.rawValue) < ($1.value.startedAt ?? 0, $1.key.rawValue) }?.key
        return speakerLabels(unit: latest)
    }
}

// The opener is the unit's start page (docs/06 § Opener and Use): its button goes on into the unit, so finishing
// it never ends on "Bravo".

extension AppModel {
    /// A launch that is a unit's opener and nothing else.
    static func isOpenerOnly(_ bundle: LessonBundle) -> Bool {
        !bundle.steps.isEmpty
            && bundle.steps.allSatisfy {
                if case .opener = $0.payload { return true }
                return false
            }
    }

    /// The step the learner goes on to after a unit's opener: where the unit overview's primary button points, else
    /// the unit's first lesson or unit-level step. Nil when the unit has nothing written past its opener (a dev pack
    /// whose lessons are still drafts to come); the player then says so instead of celebrating.
    func stepAfterOpener(of unit: UnitID) -> StepID? {
        guard let u = outline.unit(unit) else { return nil }
        let candidates =
            u.lessons.flatMap { $0.steps.map(\.id) }
            + u.unitSteps.filter { $0.kind != .opener && $0.kind != .fluency }.map(\.id)
        guard !candidates.isEmpty else { return nil }
        if let next = overview(unit: unit)?.primaryStep, candidates.contains(next) { return next }
        return candidates.first
    }
}

/// What the player says after an opener whose unit has nothing else written yet.
enum UnwrittenUnitCopy {
    static func title(unitNumber: Int) -> String { "Unit \(unitNumber) isn't written yet" }
    static let body =
        "Its lessons are still being written. Pick a unit with lessons from the Course tab, or come back after the "
        + "next update."
}

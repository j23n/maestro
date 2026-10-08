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

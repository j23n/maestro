import Foundation
import LearningCore
import Storage

/// Where a review-mode jump opens the player: a step's first page, or one exercise.
struct ReviewJump: Sendable, Hashable {
    let step: StepID
    var exercise: ExerciseID? = nil
}

/// Review mode's jump menu (docs/04 § Review mode in the app): every unit, lesson and step of the pack, unlocked,
/// with draft badges, and each step's exercises in presentation order, so the content lead can open any page.
struct ReviewJumpMenu: Sendable, Equatable {
    struct Step: Sendable, Hashable, Identifiable {
        let id: StepID
        /// "Practice", "Conversation · Order at the bar"
        let title: String
        let isDraft: Bool
        let exercises: [ExerciseID]
    }

    /// Consecutive steps of one lesson, or the unit-level steps between lessons.
    struct Group: Sendable, Hashable, Identifiable {
        let id: String
        /// "Lesson 1 · Al bar", or "Unit 2" for unit-level steps
        let title: String
        let steps: [Step]
    }

    struct Unit: Sendable, Hashable, Identifiable {
        let id: UnitID
        /// "Unit 2 · Al bar"
        let title: String
        let groups: [Group]
    }

    /// A search hit: a step, or one exercise in it.
    struct Hit: Sendable, Hashable, Identifiable {
        let jump: ReviewJump
        let title: String
        let isDraft: Bool
        var id: String { jump.exercise?.rawValue ?? jump.step.rawValue }
    }

    var units: [Unit]

    init(units: [Unit]) { self.units = units }

    init(outlines: [PackUnitOutline]) {
        units = outlines.sorted { $0.unit.ord < $1.unit.ord }.map(Self.unit).filter { !$0.groups.isEmpty }
    }

    private static func unit(_ o: PackUnitOutline) -> Unit {
        let number = CourseOutline.Unit.number(o.unit)
        let lessons = Dictionary(o.lessons.map { ($0.id, $0) }, uniquingKeysWith: { a, _ in a })
        var groups: [Group] = []
        var current: [PackStep] = []
        func close() {
            guard let first = current.first else { return }
            let title =
                first.lessonId.flatMap { lessons[$0] }.map { "Lesson \($0.ord) · \($0.titleIt)" } ?? "Unit \(number)"
            groups.append(Group(id: first.id.rawValue, title: title, steps: current.map(Self.step)))
            current = []
        }
        for s in o.steps.sorted(by: { $0.ord < $1.ord }) {
            if let last = current.last, last.lessonId != s.lessonId { close() }
            current.append(s)
        }
        close()
        return Unit(id: o.unit.id, title: "Unit \(number) · \(o.unit.titleIt)", groups: groups)
    }

    private static func step(_ s: PackStep) -> Step {
        let kind = TodayCopy.kindLabel(s.kind)
        return Step(
            id: s.id, title: s.titleEn.map { "\(kind) · \($0)" } ?? kind, isDraft: s.isDraft,
            exercises: s.exerciseOrder)
    }

    var steps: [Step] { units.flatMap { $0.groups.flatMap(\.steps) } }

    func isDraft(_ step: StepID) -> Bool { steps.first { $0.id == step }?.isDraft ?? false }

    /// Steps and exercises whose ID, title or lesson contains `query` (case-insensitive), in course order.
    func search(_ query: String) -> [Hit] {
        let q = query.trimmingCharacters(in: .whitespaces).lowercased()
        guard !q.isEmpty else { return [] }
        var hits: [Hit] = []
        for unit in units {
            for group in unit.groups {
                for step in group.steps {
                    let title = "\(unit.title) · \(group.title) · \(step.title)"
                    if step.id.rawValue.lowercased().contains(q) || title.lowercased().contains(q) {
                        hits.append(Hit(jump: ReviewJump(step: step.id), title: title, isDraft: step.isDraft))
                    }
                    for ex in step.exercises where ex.rawValue.lowercased().contains(q) {
                        hits.append(
                            Hit(
                                jump: ReviewJump(step: step.id, exercise: ex), title: "\(ex.rawValue) · \(step.title)",
                                isDraft: step.isDraft))
                    }
                }
            }
        }
        return hits
    }
}

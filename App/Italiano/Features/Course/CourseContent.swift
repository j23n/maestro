import Foundation
import LearningCore

// The Course (Indice, `CourseMap.png`) and Unit overview (`Unit.png`, the opener) texts and states, derived from the
// learner state. Platform-neutral and tested on Linux; CourseView and UnitView draw them.

/// What the course screens need from the learner state.
struct CourseProgress: Sendable, Equatable {
    var unitStates: [UnitID: UnitState] = [:]
    var completedSteps: Set<StepID> = []
    var continuePoint: ContinuePoint?
    var canDosReached: Set<CanDoID> = []

    init(
        unitStates: [UnitID: UnitState] = [:], completedSteps: Set<StepID> = [], continuePoint: ContinuePoint? = nil,
        canDosReached: Set<CanDoID> = []
    ) {
        self.unitStates = unitStates
        self.completedSteps = completedSteps
        self.continuePoint = continuePoint
        self.canDosReached = canDosReached
    }

    init(state: LearnerState, content: ContentIndex) {
        var units: [UnitID: UnitState] = [:]
        var reached: Set<CanDoID> = []
        for unit in content.units {
            units[unit.id] = state.unitState(unit.id)
            reached.formUnion(Progress.canDos(in: unit.id, state: state, content: content).reached)
        }
        self.init(
            unitStates: units,
            completedSteps: Set(content.steps.map(\.id).filter { state.isStepComplete($0) }),
            continuePoint: Progression.continuePoint(state: state, content: content), canDosReached: reached)
    }
}

enum RowTone: Sendable, Equatable { case done, current, next, none }

struct CourseRow: Sendable, Equatable {
    let unitID: UnitID
    let number: Int
    let titleIt: String
    let subtitle: String
    /// "Done", "Story 2 of 3", "Next", "Skipped", or nil (locked)
    let status: String?
    let tone: RowTone
    let isOpen: Bool
}

struct UnitRow: Sendable, Equatable {
    let stepID: StepID
    /// "Story 1", "Note", "Talk", "Check"
    let label: String
    let title: String
    let titleIsItalian: Bool
    /// "Read", "Done", "Next" or nil
    let status: String?
    let tone: RowTone
}

struct UnitOverview: Sendable, Equatable {
    let unitLine: String
    let titleIt: String
    let titleEn: String
    let canDos: [(id: CanDoID, en: String, reached: Bool)]
    let rows: [UnitRow]
    /// "Continue with Il conto", "Start Unit 2", "Practise this unit again"
    let primary: String
    let primaryStep: StepID?

    static func == (a: Self, b: Self) -> Bool {
        a.unitLine == b.unitLine && a.titleIt == b.titleIt && a.titleEn == b.titleEn && a.rows == b.rows
            && a.primary == b.primary && a.primaryStep == b.primaryStep
            && a.canDos.map(\.id) == b.canDos.map(\.id) && a.canDos.map(\.reached) == b.canDos.map(\.reached)
    }
}

enum CourseCopy {
    static func rows(outline: CourseOutline, progress: CourseProgress) -> [CourseRow] {
        let nextUnit = outline.units.first { progress.unitStates[$0.id] == .available }?.id
        return outline.units.map { unit in
            let state = progress.unitStates[unit.id] ?? .locked
            let (status, tone): (String?, RowTone) =
                switch state {
                case .completed: ("Done", .done)
                case .skipped: ("Skipped", .done)
                case .inProgress: (storyLine(unit, progress: progress) ?? "In progress", .current)
                case .available: (unit.id == nextUnit ? "Next" : nil, .next)
                case .locked: (nil, .none)
                }
            return CourseRow(
                unitID: unit.id, number: unit.number, titleIt: unit.titleIt,
                subtitle: unit.summaryEn ?? unit.titleEn, status: status, tone: tone,
                isOpen: state != .locked)
        }
    }

    /// "Story 2 of 3": the story the learner is on in this unit.
    static func storyLine(_ unit: CourseOutline.Unit, progress: CourseProgress) -> String? {
        let stories = unit.lessons.flatMap(\.steps).filter { $0.kind == .story }
        guard !stories.isEmpty else { return nil }
        let done = stories.filter { progress.completedSteps.contains($0.id) }.count
        return "Story \(min(done + 1, stories.count)) of \(stories.count)"
    }

    /// Moka's line under the Indice: "You're two stories into Unit 2. Il conto is next."
    static func footer(outline: CourseOutline, progress: CourseProgress) -> String? {
        guard let point = progress.continuePoint, let unit = outline.unit(point.unitId) else { return nil }
        let stories = unit.lessons.flatMap(\.steps).filter { $0.kind == .story }
        let done = stories.filter { progress.completedSteps.contains($0.id) }.count
        let next = unit.lessons.first { $0.steps.contains { $0.id == point.stepId } }?.titleIt
        let words = ["no", "one", "two", "three", "four", "five", "six"]
        let count = done < words.count ? words[done] : "\(done)"
        guard done > 0 else { return next.map { "Unit \(unit.number) starts with *\($0)*." } }
        let into = "You're \(count) \(done == 1 ? "story" : "stories") into Unit \(unit.number)."
        return next.map { "\(into) *\($0)* is next." } ?? into
    }

    static func overview(unit: CourseOutline.Unit, progress: CourseProgress) -> UnitOverview {
        let nextStep = progress.continuePoint?.unitId == unit.id ? progress.continuePoint?.stepId : nil
        func status(_ step: CourseOutline.Step, done: String) -> (String?, RowTone) {
            if progress.completedSteps.contains(step.id) { return (done, .done) }
            if step.id == nextStep { return ("Next", .next) }
            return (nil, .none)
        }
        var rows: [UnitRow] = []
        var storyNumber = 0
        for lesson in unit.lessons {
            for step in lesson.steps {
                switch step.kind {
                case .story:
                    storyNumber += 1
                    let s = lessonStatus(lesson, nextStep: nextStep, progress: progress)
                    rows.append(
                        UnitRow(
                            stepID: step.id, label: "Story \(storyNumber)", title: lesson.titleIt,
                            titleIsItalian: true, status: s.0, tone: s.1))
                case .note:
                    let s = status(step, done: "Read")
                    rows.append(
                        UnitRow(
                            stepID: step.id, label: "Note", title: step.titleEn ?? "Grammar",
                            titleIsItalian: false, status: s.0, tone: s.1))
                default:
                    continue
                }
            }
        }
        for step in unit.unitSteps where step.kind != .opener && step.kind != .fluency {
            let s = status(step, done: "Done")
            rows.append(
                UnitRow(
                    stepID: step.id,
                    label: TodayCopy.kindLabel(step.kind).components(separatedBy: " ")
                        .first ?? "", title: step.titleEn ?? step.titleIt ?? "",
                    titleIsItalian: step.titleEn == nil, status: s.0, tone: s.1))
        }
        let state = progress.unitStates[unit.id] ?? .locked
        let nextLesson = unit.lessons.first { $0.steps.contains { $0.id == nextStep } }
        let primary: String =
            switch state {
            case .completed, .skipped: "Practise this unit again"
            case .available: "Start Unit \(unit.number)"
            default: nextLesson.map { "Continue with \($0.titleIt)" } ?? "Continue"
            }
        return UnitOverview(
            unitLine: "Unit \(unit.number)", titleIt: unit.titleIt, titleEn: unit.titleEn,
            canDos: unit.canDos.map { ($0.id, $0.en, progress.canDosReached.contains($0.id)) }, rows: rows,
            primary: primary, primaryStep: nextStep ?? unit.lessons.first?.steps.first?.id)
    }

    /// A story row stands for its lesson: "Read" when the lesson's steps are all done, "Next" when the learner's
    /// next step is in it.
    private static func lessonStatus(
        _ lesson: CourseOutline.Lesson, nextStep: StepID?, progress: CourseProgress
    )
        -> (String?, RowTone)
    {
        if lesson.steps.allSatisfy({ progress.completedSteps.contains($0.id) }) { return ("Read", .done) }
        if let nextStep, lesson.steps.contains(where: { $0.id == nextStep }) { return ("Next", .next) }
        return (nil, .none)
    }
}

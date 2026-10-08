import Foundation
import LearningCore

// The Today screen's words (docs/05 § The Today planner, docs/07 § Copy, `Home.png`): the planner decides what is
// due and where to continue; this turns it into the card texts. Platform-neutral and tested on Linux.

/// Display titles the engine doesn't carry (`units`, `lessons` and `steps` titles in the pack).
struct CourseOutline: Sendable, Equatable {
    struct Step: Sendable, Equatable {
        let id: StepID
        let kind: StepKind
        /// The step's own title, for unit-level steps ("Order from Giulia").
        var titleIt: String?
        var titleEn: String?
    }

    struct Lesson: Sendable, Equatable {
        let id: LessonID
        let titleIt: String
        let titleEn: String
        let steps: [Step]
    }

    struct CanDo: Sendable, Equatable {
        let id: CanDoID
        let en: String
    }

    struct Unit: Sendable, Equatable {
        let id: UnitID
        /// 0…12; 99 for the final review unit.
        let number: Int
        let titleIt: String
        let titleEn: String
        let lessons: [Lesson]
        /// Unit-level steps (opener, task, check, fluency) in course order.
        let unitSteps: [Step]
        /// "Order at a café and pay": the Indice subtitle.
        var summaryEn: String?
        var canDos: [CanDo] = []
    }

    let units: [Unit]

    func unit(_ id: UnitID) -> Unit? { units.first { $0.id == id } }
}

struct TodayContent: Sendable, Equatable {
    struct ReviewCard: Sendable, Equatable {
        /// "about 6 min", or nil when nothing is due.
        let duration: String?
        /// English with inline Italian (`*vorrei*`), for MixedText.
        let body: String
        let catchUp: String?
        let canStart: Bool
    }

    struct ContinueCard: Sendable, Equatable {
        /// "Unit 2 · Story 2 of 3"
        let context: String
        let titleIt: String
        let titleEn: String
        /// "Read", "Start" or "Continue"
        let action: String
        let unitID: UnitID
        let stepID: StepID
    }

    let dateLine: String
    let greeting: String
    let review: ReviewCard
    let continueCard: ContinueCard?
    let week: WeekProgress
    /// "3 of 5 days"
    let weekLine: String
    let wordsKnown: Int
    /// "1 of 13"
    let unitsLine: String
    let reviewIsPrimary: Bool
}

enum TodayCopy {
    static func make(
        plan: TodayPlan, outline: CourseOutline, words: [ItemID: WordInfo], nowMs: Int64,
        tzOffsetMinutes: Int
    ) -> TodayContent {
        TodayContent(
            dateLine: dateLine(nowMs: nowMs, tzOffsetMinutes: tzOffsetMinutes),
            greeting: greeting(nowMs: nowMs, tzOffsetMinutes: tzOffsetMinutes),
            review: review(plan, words: words),
            continueCard: plan.continuePoint.flatMap { continueCard($0, outline: outline) },
            week: plan.week,
            weekLine: "\(plan.week.activeDays) of \(plan.week.goal) days",
            wordsKnown: plan.stats.wordsKnown,
            unitsLine: "\(plan.stats.unitsCompleted) of \(plan.stats.unitsTotal)",
            reviewIsPrimary: plan.reviewIsPrimary)
    }

    /// "Tuesday, October 6" (American English, docs/13 Q13), in the learner's time zone.
    static func dateLine(nowMs: Int64, tzOffsetMinutes: Int) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = TimeZone(secondsFromGMT: tzOffsetMinutes * 60)
        f.dateFormat = "EEEE, MMMM d"
        return f.string(from: Date(timeIntervalSince1970: Double(nowMs) / 1000))
    }

    /// *Buongiorno* from 04:00 (the day rollover) until 14:00, then *Buonasera*: what the learner would hear.
    static func greeting(nowMs: Int64, tzOffsetMinutes: Int) -> String {
        let local = (nowMs / 1000 + Int64(tzOffsetMinutes) * 60) % 86_400
        let hour = (local + 86_400) % 86_400 / 3600
        return (4..<14).contains(hour) ? "Buongiorno" : "Buonasera"
    }

    static func review(_ plan: TodayPlan, words: [ItemID: WordInfo]) -> TodayContent.ReviewCard {
        let r = plan.review
        let ready = r.dueCount + r.focusCount
        let examples = r.exampleItems.prefix(2).map { "*\(words[$0]?.display ?? $0.rawValue)*" }
        let catchUp =
            plan.catchUp.count > 0
            ? "\(plan.catchUp.count) catch-up \(plan.catchUp.count == 1 ? "card" : "cards") from placement" : nil
        guard ready > 0 else {
            if catchUp != nil {
                return .init(
                    duration: nil, body: "No reviews due. Your catch-up cards are ready.", catchUp: catchUp,
                    canStart: true)
            }
            return .init(
                duration: nil, body: "You're all caught up. New reviews will be ready tomorrow.",
                catchUp: nil, canStart: false)
        }
        let body: String
        switch (ready, examples.count) {
        case (1, 1...): body = "1 word is ready: \(examples[0])."
        case (_, 2...): body = "\(ready) words are ready, including \(examples[0]) and \(examples[1])."
        case (_, 1): body = "\(ready) words are ready, including \(examples[0])."
        default: body = ready == 1 ? "1 word is ready." : "\(ready) words are ready."
        }
        return .init(
            duration: "about \(max(1, r.estimatedMinutes)) min", body: body, catchUp: catchUp,
            canStart: true)
    }

    static func continueCard(_ point: ContinuePoint, outline: CourseOutline) -> TodayContent.ContinueCard? {
        guard let unit = outline.unit(point.unitId) else { return nil }
        let action = point.cursor > 0 ? "Continue" : "Start"
        for (lessonIndex, lesson) in unit.lessons.enumerated() {
            guard let step = lesson.steps.first(where: { $0.id == point.stepId }) else { continue }
            let stories = unit.lessons.flatMap(\.steps).filter { $0.kind == .story }
            let context =
                if step.kind == .story, let k = stories.firstIndex(where: { $0.id == step.id }) {
                    "Unit \(unit.number) · Story \(k + 1) of \(stories.count)"
                } else {
                    "Unit \(unit.number) · Lesson \(lessonIndex + 1)"
                }
            return .init(
                context: context, titleIt: lesson.titleIt, titleEn: lesson.titleEn,
                action: step.kind == .story && point.cursor == 0 ? "Read" : action, unitID: unit.id,
                stepID: point.stepId)
        }
        guard let step = unit.unitSteps.first(where: { $0.id == point.stepId }) else { return nil }
        return .init(
            context: "Unit \(unit.number) · \(kindLabel(step.kind))",
            titleIt: step.titleIt ?? unit.titleIt, titleEn: step.titleEn ?? unit.titleEn,
            action: step.kind == .opener ? "Start" : action, unitID: unit.id, stepID: point.stepId)
    }

    static func kindLabel(_ kind: StepKind) -> String {
        switch kind {
        case .opener: "Overview"
        case .preview: "New words"
        case .story: "Story"
        case .listening: "Listening"
        case .reading: "Reading"
        case .note: "Grammar"
        case .practice: "Practice"
        case .sounds: "Sounds"
        case .use: "Use it"
        case .conversation: "Conversation"
        case .talk: "Talk about it"
        case .writing: "Writing"
        case .relay: "Help a friend"
        case .fluency: "Fluency"
        case .check: "Unit check"
        }
    }
}

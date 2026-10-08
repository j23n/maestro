import Foundation
import LearningCore
import Testing

@testable import Italiano

@Suite struct TodayContentTests {
    let outline = CourseOutline(units: [
        .init(
            id: "u02", number: 2, titleIt: "Al bar", titleEn: "At the café",
            lessons: [
                .init(
                    id: "u02.l1", titleIt: "Al bar", titleEn: "At the bar",
                    steps: [
                        .init(id: "u02.l1.step-story", kind: .story), .init(id: "u02.l1.step-note", kind: .note),
                    ]),
                .init(
                    id: "u02.l2", titleIt: "Il conto", titleEn: "The bill",
                    steps: [
                        .init(id: "u02.l2.step-story", kind: .story)
                    ]),
            ],
            unitSteps: [
                .init(
                    id: "u02.task.conv1", kind: .conversation, titleIt: "Ordina da Giulia",
                    titleEn: "Order from Giulia")
            ])
    ])

    func plan(
        due: Int = 20, focus: Int = 0, examples: [ItemID] = ["c:vorrei", "w:conto"], catchUp: Int = 0,
        continueAt: ContinuePoint? = ContinuePoint(unitId: "u02", stepId: "u02.l2.step-story", cursor: 0)
    )
        -> TodayPlan
    {
        TodayPlan(
            review: .init(
                dueCount: due, dueTotal: due, focusCount: focus, estimatedMinutes: 6, secondsPerCard: 18,
                exampleItems: examples),
            catchUp: .init(count: catchUp, waiting: catchUp), continuePoint: continueAt,
            week: WeekProgress(weekStart: 0, days: [true, true, false, true, false, false, false], goal: 5),
            stats: .init(wordsKnown: 64, unitsCompleted: 1, unitsTotal: 13), reviewIsPrimary: due > 40)
    }

    let words: [ItemID: WordInfo] = [
        "c:vorrei": WordInfo(itemID: "c:vorrei", display: "vorrei", partOfSpeech: "chunk", gloss: "I'd like"),
        "w:conto": WordInfo(itemID: "w:conto", display: "il conto", partOfSpeech: "noun", gloss: "bill"),
    ]

    // Tuesday 6 October 2026, 09:30 in Rome (UTC+2).
    let morning: Int64 = 1_791_271_800_000

    @Test func homeReferenceCopy() {
        let t = TodayCopy.make(plan: plan(), outline: outline, words: words, nowMs: morning, tzOffsetMinutes: 120)
        #expect(t.dateLine == "Tuesday, October 6")
        #expect(t.greeting == "Buongiorno")
        #expect(t.review.duration == "about 6 min")
        #expect(t.review.body == "20 words are ready, including *vorrei* and *il conto*.")
        #expect(
            t.continueCard
                == .init(
                    context: "Unit 2 · Story 2 of 2", titleIt: "Il conto", titleEn: "The bill",
                    action: "Read", unitID: "u02", stepID: "u02.l2.step-story"))
        #expect(t.weekLine == "3 of 5 days" && t.wordsKnown == 64 && t.unitsLine == "1 of 13")
        #expect(!t.reviewIsPrimary)
    }

    @Test func greetingFollowsTheLocalClock() {
        #expect(TodayCopy.greeting(nowMs: morning + 5 * 3_600_000, tzOffsetMinutes: 120) == "Buonasera")  // 14:30
        #expect(TodayCopy.greeting(nowMs: morning - 6 * 3_600_000, tzOffsetMinutes: 120) == "Buonasera")  // 03:30
        #expect(TodayCopy.greeting(nowMs: morning - 5 * 3_600_000, tzOffsetMinutes: 120) == "Buongiorno")  // 04:30
    }

    @Test func emptyAndCatchUpStates() {
        let none = TodayCopy.review(plan(due: 0, examples: []), words: words)
        #expect(!none.canStart && none.duration == nil && none.body.hasPrefix("You're all caught up"))
        let catchUp = TodayCopy.review(plan(due: 0, examples: [], catchUp: 15), words: words)
        #expect(catchUp.canStart && catchUp.catchUp == "15 catch-up cards from placement")
        let one = TodayCopy.review(plan(due: 0, focus: 1, examples: ["w:conto"]), words: words)
        #expect(one.body == "1 word is ready: *il conto*.")
    }

    @Test func continueCardsForLessonsAndUnitSteps() {
        let started = TodayCopy.continueCard(
            ContinuePoint(unitId: "u02", stepId: "u02.l1.step-note", cursor: 2),
            outline: outline)
        #expect(started?.context == "Unit 2 · Lesson 1" && started?.action == "Continue")
        let task = TodayCopy.continueCard(
            ContinuePoint(unitId: "u02", stepId: "u02.task.conv1", cursor: 0),
            outline: outline)
        #expect(task?.context == "Unit 2 · Conversation" && task?.titleIt == "Ordina da Giulia")
        #expect(TodayCopy.continueCard(ContinuePoint(unitId: "u09", stepId: "x", cursor: 0), outline: outline) == nil)
    }
}

import Foundation
import LearningCore
import Testing

@testable import Italiano

@Suite struct CourseContentTests {
    let outline = CourseOutline(units: [
        .init(
            id: "u01", number: 1, titleIt: "Piacere!", titleEn: "Nice to meet you",
            lessons: [
                .init(
                    id: "u01.l1", titleIt: "Ciao", titleEn: "Hi", steps: [.init(id: "u01.l1.step-story", kind: .story)])
            ], unitSteps: [], summaryEn: "Say hello and who you are"),
        .init(
            id: "u02", number: 2, titleIt: "Al bar", titleEn: "At the café",
            lessons: [
                .init(
                    id: "u02.l1", titleIt: "Al bar", titleEn: "At the bar",
                    steps: [
                        .init(id: "u02.l1.step-story", kind: .story),
                        .init(id: "u02.l1.step-note", kind: .note, titleEn: "un and una"),
                    ]),
                .init(
                    id: "u02.l2", titleIt: "Il conto", titleEn: "The bill",
                    steps: [
                        .init(id: "u02.l2.step-story", kind: .story)
                    ]),
                .init(
                    id: "u02.l3", titleIt: "Un tavolo fuori", titleEn: "A table outside",
                    steps: [
                        .init(id: "u02.l3.step-story", kind: .story)
                    ]),
            ],
            unitSteps: [
                .init(id: "u02.step-opener", kind: .opener),
                .init(
                    id: "u02.task.conv1", kind: .conversation, titleIt: "Ordina da Giulia", titleEn: "Order from Giulia"
                ),
            ], summaryEn: "Order at a café and pay",
            canDos: [
                .init(id: "cd:order-food-drink", en: "Order a drink and something to eat"),
                .init(id: "cd:ask-bill-pay", en: "Ask for the bill and pay"),
            ]),
        .init(
            id: "u03", number: 3, titleIt: "La famiglia", titleEn: "The family", lessons: [], unitSteps: [],
            summaryEn: "Talk about your family"),
        .init(id: "u04", number: 4, titleIt: "Dov'è?", titleEn: "Where is it?", lessons: [], unitSteps: []),
    ])

    /// The `CourseMap.png` / `Unit.png` situation: Unit 1 done, two lessons of Unit 2 done, Il conto next.
    var progress: CourseProgress {
        CourseProgress(
            unitStates: ["u01": .completed, "u02": .inProgress, "u03": .available, "u04": .locked],
            completedSteps: ["u01.l1.step-story", "u02.step-opener", "u02.l1.step-story", "u02.l1.step-note"],
            continuePoint: ContinuePoint(unitId: "u02", stepId: "u02.l2.step-story", cursor: 0),
            canDosReached: ["cd:order-food-drink"])
    }

    @Test func indiceRowsMatchTheReference() {
        let rows = CourseCopy.rows(outline: outline, progress: progress)
        #expect(rows.map(\.status) == ["Done", "Story 2 of 3", "Next", nil])
        #expect(rows.map(\.tone) == [.done, .current, .next, .none])
        #expect(rows[1].subtitle == "Order at a café and pay" && rows[3].subtitle == "Where is it?")
        #expect(rows.map(\.isOpen) == [true, true, true, false])
    }

    @Test func mokaSaysWhereTheLearnerIs() {
        #expect(
            CourseCopy.footer(outline: outline, progress: progress)
                == "You're one story into Unit 2. *Il conto* is next.")
        var fresh = progress
        fresh.completedSteps = []
        fresh.continuePoint = ContinuePoint(unitId: "u02", stepId: "u02.l1.step-story", cursor: 0)
        #expect(CourseCopy.footer(outline: outline, progress: fresh) == "Unit 2 starts with *Al bar*.")
        fresh.continuePoint = nil
        #expect(CourseCopy.footer(outline: outline, progress: fresh) == nil)
    }

    @Test func unitOverviewMatchesTheReference() throws {
        let unit = try #require(outline.unit("u02"))
        let o = CourseCopy.overview(unit: unit, progress: progress)
        #expect(o.unitLine == "Unit 2" && o.titleIt == "Al bar" && o.titleEn == "At the café")
        #expect(o.canDos.map(\.reached) == [true, false])
        #expect(o.rows.map(\.label) == ["Story 1", "Note", "Story 2", "Story 3", "Conversation"])
        #expect(o.rows.map(\.status) == ["Read", "Read", "Next", nil, nil])
        #expect(o.rows.first { $0.label == "Note" }?.title == "un and una")
        #expect(o.rows.last?.title == "Order from Giulia")
        #expect(o.primary == "Continue with Il conto" && o.primaryStep == "u02.l2.step-story")
    }

    @Test func primaryActionFollowsTheUnitState() throws {
        let unit = try #require(outline.unit("u02"))
        var p = progress
        p.unitStates["u02"] = .completed
        #expect(CourseCopy.overview(unit: unit, progress: p).primary == "Practise this unit again")
        p.unitStates["u02"] = .available
        p.continuePoint = nil
        let start = CourseCopy.overview(unit: unit, progress: p)
        #expect(start.primary == "Start Unit 2" && start.primaryStep == "u02.l1.step-story")
    }
}

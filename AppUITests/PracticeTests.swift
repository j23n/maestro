import XCTest

/// Sessions after a text (HANDOFF.md 3.9): the reader offers one, every stage and drill can be answered or
/// revealed, and the wrap-up offers a card for what needed help.
final class PracticeTests: XCTestCase {
    private let base = ["-uiTesting", "-onboarded", "YES", "-uiTab", "read"]

    @MainActor
    func testReaderOffersPractice() {
        let app = XCUIApplication()
        app.launchArguments = base + ["-uiRoute", "text:vita-quotidiana-01"]
        app.launch()
        XCTAssertTrue(app.scrollViews["reader"].waitForExistence(timeout: 30), "The reader didn't open")
        let practise = app.buttons["reader.practice"]
        for _ in 0..<8 where !practise.isHittable { app.scrollViews["reader"].swipeUp() }
        XCTAssertTrue(practise.isHittable, "The reader doesn't offer practice")
        practise.tap()
        XCTAssertTrue(app.buttons["practice.start"].waitForExistence(timeout: 10), "The session plan didn't open")
    }

    @MainActor
    func testEveryStageEndsInTheWrapUp() {
        let app = XCUIApplication()
        app.launchArguments = base + ["-uiRoute", "practice:vita-quotidiana-01"]
        app.launch()
        let start = app.buttons["practice.start"]
        XCTAssertTrue(start.waitForExistence(timeout: 30), "The session plan didn't open")
        start.tap()

        let done = app.staticTexts["Session done"]
        let stageStart = app.buttons["session.stageStart"]
        let questionsDone = app.buttons["session.questionsDone"]
        let reveal = app.buttons["practice.showAnswer"]
        let next = app.buttons["practice.continue"]
        var drills = 0
        var stages = 0
        for _ in 0..<60 {
            if done.exists { break }
            if questionsDone.exists && questionsDone.isHittable {
                questionsDone.tap()
            } else if stageStart.exists && stageStart.isHittable {
                stageStart.tap()
                stages += 1
            } else if next.exists && next.isHittable {
                next.tap()
                drills += 1
            } else if reveal.exists && reveal.isHittable {
                reveal.tap()
                XCTAssertTrue(next.waitForExistence(timeout: 5), "Drill \(drills + 1) didn't finish")
            } else {
                _ = done.waitForExistence(timeout: 2)
            }
        }
        XCTAssertTrue(done.waitForExistence(timeout: 5), "The wrap-up didn't show")
        XCTAssertGreaterThanOrEqual(stages, 2, "A session has at least two stages of drills")
        XCTAssertGreaterThanOrEqual(drills, 3, "A session has at least three drills")

        let keep = app.buttons.matching(NSPredicate(format: "label BEGINSWITH 'Remember '")).firstMatch
        XCTAssertTrue(keep.waitForExistence(timeout: 5), "The wrap-up offers nothing to keep")
        keep.tap()
        let added = app.buttons.matching(NSPredicate(format: "label BEGINSWITH 'Added to Remember'")).firstMatch
        XCTAssertTrue(added.waitForExistence(timeout: 5), "Keeping an item didn't work")
    }
}

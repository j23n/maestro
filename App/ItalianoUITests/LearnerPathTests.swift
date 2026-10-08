import XCTest

/// The UI flows of docs/10 § Test layers on the learner's path: onboarding → Today → Unit 2 Lesson 1 complete, a
/// review session, the unit check; and M3.6's resume test (quit mid-step, relaunch, resume at the same exercise).
/// They run on the iPhone simulator and on the Mac (`make test-ui`), with the auto-answer bar of task M6.3 doing
/// the answering where the flow isn't about answering itself.
final class LearnerPathTests: XCTestCase {
    /// docs/10: onboarding → Today → Unit 2 Lesson 1 complete.
    @MainActor
    func testOnboardingThenTodayThenUnit2Lesson1Complete() throws {
        continueAfterFailure = false
        let learner = UIApp.uniqueLearner("path")
        var ui = UIApp.launch(learner: .named(learner))
        ui.completeOnboarding()
        // Today (its Continue card needs a unit with steps, which the pack may not have for Unit 0 yet).
        XCTAssertTrue(ui.exists("today.week", timeout: 15), "Today after onboarding")
        XCTAssertFalse(ui.exists("onboarding.continue"))

        // The test pack may not have Units 0–1 yet (content track C3): start at Unit 2 as placement would. The
        // relaunch keeps the onboarding answers (same learner database) and writes the jump once.
        ui.quit()
        ui = UIApp.launch(learner: .named(learner), jumpTo: "u02")
        XCTAssertTrue(ui.exists("today.continue", timeout: 15))
        ui.openUnit(2)
        ui.press("opener.step.0")  // Story 1: Lesson 1 from its first page
        XCTAssertTrue(ui.exists("player.close", timeout: 10))
        XCTAssertEqual(ui.playToEnd(), .done)

        // Back on the unit: Lesson 1 reads as done, the note too.
        XCTAssertTrue(ui.exists("opener.step.0", timeout: 10))
        XCTAssertTrue(ui.element("opener.step.0").label.contains("Read"), ui.element("opener.step.0").label)
        XCTAssertFalse(ui.exists("player.close"))
    }

    /// docs/10: a review session from Today, ten days after Lesson 1 (the Debug menu's clock offset).
    @MainActor
    func testAReviewSessionRunsFromToday() throws {
        continueAfterFailure = false
        let learner = UIApp.uniqueLearner("review")
        var ui = UIApp.launch(learner: .named(learner), jumpTo: "u02")
        ui.openUnit(2)
        ui.press("opener.step.0")
        XCTAssertEqual(ui.playToEnd(), .done)
        ui.quit()

        ui = UIApp.launch(learner: .named(learner), jumpTo: "u02", clockOffsetDays: 10)
        ui.openTab("Today")
        ui.press("today.review", timeout: 15)
        XCTAssertTrue(ui.exists("player.progress", timeout: 10))
        var cards = 0
        while !ui.exists("complete.summary"), cards < 80 {
            ui.press("debug.autoAdvance")
            cards += 1
        }
        XCTAssertTrue(ui.exists("complete.summary", timeout: 5), "Session complete after \(cards) cards")
        XCTAssertTrue(ui.exists("complete.week"))
        ui.press("complete.done")
        XCTAssertTrue(ui.exists("today.week", timeout: 10))
        XCTAssertFalse(ui.exists("today.review"), "nothing left to review today")
    }

    /// docs/10: the unit check (M4.14): sections, items without feedback, the result, Done.
    @MainActor
    func testTheUnit2CheckRunsAndScores() throws {
        continueAfterFailure = false
        let ui = UIApp.launch(learner: .fresh, jumpTo: "u02")
        ui.openUnit(2)
        // The check is the overview's last row: lessons first, then the unit-level steps in course order, with the
        // opener and fluency replay left out (docs/06 § Unit-level steps).
        let rows = ui.app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier BEGINSWITH 'opener.step.'"))
        XCTAssertTrue(rows.firstMatch.waitForExistence(timeout: 10))
        let last = rows.allElementsBoundByIndex.compactMap { Int($0.identifier.split(separator: ".").last ?? "") }.max()
        ui.press("opener.step.\(try XCTUnwrap(last))")
        // A learner who jumped here hasn't met Unit 2's words: "Before we go on" comes first (docs/05).
        if ui.exists("minipreview.continue", timeout: 5) { ui.press("minipreview.continue") }
        XCTAssertTrue(ui.exists("check.start", timeout: 10), "the first section's intro")
        XCTAssertTrue(ui.exists("assessment.section") || ui.exists("player.progress"))
        guard case .check(let overall)? = ui.playToEnd() else {
            XCTFail("the check didn't reach its result")
            return
        }
        // Every answer right: full marks (a section the device can't take, speaking without a recogniser, is left
        // out of the score rather than counted as zero).
        XCTAssertEqual(overall, "100%")
        XCTAssertTrue(ui.exists("opener.continue", timeout: 10))
    }

    /// M3.6: launch with `-ITAJumpToUnit u02`, start Unit 2 Lesson 1, quit mid-step, relaunch, resume at the same
    /// exercise.
    @MainActor
    func testQuittingMidStepResumesAtTheSameExercise() throws {
        continueAfterFailure = false
        let learner = UIApp.uniqueLearner("resume")
        var ui = UIApp.launch(learner: .named(learner), jumpTo: "u02")
        // Today's card opens what comes next (the unit's opener first, then Lesson 1); go to the practice step's
        // second exercise, after the preview's 13 and the story's 3, answering everything before it.
        let target = 18
        var counter: String?
        var pages = 0
        while pages < 120 {
            if ui.exists("today.continue") && !ui.exists("player.close") { ui.press("today.continue") }
            if ui.exists("complete.done") {
                ui.press("complete.done")
                continue
            }
            if ui.exists("minipreview.continue") { ui.press("minipreview.continue") }
            if let c = ui.exerciseCounter, Int(c.split(separator: " ").first ?? "") == target {
                counter = c
                break
            }
            ui.press("debug.autoAdvance")
            pages += 1
        }
        let midStep = try XCTUnwrap(counter, "never reached exercise \(target)")
        let prompt = ["cloze.sentence", "recall.prompt", "choice.question", "build.answer", "dictation.play"]
            .first { ui.exists($0) }
        let promptLabel = prompt.map { ui.element($0).label }
        ui.quit()

        // Relaunch with the same argument (it writes nothing the second time) and the same learner.
        ui = UIApp.launch(learner: .named(learner), jumpTo: "u02")
        ui.press("today.continue", timeout: 15)
        XCTAssertTrue(ui.exists("player.close", timeout: 10))
        let resumed = ui.app.staticTexts.matching(NSPredicate(format: "label == %@", midStep)).firstMatch
        XCTAssertTrue(
            resumed.waitForExistence(timeout: 10), "resumed at \(ui.exerciseCounter ?? "nothing"), not \(midStep)")
        if let prompt, let promptLabel {
            XCTAssertEqual(ui.element(prompt).label, promptLabel, "the same exercise is on screen")
        }
    }
}

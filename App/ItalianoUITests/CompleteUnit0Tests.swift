import XCTest

/// Task M6.3: an XCUITest completes Unit 0 on iPhone with the Debug auto-answer bar, saving a screenshot of every
/// step it opens to `artifacts/screens/M6.3/`.
final class CompleteUnit0Tests: XCTestCase {
    @MainActor
    func testCompleteUnit0OnIPhone() throws {
        try XCTSkipIf(UIApp.isMac, "M6.3 asks for iPhone; the Mac runs the other flows")
        continueAfterFailure = false
        // A first launch: the jump completes onboarding with its defaults and opens Unit 0 (docs/02).
        let ui = UIApp.launch(learner: .fresh, jumpTo: "u00")
        ui.openUnit(0)
        let primary = ui.element("opener.continue")
        // Skips only on an explicit signal (`TEST_RUNNER_ITALIANO_UNIT0_PENDING=1` on the xcodebuild command line,
        // while content track C3 hasn't written Unit 0): a disabled button for any other reason is a failure, so the
        // test never passes by skipping.
        if ProcessInfo.processInfo.environment["ITALIANO_UNIT0_PENDING"] == "1" {
            throw XCTSkip("Unit 0 has no steps in this build's pack yet (content track C3): nothing to complete")
        }
        XCTAssertTrue(primary.isEnabled, "Unit 0's primary button; set ITALIANO_UNIT0_PENDING=1 until C3 lands")

        // Each round opens what the unit's primary button offers next ("Start Unit 0", then "Continue with …"), plays
        // it to its end and comes back to the overview, until the unit is complete ("Practise this unit again").
        var steps = 0
        while !primary.label.hasPrefix("Practise"), steps < 40 {
            ui.press("opener.continue")
            XCTAssertTrue(ui.exists("player.close", timeout: 10), "step \(steps + 1) opened")
            steps += 1
            ui.screenshot(String(format: "u00-step%02d", steps), task: "M6.3", in: self)
            let end = ui.playToEnd()
            XCTAssertNotNil(end, "step \(steps) finished")
            if case .check(let overall)? = end { XCTAssertEqual(overall, "100%", "the unit check") }
            XCTAssertTrue(ui.exists("opener.continue", timeout: 10), "back on the overview after step \(steps)")
        }
        XCTAssertTrue(primary.label.hasPrefix("Practise"), "Unit 0 complete after \(steps) steps: \(primary.label)")
        ui.screenshot("u00-complete", task: "M6.3", in: self)

        // The course map shows Unit 0 done and Unit 1 open.
        ui.openTab("Course")
        if !ui.exists("course.unit.1", timeout: 3) {
            UIApp.press(ui.app.navigationBars.buttons.element(boundBy: 0))  // back from the overview
        }
        XCTAssertTrue(ui.exists("course.unit.1", timeout: 10))
        XCTAssertTrue(ui.element("course.unit.1").isEnabled, "Unit 1 opens after Unit 0")
        ui.screenshot("course-after-u00", task: "M6.3", in: self)
    }
}

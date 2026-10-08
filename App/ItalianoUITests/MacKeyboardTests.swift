import XCTest

/// docs/10's "Mac keyboard path" (M4.1, docs/06 § Shared player behaviour): a lesson played from the keyboard —
/// Return for Start, Next, Continue, Check and Try again; ⇧⌘H for a hint; ⇧⌘A to show the answer; 1–6 to pick an
/// option; Esc to close. Formats with no keyboard path of their own (match, sentence building) use the auto-answer
/// bar, which is not what this test is about.
final class MacKeyboardTests: XCTestCase {
    @MainActor
    func testALessonCanBePlayedFromTheKeyboard() throws {
        try XCTSkipUnless(UIApp.isMac, "the Mac keyboard path")
        continueAfterFailure = false
        let ui = UIApp.launch(learner: .fresh, jumpTo: "u02")
        ui.openUnit(2)
        ui.press("opener.step.0")
        XCTAssertTrue(ui.exists("player.close", timeout: 10))
        let app = ui.app

        var typed = 0
        var picked = 0
        var hinted = false
        var pages = 0
        while typed < 2 || picked < 1, pages < 120 {
            pages += 1
            if ui.exists("minipreview.continue") {
                app.typeKey(.return, modifierFlags: [])
                continue
            }
            if ui.exists("answer.field"), ui.exists("answer.check"), !ui.exists("feedback.panel") {
                // A typed exercise: the field has focus when the page opens.
                if !hinted, ui.exists("answer.hint") {
                    app.typeKey("h", modifierFlags: [.command, .shift])  // ⇧⌘H: Show a hint
                    XCTAssertTrue(ui.exists("answer.hintText", timeout: 3), "⇧⌘H shows the hint")
                    hinted = true
                }
                app.typeText("zzz")
                app.typeKey(.return, modifierFlags: [])  // Check
                XCTAssertTrue(ui.exists("feedback.tryAgain", timeout: 3), "a miss offers Try again")
                app.typeKey(.return, modifierFlags: [])  // Try again: the field again
                XCTAssertTrue(ui.exists("answer.check", timeout: 3))
                app.typeKey("a", modifierFlags: [.command, .shift])  // ⇧⌘A: Show answer
                XCTAssertTrue(ui.exists("feedback.continue", timeout: 3), "the answer is shown with Continue")
                app.typeKey(.return, modifierFlags: [])  // Continue
                typed += 1
                continue
            }
            if ["choice.option.0", "tf.true", "pairs.option.0"].contains(where: { ui.exists($0) }),
                !ui.exists("feedback.continue")
            {
                // Options: 1–6 pick by position; a wrong first pick is marked and another key picks again.
                for key in ["1", "2", "3", "4"] where !ui.exists("feedback.continue") {
                    app.typeKey(key, modifierFlags: [])
                }
                XCTAssertTrue(ui.exists("feedback.continue", timeout: 3), "picking by number ends the question")
                app.typeKey(.return, modifierFlags: [])
                picked += 1
                continue
            }
            let contentPage = ["preview.next", "story.continue", "note.tryIt", "check.start"]
                .contains { ui.exists($0) }
            if contentPage || ui.exists("feedback.continue") {
                app.typeKey(.return, modifierFlags: [])  // Start, Next, Continue to practice, Try it, Continue
            } else {
                ui.press("debug.autoAdvance")  // a format without its own keyboard path
            }
        }
        XCTAssertGreaterThanOrEqual(typed, 2, "typed exercises answered from the keyboard")
        XCTAssertGreaterThanOrEqual(picked, 1, "options picked from the keyboard")

        // Esc closes the lesson (Lesson → Close Lesson); the overview is back.
        app.typeKey(.escape, modifierFlags: [])
        XCTAssertTrue(ui.exists("opener.continue", timeout: 5))
        XCTAssertFalse(ui.exists("player.close"))
    }
}

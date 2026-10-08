import XCTest

/// `make screenshots` (macOS): the Mac's screens as `XCTAttachment`s kept in `artifacts/screens/mac.xcresult`
/// (MobileBuildMCP's UI automation is iOS-only; docs/07 § Visual verification): Today in the sidebar, the course
/// map, a unit, the story's two panes, an exercise with its feedback, Words as a table, and the Settings window.
final class MacScreens: XCTestCase {
    static let task = "mac"

    @MainActor
    func testMacScreens() throws {
        try XCTSkipUnless(UIApp.isMac, "the iOS screens are Screenshots")
        let ui = UIApp.launch(learner: .fresh, jumpTo: "u02")
        XCTAssertTrue(ui.exists("today.continue", timeout: 15))
        ui.screenshot("Home", task: Self.task, in: self)

        ui.openTab("Course")
        XCTAssertTrue(ui.exists("course.unit.2", timeout: 10))
        ui.screenshot("CourseMap", task: Self.task, in: self)
        ui.press("course.unit.2")
        XCTAssertTrue(ui.exists("opener.continue", timeout: 10))
        ui.screenshot("Unit", task: Self.task, in: self)

        // Lesson 1 up to its first cloze: the story on the way, then the exercise and a miss.
        ui.press("opener.step.0")
        var pages = 0
        var storyShot = false
        while !(ui.exists("cloze.sentence") && ui.exists("answer.check")), pages < 80 {
            if !storyShot, ui.exists("story.text") {
                ui.screenshot("Main", task: Self.task, in: self)
                storyShot = true
            }
            if ui.exists("minipreview.continue") { ui.press("minipreview.continue") }
            ui.press("debug.autoAdvance")
            pages += 1
        }
        XCTAssertTrue(storyShot, "the story was on the way")
        if ui.exists("cloze.sentence") {
            ui.screenshot("LibroPhone", task: Self.task, in: self)
            ui.press("debug.autoAnswerWrong")
            if ui.exists("feedback.tryAgain", timeout: 5) { ui.screenshot("TryAgain", task: Self.task, in: self) }
        }
        ui.app.typeKey(.escape, modifierFlags: [])  // Close Lesson
        XCTAssertTrue(ui.exists("opener.continue", timeout: 5))

        ui.openTab("Words")
        _ = ui.exists("words.filter.all", timeout: 10)
        ui.screenshot("Words", task: Self.task, in: self)

        // Settings… (⌘,) opens the Settings scene.
        ui.app.typeKey(",", modifierFlags: .command)
        XCTAssertTrue(ui.exists("settings.goal", timeout: 10))
        ui.screenshot("Settings", task: Self.task, in: self)
    }
}

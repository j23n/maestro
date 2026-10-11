import XCTest

/// `make screenshots` (iOS): the screens of `design/screens/` from the running app, named after their reference
/// (`Welcome`, `Reason`, `Home`, `CourseMap`, `Unit`, `Main`, `Grammar`, `LibroPhone`, `TryAgain`, `Dictation`,
/// `Pairs`, `Dialogue`, `Complete`, `Words`, `Settings`), saved to
/// `artifacts/screens/<task>/<name>-<device>-<mode>.png` and attached to the result bundle (docs/07 § Visual
/// verification). Run it on the iPhone and the iPad simulator, in light and dark mode
/// (`xcrun simctl ui booted appearance dark`), and compare with design/screens/.
final class Screenshots: XCTestCase {
    /// The folder under `artifacts/screens/` (`ITA_SCREENS_TASK` overrides it).
    static let task = "reference"

    @MainActor
    func testReferenceScreens() throws {
        try XCTSkipIf(UIApp.isMac, "the Mac's screens are MacScreens")
        let learner = UIApp.uniqueLearner("screens")
        var shot: Set<String> = []
        func save(_ ui: UIApp, _ name: String) {
            guard shot.insert(name).inserted else { return }
            ui.screenshot(name, task: Self.task, in: self)
        }

        // First launch: Welcome, Why Italian?, then Today.
        var ui = UIApp.launch(learner: .named(learner))
        XCTAssertTrue(ui.exists("onboarding.start", timeout: 15))
        save(ui, "Welcome")
        ui.press("onboarding.start")
        ui.press("onboarding.reason.travel")
        save(ui, "Reason")
        ui.quit()

        // Unit 2, where the golden lesson is (the jump completes onboarding with its defaults).
        ui = UIApp.launch(learner: .named(learner), jumpTo: "u02")
        XCTAssertTrue(ui.exists("today.continue", timeout: 15))
        save(ui, "Home")
        ui.openTab("Course")
        XCTAssertTrue(ui.exists("course.unit.2", timeout: 10))
        save(ui, "CourseMap")
        ui.press("course.unit.2")
        XCTAssertTrue(ui.exists("opener.continue", timeout: 10))
        save(ui, "Unit")

        // Lesson 1: each page kind once, as it comes.
        ui.press("opener.step.0")
        let end = ui.playToEnd { ui in
            if ui.exists("story.text") { save(ui, "Main") }
            if ui.exists("note.tryIt") { save(ui, "Grammar") }
            if ui.exists("dictation.play") && ui.exists("answer.check") { save(ui, "Dictation") }
            if ui.exists("pairs.option.0") && !ui.exists("feedback.continue") { save(ui, "Pairs") }
            if ui.exists("conv.line.0") { save(ui, "Dialogue") }
            if ui.exists("cloze.sentence") && ui.exists("answer.check") && !shot.contains("TryAgain") {
                save(ui, "LibroPhone")
                ui.press("debug.autoAnswerWrong")  // the stepped feedback after a miss (`TryAgain.png`)
                if ui.exists("feedback.tryAgain", timeout: 5) { save(ui, "TryAgain") }
            }
        }
        XCTAssertEqual(end, .done)
        ui.quit()

        // Ten days later the lesson's words are due: a review and its Session complete (`Complete.png`).
        ui = UIApp.launch(learner: .named(learner), jumpTo: "u02", clockOffsetDays: 10)
        ui.press("today.review", timeout: 15)
        var cards = 0
        while !ui.exists("complete.summary"), cards < 80 {
            ui.press("debug.autoAdvance")
            cards += 1
        }
        if ui.exists("complete.summary", timeout: 5) { save(ui, "Complete") }
        ui.press("complete.done")

        ui.openTab("Words")
        _ = ui.exists("words.filter.all", timeout: 10)
        save(ui, "Words")
        ui.openTab("Settings")
        XCTAssertTrue(ui.exists("settings.goal", timeout: 10))
        save(ui, "Settings")

        let expected: Set<String> = [
            "Welcome", "Reason", "Home", "CourseMap", "Unit", "Main", "Grammar", "LibroPhone", "TryAgain",
            "Dictation", "Pairs", "Dialogue", "Complete", "Words", "Settings",
        ]
        XCTAssertEqual(expected.subtracting(shot), [], "reference screens not reached")
    }
}

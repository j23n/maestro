import XCTest

/// The reader opens, and so does its tap-for-help: a sheet on the iPhone, an inspector on the iPad.
/// An inspector holding a NavigationStack once froze the app as soon as the reader was pushed, so each
/// test fails when the screen doesn't appear in time.
final class ReaderTests: XCTestCase {
    private let reader = ["-uiTesting", "-onboarded", "YES", "-uiTab", "read", "-uiRoute", "text:racconti-brevi-03"]

    @MainActor
    func testReaderOpens() {
        let app = XCUIApplication()
        app.launchArguments = reader
        app.launch()
        XCTAssertTrue(app.scrollViews["reader"].waitForExistence(timeout: 30), "The reader didn't open")
        XCTAssertTrue(app.buttons["Read aloud"].isHittable, "The reader's toolbar doesn't respond")
    }

    @MainActor
    func testHelpOpens() {
        let app = XCUIApplication()
        app.launchArguments = reader + ["-uiToken", "auto"]
        app.launch()
        XCTAssertTrue(app.scrollViews["help"].waitForExistence(timeout: 30), "Help didn't open")
        app.buttons["closeHelp"].tap()
        XCTAssertTrue(app.scrollViews["help"].waitForNonExistence(timeout: 10), "Help didn't close")
        XCTAssertTrue(app.buttons["Read aloud"].isHittable, "The reader didn't come back after help")
    }

    /// Help's links push onto a stack (the reader's under the inspector, the sheet's on the iPhone), and
    /// Back returns to the text with help still open.
    @MainActor
    func testHelpLinkComesBackToHelp() throws {
        let app = XCUIApplication()
        app.launchArguments = reader + ["-uiToken", "auto"]
        app.launch()
        XCTAssertTrue(app.scrollViews["help"].waitForExistence(timeout: 30), "Help didn't open")
        let link = app.buttons.matching(NSPredicate(format: "label BEGINSWITH 'In dictionary'")).firstMatch
        // The sample dictionary that make test-app builds may not have the word.
        try XCTSkipUnless(link.waitForExistence(timeout: 5), "The word has no dictionary entry in this content")
        link.tap()
        XCTAssertTrue(app.scrollViews["help"].waitForNonExistence(timeout: 10), "The dictionary entry didn't open")
        // On the iPhone the reader's own bar, behind the sheet, has a Back button too: take the lowest bar's.
        let bars = app.navigationBars.allElementsBoundByIndex.filter { $0.buttons["BackButton"].exists }
        guard let bar = bars.max(by: { $0.frame.minY < $1.frame.minY }) else {
            XCTFail("No Back button after opening the dictionary entry")
            return
        }
        bar.buttons["BackButton"].tap()
        XCTAssertTrue(app.scrollViews["help"].waitForExistence(timeout: 10), "Help didn't come back after Back")
    }
}

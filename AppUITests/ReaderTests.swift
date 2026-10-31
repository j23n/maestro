import XCTest

/// The reader opens, and so does its tap-for-help sheet. An `.inspector` in the reader once froze
/// the app as soon as the reader was pushed, so each test fails when the screen doesn't appear in time.
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
        app.buttons["Done"].tap()
        XCTAssertTrue(app.scrollViews["reader"].waitForExistence(timeout: 10), "The reader didn't come back after help")
    }
}

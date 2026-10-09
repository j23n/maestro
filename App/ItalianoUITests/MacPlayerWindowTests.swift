import XCTest

/// The lesson player takes the Mac's whole window (docs/02 § App): the window's content switches to the player
/// instead of a sheet opening over the tabs, and closing it brings back the tab and the unit it was opened from.
final class MacPlayerWindowTests: XCTestCase {
    @MainActor
    func testThePlayerTakesTheWholeWindow() throws {
        try XCTSkipUnless(UIApp.isMac, "iPhone and iPad cover the screen with fullScreenCover")
        continueAfterFailure = false
        let ui = UIApp.launch(learner: .fresh, jumpTo: "u02")
        ui.openUnit(2)
        ui.press("opener.step.0")
        XCTAssertTrue(ui.exists("player.close", timeout: 10))
        if ui.exists("minipreview.continue", timeout: 2) {  // a sheet of its own
            ui.press("minipreview.continue")
            XCTAssertTrue(ui.element("minipreview.continue").waitForNonExistence(timeout: 5))
        }

        XCTAssertEqual(ui.app.sheets.count, 0, "the player is the window's content, not a sheet")
        XCTAssertFalse(ui.exists("opener.step.0"), "the unit overview has left the window")

        ui.press("player.close")
        XCTAssertTrue(ui.exists("opener.step.0", timeout: 5), "back on the unit, in the Course tab")
        XCTAssertFalse(ui.exists("player.close"))
    }
}

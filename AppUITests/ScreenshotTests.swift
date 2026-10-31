import XCTest

/// Walks the main screens and keeps a screenshot of each, so the UI can be checked against the
/// mocks without a device. `make screenshots` runs it on an iPhone and an iPad simulator and
/// exports the screenshots to .build/Screenshots. A screen it can't reach is skipped, not failed.
final class ScreenshotTests: XCTestCase {
    private var app: XCUIApplication!
    private var device: String { UIDevice.current.userInterfaceIdiom == .pad ? "iPad" : "iPhone" }

    override func setUp() {
        continueAfterFailure = true
        app = XCUIApplication()
        // An in-memory learner store, so each run starts empty.
        app.launchArguments = ["-uiTesting"]
    }

    @MainActor
    func testMainScreens() {
        XCUIDevice.shared.orientation = UIDevice.current.userInterfaceIdiom == .pad ? .landscapeLeft : .portrait
        app.launch()

        // First launch: onboarding.
        if app.buttons["Start"].waitForExistence(timeout: 10) {
            snap("01-onboarding")
            app.buttons["Start"].tap()
        }

        snap("02-library")

        // A text in the reader, then help for a word.
        if tapText("Il treno per Bologna") || tapText("Al bar") {
            sleep(1)
            snap("03-reader")
            let word = app.links.firstMatch
            if word.waitForExistence(timeout: 3) {
                word.tap()
                sleep(1)
                snap("04-reader-help")
                // Keep the first item, so Remember has a card.
                let keep = app.buttons.matching(NSPredicate(format: "label BEGINSWITH 'Remember' OR label BEGINSWITH 'Keep'")).firstMatch
                if keep.exists { keep.tap() }
            }
            app.swipeDown()
            if app.buttons["Questions"].exists {
                app.buttons["Questions"].tap()
                sleep(1)
                snap("05-questions")
            }
        }

        // Dictionary: a search and an entry.
        if openTab("Dictionary") {
            snap("06-dictionary")
            search("andare")
            snap("07-dictionary-search")
            if tapText("andare") {
                sleep(1)
                snap("08-entry")
            }
        }

        // Verbs: the home, a verb table, a grammar topic.
        if openTab("Verbs") {
            snap("09-verbs")
            search("saremmo")
            snap("10-verbs-search")
            if tapText("andare") || tapText("essere") {
                sleep(1)
                snap("11-verb-table")
            }
            if openTab("Verbs"), tapText("Passato prossimo") {
                sleep(1)
                snap("12-grammar-topic")
            }
        }

        if openTab("Remember") {
            snap("13-remember")
        }

        if openTab("Listen") {
            snap("14-listen")
        }

        if openTab("Read") {
            let settings = app.buttons["Settings"].firstMatch
            if settings.waitForExistence(timeout: 3) {
                settings.tap()
                sleep(1)
                snap("15-settings")
            }
        }
    }

    // MARK: Helpers

    private func snap(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = "\(device)-\(name)"
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    /// Selects a tab, from the tab bar on iPhone or the sidebar or top bar on iPad.
    @discardableResult
    private func openTab(_ name: String) -> Bool {
        let candidates = [app.tabBars.buttons[name], app.buttons[name], app.cells[name], app.staticTexts[name]]
        for element in candidates where element.firstMatch.exists && element.firstMatch.isHittable {
            element.firstMatch.tap()
            // Back to the tab's root when it was showing a pushed screen.
            element.firstMatch.tap()
            sleep(1)
            return true
        }
        return false
    }

    private func tapText(_ text: String) -> Bool {
        let element = app.staticTexts[text].firstMatch
        guard element.waitForExistence(timeout: 3) else { return false }
        if !element.isHittable { app.swipeUp() }
        guard element.isHittable else { return false }
        element.tap()
        return true
    }

    private func search(_ text: String) {
        let field = app.searchFields.firstMatch
        guard field.waitForExistence(timeout: 3) else { return }
        field.tap()
        field.typeText(text)
        sleep(1)
    }
}

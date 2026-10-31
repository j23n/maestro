import XCTest

/// Opens each main screen and keeps a screenshot of it, so the UI can be checked against the mocks
/// without a device. `make screenshots` runs it on an iPhone and an iPad simulator and exports the
/// screenshots to .build/Screenshots. Each screen is a fresh launch that opens it directly through
/// launch arguments (App/Model/UITesting.swift), so one screen that doesn't render can't hide the rest.
final class ScreenshotTests: XCTestCase {
    /// The screens: a name and the launch arguments that open it.
    private let screens: [(name: String, arguments: [String])] = [
        ("01-onboarding", ["-onboarded", "NO"]),
        ("02-library", ["-uiTab", "read"]),
        ("03-reader", ["-uiTab", "read", "-uiRoute", "text:racconti-brevi-03"]),
        ("04-reader-help", ["-uiTab", "read", "-uiRoute", "text:racconti-brevi-03", "-uiToken", "auto"]),
        ("05-questions", ["-uiTab", "read", "-uiRoute", "questions:racconti-brevi-03"]),
        ("06-dictionary", ["-uiTab", "dictionary"]),
        ("07-dictionary-lookup", ["-uiTab", "dictionary", "-uiQuery", "andavamo"]),
        ("08-entry", ["-uiTab", "dictionary", "-uiRoute", "entry:it:andare:v"]),
        ("09-verbs", ["-uiTab", "verbs"]),
        ("10-verbs-lookup", ["-uiTab", "verbs", "-uiQuery", "saremmo"]),
        ("11-verb-table", ["-uiTab", "verbs", "-uiRoute", "verb:it:andare:v"]),
        ("12-grammar-topic", ["-uiTab", "verbs", "-uiRoute", "grammar:congiuntivo-presente"]),
        ("13-grammar-index", ["-uiTab", "verbs", "-uiRoute", "grammarIndex"]),
        ("14-remember", ["-uiTab", "remember", "-uiSeed"]),
        ("15-review", ["-uiTab", "remember", "-uiSeed", "-uiReview"]),
        ("16-listen", ["-uiTab", "listen"]),
        ("17-settings", ["-uiTab", "read", "-uiRoute", "settings"]),
    ]

    @MainActor
    func testScreens() {
        let pad = UIDevice.current.userInterfaceIdiom == .pad
        XCUIDevice.shared.orientation = pad ? .landscapeLeft : .portrait
        let app = XCUIApplication()
        for screen in screens {
            // -uiTesting: an empty in-memory learner store. Onboarding is done unless the screen says.
            let onboarded = screen.arguments.contains("-onboarded") ? [] : ["-onboarded", "YES"]
            app.launchArguments = ["-uiTesting"] + onboarded + screen.arguments
            app.launch()
            _ = app.wait(for: .runningForeground, timeout: 10)
            sleep(3)
            let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
            attachment.name = "\(pad ? "iPad" : "iPhone")-\(screen.name)"
            attachment.lifetime = .keepAlways
            add(attachment)
            app.terminate()
        }
    }
}

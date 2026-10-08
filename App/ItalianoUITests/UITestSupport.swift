import XCTest

#if os(iOS)
    import UIKit
#endif

/// The app under test, launched the way every UI test needs it (docs/10 § Test layers, docs/02 § App configuration):
///
/// - its own throwaway learner database (`-ITAFreshLearner`, or `-ITALearner <name>` to relaunch onto the same
///   progress), so a test never sees another test's progress or the developer's own;
/// - the learner's path (`-ITANoReviewMode`: Debug builds otherwise run review mode on a dev pack);
/// - the players' auto-answer bar (`-ITAAutoAnswer`: `debug.autoAnswer`, `debug.autoAnswerWrong`,
///   `debug.autoAdvance`, task M6.3);
/// - the Debug menu's kept switches pinned through the `UserDefaults` argument domain (clock offset, eligibility
///   badges and draft markers off), so a switch left on in the Simulator can't change a run.
///
/// These arguments work in Debug builds only (`ITA_DEBUG_MENU`), which is what `make test-ui` builds.
@MainActor
struct UIApp {
    enum Learner {
        /// A new, empty learner database for this launch.
        case fresh
        /// A throwaway database kept under this name: launch again with the same name to resume.
        case named(String)
    }

    let app: XCUIApplication

    nonisolated static var isMac: Bool {
        #if os(macOS)
            true
        #else
            false
        #endif
    }

    /// A name no other test run uses, for `.named`.
    nonisolated static func uniqueLearner(_ prefix: String) -> String {
        "\(prefix)-\(UUID().uuidString.prefix(8))"
    }

    /// Launches the app. `clockOffsetDays` runs it that many days later (the Debug menu's clock offset).
    @discardableResult
    static func launch(
        learner: Learner = .fresh, jumpTo unit: String? = nil, autoAnswer: Bool = true, clockOffsetDays: Int = 0,
        extra: [String] = []
    ) -> UIApp {
        let app = XCUIApplication()
        // Key–value pairs first: the argument domain reads `-key value`, and a bare flag before a pair would take
        // the pair's key as its value.
        var arguments = [
            "-ITADebugClockOffsetDays", "\(clockOffsetDays)", "-ITADebugShowEligibility", "NO",
            "-ITADebugShowDraftMarkers", "NO", "-AppleLanguages", "(en)", "-AppleLocale", "en_US",
        ]
        switch learner {
        case .fresh: arguments += ["-ITAFreshLearner"]
        case .named(let name): arguments += ["-ITALearner", name]
        }
        if let unit { arguments += ["-ITAJumpToUnit", unit] }
        arguments += ["-ITANoReviewMode"]
        if autoAnswer { arguments += ["-ITAAutoAnswer"] }
        app.launchArguments = arguments + extra
        app.launch()
        return UIApp(app: app)
    }

    // MARK: - Elements

    /// The element with this accessibility identifier, whatever its type.
    func element(_ identifier: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: identifier).firstMatch
    }

    func exists(_ identifier: String, timeout: TimeInterval = 0) -> Bool {
        timeout > 0 ? element(identifier).waitForExistence(timeout: timeout) : element(identifier).exists
    }

    /// Waits for the element and taps (iOS) or clicks (macOS) it; fails the test when it never appears.
    func press(_ identifier: String, timeout: TimeInterval = 10, file: StaticString = #filePath, line: UInt = #line) {
        let e = element(identifier)
        guard e.waitForExistence(timeout: timeout) else {
            XCTFail("\(identifier) never appeared", file: file, line: line)
            return
        }
        UIApp.press(e)
    }

    static func press(_ e: XCUIElement) {
        #if os(macOS)
            e.click()
        #else
            e.tap()
        #endif
    }

    /// The player's `n / total` counter, or nil when none is on screen.
    var exerciseCounter: String? {
        let counter = app.staticTexts.matching(NSPredicate(format: "label MATCHES %@", "^[0-9]+ / [0-9]+$"))
            .firstMatch
        return counter.exists ? counter.label : nil
    }

    // MARK: - Navigation

    /// Today, Course, Words or Settings: a tab bar on iPhone, a sidebar on iPad and Mac.
    func openTab(_ name: String, file: StaticString = #filePath, line: UInt = #line) {
        let candidates = [
            app.tabBars.buttons[name], app.outlines.buttons[name], app.outlines.staticTexts[name],
            app.buttons[name], app.staticTexts[name],
        ]
        for _ in 0..<10 {
            if let hit = candidates.first(where: { $0.exists && $0.isHittable }) {
                UIApp.press(hit)
                return
            }
            _ = candidates[0].waitForExistence(timeout: 1)
        }
        XCTFail("no tab named \(name)", file: file, line: line)
    }

    /// Course → the unit's overview (`Unit.png`).
    func openUnit(_ number: Int, file: StaticString = #filePath, line: UInt = #line) {
        openTab("Course", file: file, line: line)
        press("course.unit.\(number)", file: file, line: line)
        XCTAssertTrue(exists("opener.continue", timeout: 10), "unit \(number)'s overview", file: file, line: line)
    }

    /// Every onboarding screen with the same answers a learner might give: travel, a name, both forms, no country,
    /// five days a week, a beginner (docs/07 § Navigation).
    func completeOnboarding(name: String = "Anna") {
        if exists("onboarding.start", timeout: 10) { press("onboarding.start") }
        press("onboarding.reason.travel")
        press("onboarding.continue")
        press("onboarding.name")
        element("onboarding.name").typeText(name + "\n")  // Return goes on, so the keyboard never covers Continue
        press("onboarding.forms.both")
        press("onboarding.continue")
        press("onboarding.continue")  // Where do you live? is optional
        press("onboarding.goal.5")
        press("onboarding.continue")
        press("onboarding.experience.no")
        press("onboarding.continue")
    }

    // MARK: - Playing

    enum StepEnd: Equatable {
        /// A lesson, a unit-level step or a review ended (its Done was tapped).
        case done
        /// A unit check ended: its overall score ("100%"), read from the result before Done.
        case check(overall: String)
    }

    /// Plays the open player to its end with "Answer and continue" (`debug.autoAdvance`), passing the mini-preview
    /// when a step needs it, then taps Done (and the check result's Done). `onPage` runs before each page is left,
    /// for screenshots or a different answer. Nil when the player never finished within `maxPages`.
    @discardableResult
    func playToEnd(maxPages: Int = 300, onPage: ((UIApp) -> Void)? = nil) -> StepEnd? {
        for _ in 0..<maxPages {
            if exists("complete.done") {
                press("complete.done")
                guard exists("check.done", timeout: 3) else { return .done }
                let overall = element("check.overall").label
                press("check.done")
                return .check(overall: overall)
            }
            if exists("minipreview.continue") {
                press("minipreview.continue")
                continue
            }
            onPage?(self)
            guard exists("debug.autoAdvance", timeout: 10) else { break }
            if exists("complete.done") { continue }  // onPage may have finished the player
            press("debug.autoAdvance")
        }
        return nil
    }

    /// Simulates quitting: to the background first (the app stores its checkpoint there, as on a device), then the
    /// process ends.
    func quit() {
        #if os(iOS)
            XCUIDevice.shared.press(.home)
        #endif
        _ = app.wait(for: .runningBackground, timeout: 3)
        Thread.sleep(forTimeInterval: 1)
        app.terminate()
    }

    // MARK: - Screenshots

    /// Attaches a screenshot to the test (kept in the result bundle: `make screenshots` writes
    /// `artifacts/screens/{ios,mac}.xcresult`) and, on iOS, also writes it to
    /// `artifacts/screens/<task>/<name>-<device>-<mode>.png` (docs/07 § Visual verification). `task` comes from the
    /// test or from `ITA_SCREENS_TASK` (`TEST_RUNNER_ITA_SCREENS_TASK=M6.4 make screenshots`).
    func screenshot(_ name: String, task: String, in testCase: XCTestCase) {
        #if os(macOS)
            let shot =
                app.windows.firstMatch.exists ? app.windows.firstMatch.screenshot() : XCUIScreen.main.screenshot()
        #else
            let shot = XCUIScreen.main.screenshot()
        #endif
        let attachment = XCTAttachment(screenshot: shot)
        attachment.name = "\(name)-\(UIApp.device)-\(UIApp.appearance)"
        attachment.lifetime = .keepAlways
        testCase.add(attachment)
        #if os(iOS)
            let env = ProcessInfo.processInfo.environment
            let folder = UIApp.screensFolder.appendingPathComponent(env["ITA_SCREENS_TASK"] ?? task, isDirectory: true)
            do {
                try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
                try shot.pngRepresentation.write(to: folder.appendingPathComponent("\(attachment.name ?? name).png"))
            } catch {
                print("screenshot \(name) not written to \(folder.path): \(error)")  // the attachment still has it
            }
        #endif
    }

    /// `artifacts/screens` in the repository (the Simulator's test runner can write to the Mac's disk), or
    /// `ITA_SCREENS_DIR`.
    nonisolated static var screensFolder: URL {
        if let dir = ProcessInfo.processInfo.environment["ITA_SCREENS_DIR"] { return URL(fileURLWithPath: dir) }
        var root = URL(fileURLWithPath: #filePath)
        for _ in 0..<3 { root.deleteLastPathComponent() }  // App/ItalianoUITests/<file> → repository root
        return root.appendingPathComponent("artifacts/screens", isDirectory: true)
    }

    static var device: String {
        #if os(macOS)
            "mac"
        #else
            UIDevice.current.userInterfaceIdiom == .pad ? "ipad" : "iphone"
        #endif
    }

    static var appearance: String {
        #if os(macOS)
            UserDefaults.standard.string(forKey: "AppleInterfaceStyle") == "Dark" ? "dark" : "light"
        #else
            UITraitCollection.current.userInterfaceStyle == .dark ? "dark" : "light"
        #endif
    }
}

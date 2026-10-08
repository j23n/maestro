import Foundation
import LearningCore

/// Launch arguments for UI tests and screenshots (docs/02 § App configuration). Honoured only in builds with the
/// Debug menu (`ITA_DEBUG_MENU`); Release and Study builds ignore them.
///
/// - `-ITAJumpToUnit u02` jumps to Unit 2 at launch, as the Debug menu's "Jump to unit" does, and completes
///   onboarding with its defaults when it hasn't run, so a UI test lands on Today with the unit open.
/// - `-ITAAutoAnswer` shows the players' auto-answer bar for this launch (`debug.autoAnswer`, M6.3).
/// - `-ITAFreshLearner` opens a new, empty learner database for this launch instead of the learner's own, so every UI
///   test starts from first launch and never touches the real progress.
/// - `-ITALearner <name>` opens a throwaway learner database kept under that name, so a test can quit and relaunch
///   onto the same progress (the M3.6 resume test). With both, `-ITALearner` wins.
struct LaunchArguments: Equatable, Sendable {
    static let jumpToUnitFlag = "-ITAJumpToUnit"
    static let autoAnswerFlag = "-ITAAutoAnswer"
    static let freshLearnerFlag = "-ITAFreshLearner"
    static let learnerFlag = "-ITALearner"
    /// The folder of the throwaway learner databases, in the app's temporary directory.
    static let testLearnerFolder = "ItalianoUITests"

    /// Which learner database a UI test asked for.
    enum LearnerDatabase: Equatable, Sendable {
        /// A new one for every launch.
        case fresh
        /// One kept between launches under this name (letters, digits, `-` and `_` only).
        case named(String)
    }

    var jumpToUnit: UnitID?
    var autoAnswer = false
    var learner: LearnerDatabase?

    init(jumpToUnit: UnitID? = nil, autoAnswer: Bool = false, learner: LearnerDatabase? = nil) {
        self.jumpToUnit = jumpToUnit
        self.autoAnswer = autoAnswer
        self.learner = learner
    }

    /// Reads `ProcessInfo.processInfo.arguments` (the first element, the executable, is ignored like any other
    /// unknown argument). The last occurrence of a flag wins; a value that isn't a unit ID or a valid name is
    /// ignored.
    init(_ arguments: [String]) {
        var jump: UnitID?
        var fresh = false
        var named: String?
        for (n, argument) in arguments.enumerated() {
            let value = arguments.dropFirst(n + 1).first
            switch argument {
            case Self.jumpToUnitFlag: jump = value.flatMap(Self.unitID)
            case Self.freshLearnerFlag: fresh = true
            case Self.learnerFlag: named = value.flatMap(Self.learnerName)
            default: break
            }
        }
        jumpToUnit = jump
        autoAnswer = arguments.contains(Self.autoAnswerFlag)
        learner = named.map { .named($0) } ?? (fresh ? .fresh : nil)
    }

    /// `u02`, `U2` or `2` → `u02`; anything else → nil.
    static func unitID(_ raw: String) -> UnitID? {
        var digits = Substring(raw.trimmingCharacters(in: .whitespaces))
        if digits.first == "u" || digits.first == "U" { digits = digits.dropFirst() }
        guard !digits.isEmpty, digits.count <= 2, digits.allSatisfy({ $0.isASCII && $0.isNumber }),
            let n = Int(digits)
        else { return nil }
        return UnitID(rawValue: n < 10 ? "u0\(n)" : "u\(n)")
    }

    /// 1–64 ASCII letters, digits, `-` or `_` (it becomes a folder name); anything else → nil.
    static func learnerName(_ raw: String) -> String? {
        guard (1...64).contains(raw.count),
            raw.allSatisfy({ $0.isASCII && ($0.isLetter || $0.isNumber || $0 == "-" || $0 == "_") })
        else { return nil }
        return raw
    }

    /// The learner database to open instead of `Application Support/Italiano/learner.sqlite`, or nil for the
    /// learner's own. Always nil without the Debug menu, so Release and Study builds can't be pointed elsewhere.
    /// Each database gets its own folder (`<temporary>/ItalianoUITests/<name>/learner.sqlite`), so the final check's
    /// recordings and exports, which live next to it, stay with the test too.
    func learnerURL(config: AppConfig, temporaryDirectory: URL, newName: () -> String) -> URL? {
        guard config.debugMenu, let learner else { return nil }
        let name: String =
            switch learner {
            case .fresh: "fresh-\(newName())"
            case .named(let n): n
            }
        return temporaryDirectory.appendingPathComponent(Self.testLearnerFolder, isDirectory: true)
            .appendingPathComponent(name, isDirectory: true)
            .appendingPathComponent("learner.sqlite")
    }
}

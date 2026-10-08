import Foundation
import LearningCore

/// Launch arguments for UI tests and screenshots (docs/02 § App configuration). Honoured only in builds with the
/// Debug menu (`ITA_DEBUG_MENU`); Release and Study builds ignore them.
///
/// `-ITAJumpToUnit u02` jumps to Unit 2 at launch, as the Debug menu's "Jump to unit" does, and completes onboarding
/// with its defaults when it hasn't run, so a UI test lands on Today with the unit open.
struct LaunchArguments: Equatable, Sendable {
    static let jumpToUnitFlag = "-ITAJumpToUnit"

    var jumpToUnit: UnitID?

    init(jumpToUnit: UnitID? = nil) { self.jumpToUnit = jumpToUnit }

    /// Reads `ProcessInfo.processInfo.arguments` (the first element, the executable, is ignored like any other
    /// unknown argument). The last occurrence of a flag wins; a value that isn't a unit ID is ignored.
    init(_ arguments: [String]) {
        var jump: UnitID?
        for (n, argument) in arguments.enumerated() where argument == Self.jumpToUnitFlag {
            jump = arguments.dropFirst(n + 1).first.flatMap(Self.unitID)
        }
        jumpToUnit = jump
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
}

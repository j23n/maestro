import Foundation
import LearningCore
import Observation

/// The Debug menu's clock offset (docs/02 § App configuration): the device clock moved by whole days, so the
/// planner, review due dates, the week dots and new events all see the shifted "now". Builds with the Debug menu use
/// it as the app's only clock; others use `SystemClock` directly.
///
/// Observable by hand rather than with the macro: `nowMs()` runs on the learner store's writer queue as well as the
/// main actor, so the offset sits behind a lock, and reading it inside a SwiftUI body registers the dependency, so
/// Today and Your words redraw when the offset changes.
final class DebugClock: LearningCore.Clock, Observable, @unchecked Sendable {
    // @unchecked: `_offsetDays` is guarded by `lock`; `base` and the registrar are Sendable.
    static let msPerDay: Int64 = 86_400_000

    private let base: any LearningCore.Clock
    private let lock = NSLock()
    private var _offsetDays: Int
    private let registrar = ObservationRegistrar()

    init(base: any LearningCore.Clock, offsetDays: Int = 0) {
        self.base = base
        _offsetDays = offsetDays
    }

    /// Whole days added to the device clock (negative moves back).
    var offsetDays: Int {
        get {
            registrar.access(self, keyPath: \.offsetDays)
            return lock.withLock { _offsetDays }
        }
        set {
            registrar.withMutation(of: self, keyPath: \.offsetDays) { lock.withLock { _offsetDays = newValue } }
        }
    }

    func nowMs() -> Int64 { base.nowMs() + Int64(offsetDays) * Self.msPerDay }
    func tzOffsetMinutes() -> Int { base.tzOffsetMinutes() }
}

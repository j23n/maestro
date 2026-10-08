import Foundation
import LearningCore
import Observation

/// View → Bigger Text (⌘+), Smaller Text (⌘−) and Actual Size (⌘0) on the Mac (docs/07 § Navigation): steps through
/// `display.textScale` (docs/08; 0.85–1.6, device-scoped). On macOS this is the only text-size control; on iOS the
/// Settings slider sets the same value on top of Dynamic Type.
enum TextSizeCommand: Sendable, CaseIterable {
    case bigger, smaller, actualSize

    /// The sizes the commands step through. A value between two steps (the Settings slider moves in 0.05s) goes to
    /// the next step in that direction.
    static let steps: [Double] = [0.85, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6]

    /// The scale after this command from `current`.
    func apply(to current: Double) -> Double {
        let epsilon = 0.001
        switch self {
        case .bigger: return Self.steps.first { $0 > current + epsilon } ?? Self.steps[Self.steps.count - 1]
        case .smaller: return Self.steps.last { $0 < current - epsilon } ?? Self.steps[0]
        case .actualSize: return 1.0
        }
    }

    /// False when the command wouldn't change anything (the menu item is disabled).
    func canApply(to current: Double) -> Bool { abs(apply(to: current) - current) > 0.001 }
}

/// Applies the commands to the setting. Settings are written asynchronously, so pressing ⌘+ twice in quick
/// succession steps from the value the first press wrote, not from the one still stored.
@MainActor
@Observable
final class TextSizeController {
    @ObservationIgnored private let app: AppModel
    @ObservationIgnored private var written: Double?
    @ObservationIgnored private var inFlight = 0

    init(app: AppModel) { self.app = app }

    /// The size the next command starts from.
    var current: Double { inFlight > 0 ? (written ?? app.settings.textScale) : app.settings.textScale }

    func canApply(_ command: TextSizeCommand) -> Bool { command.canApply(to: current) }

    func apply(_ command: TextSizeCommand) {
        let next = command.apply(to: current)
        guard abs(next - current) > 0.001 else { return }
        written = next
        inFlight += 1
        app.set(.displayTextScale, to: .number(next))
        Task {
            await app.settle()
            inFlight -= 1
            if inFlight == 0 { written = nil }
        }
    }

    /// Waits until the commands so far are stored (tests).
    func settle() async {
        while inFlight > 0 { try? await Task.sleep(for: .milliseconds(1)) }
    }
}

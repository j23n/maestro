import SwiftUI

/// Moka, the stovetop coffee pot (ADR-13). Swapping the mascot is an asset change: the poses are image sets named
/// `moka-<pose>` in Assets.xcassets (vector data preserved). docs/07 § Components.
struct Mascot: View {
    enum Pose: String, CaseIterable, Sendable {
        case hello, think, cheer, sleep

        var spoken: String {
            switch self {
            case .hello: "waving hello"
            case .think: "thinking"
            case .cheer: "cheering"
            case .sleep: "sleeping"
            }
        }
    }

    let pose: Pose
    var size: Double = 56
    /// Decorative mascots are hidden from VoiceOver; a mascot that carries meaning gets its label.
    var decorative = true
    /// Hint mascots disappear when "Show Moka's hints and notes" is off (`mascot.hints`); the hint text stays.
    var isHint = false

    @Environment(\.showsMascotHints) private var showsHints
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        if isHint && !showsHints {
            EmptyView()
        } else {
            Image("moka-\(pose.rawValue)")
                .resizable()
                .scaledToFit()
                .frame(width: size, height: size)
                .accessibilityHidden(decorative)
                .accessibilityLabel(Text("Moka, the coffee pot, \(pose.spoken)"))
                .transaction { if reduceMotion { $0.animation = nil } }
        }
    }
}

private struct ShowsMascotHintsKey: EnvironmentKey {
    static let defaultValue = true
}

extension EnvironmentValues {
    /// The synced setting `mascot.hints` (docs/08).
    var showsMascotHints: Bool {
        get { self[ShowsMascotHintsKey.self] }
        set { self[ShowsMascotHintsKey.self] = newValue }
    }
}

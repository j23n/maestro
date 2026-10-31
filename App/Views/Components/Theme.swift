import SwiftUI
import ItalianCore

/// Colours and type from design/tokens.json. The mocks are light only; dark values are first guesses.
enum Theme {
    static let accent = Color.accentColor
    static let ink = dynamic(0x17181A, 0xF2F2F4)
    static let secondary = Color.secondary
    static let background = dynamic(0xFFFFFF, 0x000000)
    static let hairline = dynamic(0xE4E5E8, 0x3A3B3F)
    static let borderControl = dynamic(0x8E9299, 0x6A6E75)
    static let borderInput = dynamic(0xC3C6CC, 0x4A4E55)
    static let addedBorder = dynamic(0x8CC3A0, 0x2F6B45)
    static let surface = dynamic(0xF4F4F5, 0x1F2023)
    static let chip = dynamic(0xF1F2F4, 0x2A2B2F)
    static let selectionFill = dynamic(0xDCE5FF, 0x23376E)
    static let info = Pair(dynamic(0xEEF2FF, 0x1B2440), dynamic(0x1E3F99, 0xA9BEFF))
    static let added = Pair(dynamic(0xE7F3EC, 0x163222), dynamic(0x1D5A35, 0x9CD8B1))
    static let error = Pair(dynamic(0xFDECEA, 0x3A1715), dynamic(0x8E1B1B, 0xFFB4AB))
    static let warning = Pair(dynamic(0xFFF4E5, 0x3A2A10), dynamic(0x6B3A00, 0xFFCF8A))
    static let irregularForm = dynamic(0x9A4300, 0xFFA05C)
    static let irregularBadge = Pair(dynamic(0xFFF0E3, 0x3A2412), dynamic(0x8A3D00, 0xFFB57A))

    struct Pair {
        let background: Color
        let foreground: Color
        init(_ background: Color, _ foreground: Color) {
            self.background = background
            self.foreground = foreground
        }
    }

    static func kind(_ kind: ItemKind) -> Pair {
        switch kind {
        case .word: Pair(dynamic(0xF1F2F4, 0x2A2B2F), dynamic(0x2B2E33, 0xE2E3E6))
        case .verbForm: Pair(dynamic(0xDDF1EB, 0x15302A), dynamic(0x1F5F52, 0x8FD6C3))
        case .grammar: Pair(dynamic(0xE3EAFF, 0x1B2440), dynamic(0x1E3F99, 0xA9BEFF))
        }
    }

    static func level(_ level: String) -> Pair {
        switch level {
        case "A1": Pair(dynamic(0xE4F2D8, 0x1E2E12), dynamic(0x2F5A12, 0xB4DE8F))
        case "A2": Pair(dynamic(0xCDEBE3, 0x15302A), dynamic(0x1F5F52, 0x8FD6C3))
        case "B1": Pair(dynamic(0xDCE5FF, 0x1B2440), dynamic(0x1E3F99, 0xA9BEFF))
        default: Pair(dynamic(0xE2D6FF, 0x2A1E48), dynamic(0x4B2A9B, 0xCDB8FF))
        }
    }

    static func grade(_ rating: Int) -> Pair {
        switch rating {
        case 1: Pair(dynamic(0xFBE7E7, 0x3A1715), dynamic(0x8E1B1B, 0xFFB4AB))
        case 2: Pair(dynamic(0xF6EEDC, 0x33290F), dynamic(0x6B4E00, 0xF0CF7A))
        case 3: Pair(dynamic(0xE7F3EC, 0x163222), dynamic(0x1D5A35, 0x9CD8B1))
        default: Pair(dynamic(0xE3EAFF, 0x1B2440), dynamic(0x1E3F99, 0xA9BEFF))
        }
    }

    /// Reading text size in points per platform (tokens: 19 iPhone, 22 iPad, 21 Mac), times the
    /// learner's text-size setting.
    static func readingSize(regular: Bool, scale: Double) -> CGFloat {
        #if os(macOS)
        let base: CGFloat = 21
        #else
        let base: CGFloat = regular ? 22 : 19
        #endif
        return base * CGFloat(scale)
    }

    static func readingFont(size: CGFloat) -> Font { .system(size: size, design: .serif) }

    static func dynamic(_ light: UInt32, _ dark: UInt32) -> Color {
        #if os(macOS)
        Color(nsColor: NSColor(name: nil) { appearance in
            appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua ? NSColor(hex: dark) : NSColor(hex: light)
        })
        #else
        Color(uiColor: UIColor { traits in
            traits.userInterfaceStyle == .dark ? UIColor(hex: dark) : UIColor(hex: light)
        })
        #endif
    }
}

#if os(macOS)
extension NSColor {
    convenience init(hex: UInt32) {
        self.init(srgbRed: CGFloat((hex >> 16) & 0xFF) / 255, green: CGFloat((hex >> 8) & 0xFF) / 255,
                  blue: CGFloat(hex & 0xFF) / 255, alpha: 1)
    }
}
#else
extension UIColor {
    convenience init(hex: UInt32) {
        self.init(red: CGFloat((hex >> 16) & 0xFF) / 255, green: CGFloat((hex >> 8) & 0xFF) / 255,
                  blue: CGFloat(hex & 0xFF) / 255, alpha: 1)
    }
}
#endif

/// Small rounded label: level, kind, "irregular".
struct Tag: View {
    let text: String
    let colors: Theme.Pair

    var body: some View {
        Text(text)
            .font(.system(size: 11, weight: .semibold))
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .foregroundStyle(colors.foreground)
            .background(colors.background, in: RoundedRectangle(cornerRadius: 5))
    }
}

struct LevelTag: View {
    let level: String
    var body: some View { Tag(text: level, colors: Theme.level(level)) }
}

struct KindTag: View {
    let kind: ItemKind
    var body: some View { Tag(text: kind.label, colors: Theme.kind(kind)) }
}

/// Section label: 12 pt semibold uppercase.
struct SectionLabel: View {
    let text: String
    init(_ text: String) { self.text = text }
    var body: some View {
        Text(text.uppercased())
            .font(.system(size: 12, weight: .semibold))
            .tracking(0.7)
            .foregroundStyle(.secondary)
    }
}

extension View {
    /// Italian text for VoiceOver.
    func italian() -> some View { environment(\.locale, Locale(identifier: "it_IT")) }
}

extension Text {
    /// Marks the text as Italian so VoiceOver reads it with an Italian voice.
    init(italian string: String) {
        var attributed = AttributedString(string)
        attributed.languageIdentifier = "it-IT"
        self.init(attributed)
    }
}

/// The mocks' page look: plain white lists with hairline rows, not iOS's grey grouped cards.
extension View {
    func plainPage() -> some View {
        listStyle(.plain)
            .scrollContentBackground(.hidden)
            .background(Theme.background)
    }
}

/// A list section whose header is a small uppercase label, as in the mocks.
struct LabeledSection<Content: View>: View {
    let title: String
    let content: Content

    init(_ title: String, @ViewBuilder content: () -> Content) {
        self.title = title
        self.content = content()
    }

    var body: some View {
        Section {
            content
        } header: {
            SectionLabel(title)
        }
    }
}

/// The primary action: a full-width ink button (Review, Show answer, Start reading).
struct PrimaryButtonStyle: ButtonStyle {
    let fullWidth: Bool
    @Environment(\.isEnabled) private var isEnabled

    init(fullWidth: Bool = true) { self.fullWidth = fullWidth }

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.body.weight(.semibold))
            .padding(.horizontal, fullWidth ? 0 : 20)
            .frame(maxWidth: fullWidth ? .infinity : nil, minHeight: fullWidth ? 50 : 44)
            .foregroundStyle(Theme.background)
            .background(Theme.ink.opacity(isEnabled ? (configuration.isPressed ? 0.8 : 1) : 0.3),
                        in: RoundedRectangle(cornerRadius: 12))
    }
}

/// A secondary action: an outlined button.
struct SecondaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.body.weight(.semibold))
            .frame(maxWidth: .infinity, minHeight: 44)
            .foregroundStyle(Theme.ink)
            .background(RoundedRectangle(cornerRadius: 12).stroke(Theme.borderControl))
            .opacity(configuration.isPressed ? 0.7 : 1)
    }
}

/// A filter chip: outlined, or filled with ink when selected.
struct ChipLabel: View {
    let title: String
    var count: Int?
    let selected: Bool

    var body: some View {
        HStack(spacing: 5) {
            Text(title).fontWeight(.semibold)
            if let count {
                Text("\(count)").monospacedDigit().opacity(0.75)
            }
        }
        .font(.subheadline)
        .padding(.horizontal, 14)
        .frame(minHeight: 34)
        .foregroundStyle(selected ? Theme.background : Theme.ink)
        .background(Capsule().fill(selected ? Theme.ink : Color.clear))
        .overlay(Capsule().stroke(selected ? Color.clear : Theme.borderInput))
        .frame(minHeight: 44)
        .contentShape(Rectangle())
    }
}

struct EmptyState: View {
    let title: String
    let message: String
    let systemImage: String

    var body: some View {
        ContentUnavailableView(title, systemImage: systemImage, description: Text(message))
    }
}

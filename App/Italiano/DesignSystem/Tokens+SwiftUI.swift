import SwiftUI

#if os(macOS)
    import AppKit
#else
    import UIKit
#endif

// The SwiftUI face of the generated tokens (Tokens.swift ← design/tokens.json; docs/07). Feature views use only
// these: `Color.ds.accent`, `.font(.ds(.uiBody))`, `Tokens.Space.l`. Never hard-code a colour, size or radius.

extension Color {
    /// A colour that follows light and dark mode with the two token palettes.
    static func dynamic(_ light: UInt32, _ dark: UInt32) -> Color {
        #if os(macOS)
            Color(
                nsColor: NSColor(name: nil) { appearance in
                    let isDark = appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
                    return NSColor(hex: isDark ? dark : light)
                })
        #else
            Color(uiColor: UIColor { traits in UIColor(hex: traits.userInterfaceStyle == .dark ? dark : light) })
        #endif
    }

    /// `Color.ds.<token>`: the design-system palette.
    enum ds {
        static let background = token(\.background)
        static let surface = token(\.surface)
        static let subtle = token(\.subtle)
        static let divider = token(\.divider)
        static let inputBorder = token(\.inputBorder)
        static let switchOff = token(\.switchOff)
        static let ink = token(\.ink)
        static let secondary = token(\.secondary)
        static let accent = token(\.accent)
        static let accentPressed = token(\.accentPressed)
        static let accentTint = token(\.accentTint)
        static let onAccent = token(\.onAccent)
        static let success = token(\.success)
        static let warning = token(\.warning)
        static let warningBackground = token(\.warningBackground)
        static let warningText = token(\.warningText)
        static let warningInputBackground = token(\.warningInputBackground)

        static func token(_ key: KeyPath<Palette, UInt32>) -> Color {
            .dynamic(Tokens.light[keyPath: key], Tokens.dark[keyPath: key])
        }
    }
}

#if os(macOS)
    extension NSColor {
        convenience init(hex: UInt32) {
            self.init(
                srgbRed: CGFloat((hex >> 16) & 0xFF) / 255, green: CGFloat((hex >> 8) & 0xFF) / 255,
                blue: CGFloat(hex & 0xFF) / 255, alpha: 1)
        }
    }
#else
    extension UIColor {
        convenience init(hex: UInt32) {
            self.init(
                red: CGFloat((hex >> 16) & 0xFF) / 255, green: CGFloat((hex >> 8) & 0xFF) / 255,
                blue: CGFloat(hex & 0xFF) / 255, alpha: 1)
        }
    }
#endif

// MARK: - Text scale (display.textScale, docs/07 § Text size)

private struct TextScaleKey: EnvironmentKey {
    static let defaultValue: Double = 1.0
}

extension EnvironmentValues {
    /// The learner's text size multiplier (0.85–1.6). On iOS it applies on top of Dynamic Type; on macOS it is the
    /// only text-size control (View → Bigger/Smaller Text).
    var textScale: Double {
        get { self[TextScaleKey.self] }
        set { self[TextScaleKey.self] = min(max(newValue, 0.85), 1.6) }
    }
}

extension TypeStyle.TextStyle {
    var swiftUI: Font.TextStyle {
        switch self {
        case .largeTitle: .largeTitle
        case .title: .title
        case .title2: .title2
        case .title3: .title3
        case .headline: .headline
        case .body: .body
        case .callout: .callout
        case .footnote: .footnote
        case .caption: .caption
        }
    }
}

extension TypeStyle {
    var familyName: String { family == .italian ? Tokens.FontFamily.italian : Tokens.FontFamily.ui }

    var swiftUIWeight: Font.Weight {
        switch weight {
        case ..<450: .regular
        case ..<550: .medium
        case ..<650: .semibold
        default: .bold
        }
    }

    /// Extra line spacing for SwiftUI's `lineSpacing` from the token's line height (a multiple of the size).
    func lineSpacing(scale: Double) -> CGFloat {
        guard let lh = lineHeight else { return 0 }
        return max(0, CGFloat((lh - 1.2) * size * scale))
    }
}

extension Font {
    /// A design-system font: the token's family and size × text scale, scaling with Dynamic Type on iOS.
    static func ds(_ style: TypeStyle, scale: Double = 1.0) -> Font {
        var font = Font.custom(style.familyName, size: CGFloat(style.size * scale), relativeTo: style.relativeTo.swiftUI)
            .weight(style.swiftUIWeight)
        if style.italic { font = font.italic() }
        return font
    }
}

/// `.dsFont(Tokens.TypeScale.uiBody)` applies the font, the line spacing and the learner's text scale.
struct DSFontModifier: ViewModifier {
    let style: TypeStyle
    @Environment(\.textScale) private var textScale

    func body(content: Content) -> some View {
        content
            .font(.ds(style, scale: textScale))
            .lineSpacing(style.lineSpacing(scale: textScale))
    }
}

extension View {
    func dsFont(_ style: TypeStyle) -> some View { modifier(DSFontModifier(style: style)) }

    /// Content column for regular width: max 720 pt, centred; 24 pt side padding on compact width (docs/07).
    func readableColumn(maxWidth: Double = Tokens.Size.readableWidth) -> some View {
        modifier(ReadableColumn(maxWidth: maxWidth))
    }
}

struct ReadableColumn: ViewModifier {
    let maxWidth: Double
    @Environment(\.isCompactWidth) private var isCompact

    func body(content: Content) -> some View {
        content
            .frame(maxWidth: maxWidth)
            .padding(.horizontal, isCompact ? Tokens.Space.screenPaddingCompact : Tokens.Space.screenPaddingRegular)
            .frame(maxWidth: .infinity)
    }
}

// MARK: - Compact width, on every platform

private struct IsCompactWidthKey: EnvironmentKey {
    static let defaultValue = false
}

extension EnvironmentValues {
    /// True on iPhone and iPad Slide Over (compact horizontal size class); always false on macOS, which has no size
    /// classes. Set once at the root by `CompactWidthReader` so views never branch on the platform.
    var isCompactWidth: Bool {
        get { self[IsCompactWidthKey.self] }
        set { self[IsCompactWidthKey.self] = newValue }
    }
}

struct CompactWidthReader: ViewModifier {
    #if os(iOS)
        @Environment(\.horizontalSizeClass) private var sizeClass
        func body(content: Content) -> some View {
            content.environment(\.isCompactWidth, sizeClass == .compact)
        }
    #else
        func body(content: Content) -> some View { content.environment(\.isCompactWidth, false) }
    #endif
}

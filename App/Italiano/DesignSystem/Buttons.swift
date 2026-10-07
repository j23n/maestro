import SwiftUI

// docs/07 § Components: PrimaryButton, SecondaryButton, TextLinkButton. Use them through the button styles
// (`.buttonStyle(.dsPrimary)`) so keyboard shortcuts, accessibility and disabled states come from SwiftUI.

struct PrimaryButtonStyle: ButtonStyle {
    var height: Double = Tokens.Size.primaryButtonHeight
    @Environment(\.isEnabled) private var isEnabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .dsFont(Tokens.TypeScale.uiButton)
            .foregroundStyle(Color.ds.onAccent)
            .frame(maxWidth: .infinity, minHeight: height)
            .padding(.horizontal, Tokens.Space.xl)
            .background(Capsule().fill(configuration.isPressed ? Color.ds.accentPressed : Color.ds.accent))
            .contentShape(Capsule())
            .opacity(isEnabled ? 1 : 0.4)
    }
}

struct SecondaryButtonStyle: ButtonStyle {
    var height: Double = Tokens.Size.primaryButtonHeight
    var fillsWidth = true
    @Environment(\.isEnabled) private var isEnabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .dsFont(Tokens.TypeScale.uiButton)
            .foregroundStyle(Color.ds.ink)
            .frame(maxWidth: fillsWidth ? .infinity : nil, minHeight: height)
            .padding(.horizontal, Tokens.Space.xxl)
            .background(Capsule().fill(configuration.isPressed ? Color.ds.subtle : Color.ds.background))
            .overlay(Capsule().strokeBorder(Color.ds.ink, lineWidth: Tokens.Border.control))
            .contentShape(Capsule())
            .opacity(isEnabled ? 1 : 0.4)
    }
}

struct TextLinkButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .dsFont(TypeStyle(family: .ui, size: 15, weight: 500, lineHeight: nil, italic: false, relativeTo: .callout))
            .underline()
            .foregroundStyle(Color.ds.secondary)
            .frame(minHeight: Tokens.Size.minTouch)
            .contentShape(Rectangle())
            .opacity(configuration.isPressed ? 0.6 : 1)
    }
}

extension ButtonStyle where Self == PrimaryButtonStyle {
    static var dsPrimary: PrimaryButtonStyle { PrimaryButtonStyle() }
    /// The 50 pt variant used on Today cards.
    static var dsPrimaryCompact: PrimaryButtonStyle { PrimaryButtonStyle(height: Tokens.Size.homeButtonHeight) }
}

extension ButtonStyle where Self == SecondaryButtonStyle {
    static var dsSecondary: SecondaryButtonStyle { SecondaryButtonStyle() }
    static var dsSecondarySmall: SecondaryButtonStyle {
        SecondaryButtonStyle(height: Tokens.Size.secondaryButtonHeight, fillsWidth: false)
    }
}

extension ButtonStyle where Self == TextLinkButtonStyle {
    static var dsTextLink: TextLinkButtonStyle { TextLinkButtonStyle() }
}

// The web app's design language, ported to SwiftUI.
//
// Palette and type pairing come from `src/maestro/static/style.css`: a warm
// cream page, white cards on a sand border, terracotta for the one action
// that matters, and a serif for headings against a sans for everything else.
// Lora/Inter aren't bundled, so headings use the system serif (New York) —
// the same pairing without shipping font binaries.
//
// Deliberately small: colours, one card modifier, one progress bar. Screens
// stay stock SwiftUI and pick the rest up from `.tint`.

import SwiftUI
import UIKit

// The palette lives in UIColor so the bar appearance, which is configured
// before the SwiftUI environment exists, isn't converting Colors that early.
extension UIColor {
    convenience init(hex: UInt32) {
        self.init(
            red: CGFloat((hex >> 16) & 0xFF) / 255,
            green: CGFloat((hex >> 8) & 0xFF) / 255,
            blue: CGFloat(hex & 0xFF) / 255,
            alpha: 1)
    }

    static let mCharcoal = UIColor(hex: 0x2D2926)
    static let mCream = UIColor(hex: 0xFAF7F2)
    static let mTerracotta = UIColor(hex: 0xC75B39)
    static let mSage = UIColor(hex: 0x6B8F71)
    static let mGold = UIColor(hex: 0xD4A843)
    static let mBlue = UIColor(hex: 0x5B7F9E)
    static let mBorder = UIColor(hex: 0xE8E2D9)
    static let mText = UIColor(hex: 0x3D3833)
    static let mTextMuted = UIColor(hex: 0x8A8279)
    static let mSurface = UIColor(hex: 0xF3EDE4)
    static let mSuccess = UIColor(hex: 0x065F46)
    static let mSuccessBg = UIColor(hex: 0xECFDF5)
    static let mError = UIColor(hex: 0xB91C1C)
    static let mErrorBg = UIColor(hex: 0xFEF2F2)
}

extension Color {
    static let mCharcoal = Color(uiColor: .mCharcoal)
    static let mCream = Color(uiColor: .mCream)
    static let mTerracotta = Color(uiColor: .mTerracotta)
    static let mSage = Color(uiColor: .mSage)
    static let mGold = Color(uiColor: .mGold)
    static let mBlue = Color(uiColor: .mBlue)
    static let mBorder = Color(uiColor: .mBorder)
    static let mText = Color(uiColor: .mText)
    static let mTextMuted = Color(uiColor: .mTextMuted)
    static let mSurface = Color(uiColor: .mSurface)
    static let mSuccess = Color(uiColor: .mSuccess)
    static let mSuccessBg = Color(uiColor: .mSuccessBg)
    static let mError = Color(uiColor: .mError)
    static let mErrorBg = Color(uiColor: .mErrorBg)
}

extension View {
    /// The `.card` rule: white panel, sand hairline, generous padding.
    func card(padding: CGFloat = 20) -> some View {
        self
            .padding(padding)
            .background(.white, in: RoundedRectangle(cornerRadius: 10))
            .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Color.mBorder))
    }

    /// Cream page behind a scrolling screen, replacing the system grey.
    func creamBackground() -> some View {
        self
            .scrollContentBackground(.hidden)
            .background(Color.mCream)
    }
}

// No UINavigationBarAppearance proxy here on purpose: setting one on iOS 26
// stops the navigation title rendering at all. The bars stay stock and let
// the cream page show through.

/// The `.prompt` rule — a small uppercase label above the thing it names.
struct Eyebrow: View {
    let text: String

    var body: some View {
        Text(text.uppercased())
            .font(.caption2.weight(.semibold))
            .tracking(0.8)
            .foregroundStyle(Color.mTextMuted)
    }
}

/// The `.badge` rule: a pill of metadata on a card.
struct Badge: View {
    let text: String

    var body: some View {
        Text(text)
            .font(.caption2)
            .foregroundStyle(Color.mTextMuted)
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .background(Color.mSurface, in: Capsule())
    }
}

/// `templates/lesson-progress.html`: one segment per activity, so the
/// learner can see how much of the session is left rather than inferring it
/// from a counter. Grammar segments read differently because they teach
/// rather than test.
struct LessonProgressBar: View {
    let total: Int
    let current: Int
    /// Indices that teach rather than test, drawn in gold.
    var grammarIndices: Set<Int> = []

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 3) {
                ForEach(0..<max(total, 1), id: \.self) { i in
                    Capsule()
                        .fill(color(for: i))
                        .frame(height: 4)
                }
            }
            Text("\(min(current + 1, total)) of \(total)")
                .font(.caption2)
                .foregroundStyle(Color.mTextMuted)
        }
    }

    private func color(for index: Int) -> Color {
        if index == current { return .mTerracotta }
        if index < current { return grammarIndices.contains(index) ? .mGold : .mSage }
        return .mBorder
    }
}

import SwiftUI

// docs/07 § Components: Card, StatTile, SettingsGroup, ProgressBar, WeekDots, GoalChecklist, SkillBars.

/// 1 pt `divider` border, radius 18, padding 20; sections inside are separated by a 1 pt divider (`CardDivider`).
struct Card<Content: View>: View {
    @ViewBuilder var content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 0) { content }
            .padding(Tokens.Space.xl)
            .background(RoundedRectangle(cornerRadius: Tokens.Radius.card).fill(Color.ds.background))
            .overlay(
                RoundedRectangle(cornerRadius: Tokens.Radius.card)
                    .strokeBorder(Color.ds.divider, lineWidth: Tokens.Border.hairline))
    }
}

/// A full-bleed divider between card sections (cancels the card's horizontal padding).
struct CardDivider: View {
    var body: some View {
        Rectangle().fill(Color.ds.divider).frame(height: Tokens.Border.hairline)
            .padding(.horizontal, -Tokens.Space.xl)
            .padding(.vertical, Tokens.Space.xl)
            .accessibilityHidden(true)
    }
}

/// `surface` background, radius 14, padding 16; number in Literata 28/600, label 14 `secondary`.
struct StatTile: View {
    let value: String
    let label: String

    var body: some View {
        VStack(alignment: .leading, spacing: Tokens.Space.xs) {
            Text(value).dsFont(Tokens.TypeScale.sectionTitle).foregroundStyle(Color.ds.ink)
            Text(label).dsFont(Tokens.TypeScale.uiCaption).foregroundStyle(Color.ds.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(Tokens.Space.l)
        .background(RoundedRectangle(cornerRadius: Tokens.Radius.tile).fill(Color.ds.surface))
        .accessibilityElement(children: .combine)
    }
}

/// White rows on `surface`, radius 14, row min-height 52, row dividers `subtle`.
struct SettingsGroup<Content: View>: View {
    let title: String?
    @ViewBuilder var content: Content

    init(_ title: String? = nil, @ViewBuilder content: () -> Content) {
        self.title = title
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: Tokens.Space.s) {
            if let title {
                Text(title).dsFont(Tokens.TypeScale.uiMicro).textCase(.uppercase)
                    .foregroundStyle(Color.ds.secondary)
                    .padding(.horizontal, Tokens.Space.l)
                    .accessibilityAddTraits(.isHeader)
            }
            VStack(spacing: 0) {
                Group(subviews: content) { rows in
                    ForEach(Array(rows.enumerated()), id: \.offset) { index, row in
                        row
                            .frame(maxWidth: .infinity, minHeight: 52, alignment: .leading)
                            .padding(.horizontal, Tokens.Space.l)
                        if index < rows.count - 1 {
                            Rectangle().fill(Color.ds.subtle).frame(height: Tokens.Border.hairline)
                                .padding(.leading, Tokens.Space.l)
                        }
                    }
                }
            }
            .background(RoundedRectangle(cornerRadius: Tokens.Radius.tile).fill(Color.ds.background))
        }
        .padding(Tokens.Space.xs)
        .background(RoundedRectangle(cornerRadius: Tokens.Radius.tile + 4).fill(Color.ds.surface))
    }
}

/// 4 pt, radius 2, `divider` track, `accent` fill.
struct DSProgressBar: View {
    let value: Double  // 0…1

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                Capsule().fill(Color.ds.divider)
                Capsule().fill(Color.ds.accent).frame(width: geo.size.width * min(max(value, 0), 1))
            }
        }
        .frame(height: Tokens.Size.progressBarHeight)
        .accessibilityElement()
        .accessibilityValue(Text("\(Int((value * 100).rounded())) percent"))
    }
}

/// 7 circles of 32 pt; an active day is filled accent, inactive a 1.5 pt `divider` ring; letters under them.
struct WeekDots: View {
    /// Monday first; true = an active day (docs/05 § The Today planner, This week).
    let active: [Bool]
    let letters: [String]

    var body: some View {
        HStack(spacing: 0) {
            ForEach(0..<7, id: \.self) { i in
                VStack(spacing: Tokens.Space.s) {
                    Circle()
                        .fill(isActive(i) ? Color.ds.accent : Color.clear)
                        .overlay(Circle().strokeBorder(isActive(i) ? Color.clear : Color.ds.divider, lineWidth: 1.5))
                        .frame(width: 32, height: 32)
                    Text(i < letters.count ? letters[i] : "").dsFont(Tokens.TypeScale.uiCaption)
                        .foregroundStyle(Color.ds.secondary)
                }
                .frame(maxWidth: .infinity)
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(Text("This week: \(active.filter { $0 }.count) active days"))
    }

    private func isActive(_ i: Int) -> Bool { i < active.count && active[i] }
}

/// Rows with an empty circle, or a check in `success`.
struct GoalChecklist: View {
    struct Goal: Identifiable, Equatable {
        let id: String
        let text: String
        let done: Bool
    }

    let goals: [Goal]
    var identifierPrefix = "conv.goal"

    var body: some View {
        VStack(alignment: .leading, spacing: Tokens.Space.m) {
            ForEach(goals) { goal in
                HStack(alignment: .firstTextBaseline, spacing: Tokens.Space.m) {
                    Image(systemName: goal.done ? "checkmark.circle.fill" : "circle")
                        .foregroundStyle(goal.done ? Color.ds.success : Color.ds.inputBorder)
                        .accessibilityHidden(true)
                    Text(goal.text).dsFont(Tokens.TypeScale.uiBody).foregroundStyle(Color.ds.ink)
                }
                .accessibilityElement(children: .combine)
                .accessibilityValue(Text(goal.done ? "done" : "not yet"))
                .accessibilityIdentifier("\(identifierPrefix).\(goal.id)")
            }
        }
    }
}

/// Four 4-segment bars (read, listen, recall, speak), 20 × 6 segments, accent fill or `subtle` (docs/05 § Progress).
struct SkillBars: View {
    /// 0–4 per skill, in the order read, listen, recall, speak.
    let levels: [Int]
    let labels: [String]

    var body: some View {
        VStack(alignment: .leading, spacing: Tokens.Space.s) {
            ForEach(Array(levels.enumerated()), id: \.offset) { index, level in
                HStack(spacing: Tokens.Space.m) {
                    Text(index < labels.count ? labels[index] : "").dsFont(Tokens.TypeScale.uiCaption)
                        .foregroundStyle(Color.ds.secondary)
                        .frame(minWidth: 56, alignment: .leading)
                    HStack(spacing: 3) {
                        ForEach(0..<4, id: \.self) { seg in
                            RoundedRectangle(cornerRadius: 2)
                                .fill(seg < level ? Color.ds.accent : Color.ds.subtle)
                                .frame(width: 20, height: 6)
                        }
                    }
                }
                .accessibilityElement(children: .ignore)
                .accessibilityLabel(Text(index < labels.count ? labels[index] : ""))
                .accessibilityValue(Text("\(level) of 4"))
            }
        }
    }
}

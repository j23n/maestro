import LearningCore
import SwiftUI

/// The course map, *Indice* (`CourseMap.png`): an intro column with Moka's line on regular width, the unit list on
/// the right; one list on compact width. The current unit is tinted; locked units can't be opened.
struct CourseView: View {
    let rows: [CourseRow]
    let footer: String?
    let onOpenUnit: (UnitID) -> Void
    @Environment(\.isCompactWidth) private var isCompact

    var body: some View {
        if isCompact {
            ScrollView {
                VStack(alignment: .leading, spacing: Tokens.Space.xxl) {
                    intro
                    unitList
                    if let footer { mokaLine(footer) }
                }
                .padding(Tokens.Space.screenPaddingCompact)
            }
            .background(Color.ds.background)
        } else {
            HStack(alignment: .top, spacing: 0) {
                VStack(alignment: .leading, spacing: Tokens.Space.xxl) {
                    intro
                    Spacer()
                    if let footer { mokaLine(footer) }
                }
                .padding(Tokens.Space.screenPaddingRegular)
                .frame(width: 340, alignment: .leading)
                Divider()
                ScrollView {
                    unitList.padding(Tokens.Space.screenPaddingRegular)
                }
            }
            .background(Color.ds.background)
        }
    }

    private var intro: some View {
        VStack(alignment: .leading, spacing: Tokens.Space.m) {
            Text("Your course · Level A1").dsFont(Tokens.TypeScale.uiCallout).foregroundStyle(Color.ds.secondary)
            ItalianText("Indice", style: Tokens.TypeScale.display)
                .accessibilityAddTraits(.isHeader)
            Text("Contents").dsFont(Tokens.TypeScale.translation).italic().foregroundStyle(Color.ds.secondary)
            Text("Each unit is built around things you can do in Italian, and ends with a real conversation.")
                .dsFont(Tokens.TypeScale.uiBody).foregroundStyle(Color.ds.ink)
        }
    }

    private var unitList: some View {
        VStack(spacing: 0) {
            ForEach(Array(rows.enumerated()), id: \.element.unitID) { n, row in
                Button {
                    onOpenUnit(row.unitID)
                } label: {
                    rowView(row)
                }
                .buttonStyle(.plain)
                .disabled(!row.isOpen)
                .accessibilityElement(children: .combine)
                .accessibilityValue(Text(row.status ?? (row.isOpen ? "" : "Locked")))
                .accessibilityIdentifier("course.unit.\(row.number)")
                if n + 1 < rows.count && row.tone != .current && rows[n + 1].tone != .current {
                    Divider().padding(.leading, 72)
                }
            }
        }
    }

    private func rowView(_ row: CourseRow) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: Tokens.Space.xl) {
            Text("\(row.number)")
                .dsFont(Tokens.TypeScale.sectionTitle)
                .foregroundStyle(row.tone == .current ? Color.ds.accent : Color.ds.secondary)
                .frame(width: 40, alignment: .leading)
            VStack(alignment: .leading, spacing: Tokens.Space.xxs) {
                ItalianText(row.titleIt, style: Tokens.TypeScale.unitTitle)
                Text(row.subtitle).dsFont(Tokens.TypeScale.uiCallout).foregroundStyle(Color.ds.secondary)
            }
            Spacer(minLength: Tokens.Space.m)
            if let status = row.status {
                Text(status)
                    .dsFont(Tokens.TypeScale.uiCallout)
                    .fontWeight(row.tone == .next ? .regular : .semibold)
                    .foregroundStyle(statusColor(row.tone))
            }
        }
        .padding(.vertical, Tokens.Space.l)
        .padding(.horizontal, Tokens.Space.l)
        .background(
            RoundedRectangle(cornerRadius: Tokens.Radius.card)
                .fill(row.tone == .current ? Color.ds.accentTint : Color.clear)
        )
        .opacity(row.isOpen ? 1 : 0.55)
        .contentShape(Rectangle())
    }

    private func statusColor(_ tone: RowTone) -> Color {
        switch tone {
        case .done: Color.ds.success
        case .current: Color.ds.accent
        case .next, .none: Color.ds.secondary
        }
    }

    private func mokaLine(_ text: String) -> some View {
        HStack(alignment: .center, spacing: Tokens.Space.l) {
            Mascot(pose: .think, size: 72, decorative: true, isHint: true)
            MixedText(text: text, style: Tokens.TypeScale.translation)
                .foregroundStyle(Color.ds.secondary)
        }
        .accessibilityIdentifier("course.footer")
    }
}

/// The unit overview, which is also the unit's opener step (`Unit.png`, docs/06 § Opener and Use): unit number,
/// Italian title and English subtitle, the can-dos (ticked when reached), the unit's stories, notes and tasks with
/// their state, and **Continue with …**.
struct UnitView<Accessory: View>: View {
    let overview: UnitOverview
    let onOpenStep: (StepID) -> Void
    /// Shown under the title, in the scrolling content (the final review unit's final-check card).
    @ViewBuilder var accessory: () -> Accessory

    var body: some View {
        VStack(spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: Tokens.Space.xxl) {
                    VStack(alignment: .leading, spacing: Tokens.Space.s) {
                        Text(overview.unitLine).dsFont(Tokens.TypeScale.uiCallout)
                            .foregroundStyle(Color.ds.secondary)
                        ItalianText(overview.titleIt, style: Tokens.TypeScale.display)
                            .accessibilityAddTraits(.isHeader)
                        Text(overview.titleEn).dsFont(Tokens.TypeScale.translation).italic()
                            .foregroundStyle(Color.ds.secondary)
                    }
                    accessory()
                    if !overview.canDos.isEmpty { canDos }
                    steps
                }
                .readableColumn()
                .padding(.vertical, Tokens.Space.xxl)
            }
            Button(overview.primary) { if let step = overview.primaryStep { onOpenStep(step) } }
                .buttonStyle(.dsPrimary)
                .disabled(overview.primaryStep == nil)
                .keyboardShortcut(.return, modifiers: [])
                .accessibilityIdentifier("opener.continue")
                .readableColumn()
                .padding(.vertical, Tokens.Space.l)
        }
        .background(Color.ds.background)
    }

    private var canDos: some View {
        VStack(alignment: .leading, spacing: Tokens.Space.m) {
            Text("By the end you can").dsFont(Tokens.TypeScale.uiCallout).fontWeight(.semibold)
                .foregroundStyle(Color.ds.secondary)
            ForEach(Array(overview.canDos.enumerated()), id: \.offset) { n, c in
                HStack(alignment: .firstTextBaseline, spacing: Tokens.Space.m) {
                    Image(systemName: c.reached ? "checkmark" : "circle")
                        .foregroundStyle(c.reached ? Color.ds.success : Color.ds.inputBorder)
                        .frame(width: 24)
                        .accessibilityHidden(true)
                    Text(c.en).dsFont(Tokens.TypeScale.uiBody).foregroundStyle(Color.ds.ink)
                }
                .accessibilityElement(children: .combine)
                .accessibilityValue(Text(c.reached ? "reached" : "not yet"))
                .accessibilityIdentifier("opener.cando.\(n)")
            }
        }
    }

    private var steps: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("In this unit").dsFont(Tokens.TypeScale.uiCallout).fontWeight(.semibold)
                .foregroundStyle(Color.ds.secondary)
                .padding(.bottom, Tokens.Space.s)
            ForEach(Array(overview.rows.enumerated()), id: \.element.stepID) { n, row in
                Button {
                    onOpenStep(row.stepID)
                } label: {
                    HStack(alignment: .firstTextBaseline, spacing: Tokens.Space.l) {
                        Text(row.label)
                            .dsFont(Tokens.TypeScale.uiCallout)
                            .foregroundStyle(row.tone == .next ? Color.ds.accent : Color.ds.secondary)
                            .frame(width: 96, alignment: .leading)
                        if row.titleIsItalian {
                            ItalianText(row.title, style: Tokens.TypeScale.rowTitle)
                        } else {
                            Text(row.title).dsFont(Tokens.TypeScale.uiBody).foregroundStyle(Color.ds.ink)
                        }
                        Spacer(minLength: Tokens.Space.m)
                        if let status = row.status {
                            Text(status).dsFont(Tokens.TypeScale.uiCallout).fontWeight(.semibold)
                                .foregroundStyle(row.tone == .done ? Color.ds.success : Color.ds.accent)
                        }
                    }
                    .padding(.vertical, Tokens.Space.l)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityElement(children: .combine)
                .accessibilityIdentifier("opener.step.\(n)")
                if n + 1 < overview.rows.count { Divider() }
            }
        }
    }
}

extension UnitView where Accessory == EmptyView {
    init(overview: UnitOverview, onOpenStep: @escaping (StepID) -> Void) {
        self.init(overview: overview, onOpenStep: onOpenStep, accessory: { EmptyView() })
    }
}

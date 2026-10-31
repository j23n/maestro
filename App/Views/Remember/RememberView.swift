import SwiftData
import SwiftUI
import ItalianCore
import SRSKit

/// The Remember tab (HANDOFF.md 3.4): due count with Review, filters, New / Due today / Later.
struct RememberView: View {
    @Environment(AppModel.self) private var model
    @Environment(Preferences.self) private var prefs
    @Environment(\.modelContext) private var context
    @Query(sort: \Card.createdAt, order: .reverse) private var cards: [Card]
    @Query private var states: [ScheduleState]
    @State private var filter: ItemKind?
    @State private var reviewing = false

    private var active: [Card] {
        var seen = Set<String>()
        return cards.filter { $0.isActive && (filter == nil || $0.kind == filter?.rawValue) && seen.insert($0.itemKey).inserted }
    }

    var body: some View {
        let stateByKey = Dictionary(states.map { ($0.itemKey, $0) }, uniquingKeysWith: { a, _ in a })
        let now = Date.now
        let endOfToday = Calendar.current.startOfDay(for: now).addingTimeInterval(86400)
        let new = active.filter { (stateByKey[$0.itemKey]?.reps ?? 0) == 0 }
        let due = active.filter { c in stateByKey[c.itemKey].map { $0.reps > 0 && $0.due < endOfToday } ?? false }
        let later = active.filter { c in stateByKey[c.itemKey].map { $0.reps > 0 && $0.due >= endOfToday } ?? false }
        let queueCount = RememberStore(context: context, prefs: prefs, content: model.content).queue(now: now).count

        List {
            Section {
                HStack(alignment: .center, spacing: 12) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(queueCount == 0 ? "Nothing due" : "\(queueCount) due")
                            .font(.system(size: 28, weight: .bold))
                        Text("\(due.count) to review, \(min(new.count, prefs.newItemsPerDay)) new today")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                    Spacer(minLength: 8)
                    Button("Review") { reviewing = true }
                        .buttonStyle(PrimaryButtonStyle(fullWidth: false))
                        .disabled(queueCount == 0)
                }
                .padding(16)
                .background(Theme.surface, in: RoundedRectangle(cornerRadius: 16))
            }
            .listRowInsets(EdgeInsets(top: 8, leading: 16, bottom: 4, trailing: 16))
            .listRowSeparator(.hidden)
            Section {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        filterChip(nil, "All")
                        filterChip(.word, "Words")
                        filterChip(.verbForm, "Verb forms")
                        filterChip(.grammar, "Grammar")
                    }
                }
            }
            .listRowInsets(EdgeInsets(top: 0, leading: 16, bottom: 0, trailing: 16))
            .listRowSeparator(.hidden)
            if active.isEmpty {
                EmptyState(title: "Nothing kept yet",
                           message: "Tap a word while reading and choose Remember to add it here.",
                           systemImage: "rectangle.stack.badge.plus")
            }
            group("New", new, stateByKey: stateByKey)
            group("Due today", due, stateByKey: stateByKey)
            group("Later", later, stateByKey: stateByKey)
        }
        .plainPage()
        .navigationTitle("Remember")
        #if DEBUG
        .task { if UITestLaunch.review { reviewing = true } }
        #endif
        #if os(macOS)
        .sheet(isPresented: $reviewing) {
            ReviewView().frame(minWidth: 560, minHeight: 620)
        }
        #else
        .fullScreenCover(isPresented: $reviewing) {
            ReviewView()
        }
        #endif
    }

    private func filterChip(_ kind: ItemKind?, _ title: String) -> some View {
        var seen = Set<String>()
        let count = cards.filter { $0.isActive && (kind == nil || $0.kind == kind?.rawValue) && seen.insert($0.itemKey).inserted }.count
        return Button {
            filter = kind
        } label: {
            ChipLabel(title: title, count: count, selected: filter == kind)
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(filter == kind ? .isSelected : [])
    }

    @ViewBuilder
    private func group(_ title: String, _ cards: [Card], stateByKey: [String: ScheduleState]) -> some View {
        if !cards.isEmpty {
            LabeledSection(title) {
                ForEach(cards) { card in
                    CardRow(card: card, due: stateByKey[card.itemKey].flatMap { $0.reps > 0 ? $0.due : nil })
                        .swipeActions {
                            Button(role: .destructive) {
                                RememberStore(context: context, prefs: prefs, content: model.content).delete(card)
                            } label: {
                                Label("Delete", systemImage: "trash")
                            }
                        }
                        .contextMenu {
                            Button(role: .destructive) {
                                RememberStore(context: context, prefs: prefs, content: model.content).delete(card)
                            } label: {
                                Label("Delete", systemImage: "trash")
                            }
                        }
                }
            }
        }
    }
}

struct CardRow: View {
    let card: Card
    let due: Date?
    @Environment(AppModel.self) private var model

    var body: some View {
        let kind = ItemKind(rawValue: card.kind) ?? .word
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 6) {
                KindTag(kind: kind)
                if let source = model.entries.first(where: { $0.id == card.sourceTextID })?.title {
                    Text(source).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                }
                Spacer(minLength: 8)
                Group {
                    if let due {
                        Text(due, format: .relative(presentation: .named))
                    } else {
                        Text("new")
                    }
                }
                .font(.caption)
                .foregroundStyle(.secondary)
            }
            line(kind)
        }
        .padding(.vertical, 4)
    }

    private func line(_ kind: ItemKind) -> Text {
        let title = CardText.title(card, model: model)
        var head = AttributedString(title)
        head.languageIdentifier = kind == .grammar ? nil : "it-IT"
        let t = Text(head).font(kind == .grammar ? .body.weight(.semibold) : .system(.body, design: .serif).weight(.semibold))
        guard let detail = CardText.detail(card, model: model) else { return t }
        return Text("\(t) — \(detail)")
    }
}

/// How a card's item reads, from the content DB when it knows the IDs, else from the snapshot.
@MainActor enum CardText {
    static func title(_ card: Card, model: AppModel) -> String {
        switch ItemKind(rawValue: card.kind) ?? .word {
        case .word: model.content?.lemma(card.lemmaID)?.headword ?? LemmaID.headword(of: card.lemmaID)
        case .verbForm: card.surface
        case .grammar: model.grammarTitle(card.grammarID)
        }
    }

    static func detail(_ card: Card, model: AppModel) -> String? {
        switch ItemKind(rawValue: card.kind) ?? .word {
        case .word:
            return model.content?.sense(card.senseID)?.gloss ?? model.content?.lemma(card.lemmaID)?.firstGloss
        case .verbForm:
            guard let tag = FormTag(card.formTag) else { return nil }
            return "\(LemmaID.headword(of: card.lemmaID)) · \(tag.label)"
        case .grammar:
            return model.grammarTopic(card.grammarID)?.summary
        }
    }
}

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
                VStack(alignment: .leading, spacing: 10) {
                    Text(queueCount == 0 ? "Nothing to review" : "\(queueCount) to review")
                        .font(.title2.weight(.bold))
                    Text("\(due.count) due, \(min(new.count, prefs.newItemsPerDay)) new today")
                        .foregroundStyle(.secondary)
                    Button {
                        reviewing = true
                    } label: {
                        Text("Review").frame(maxWidth: .infinity, minHeight: 44)
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(queueCount == 0)
                }
                .padding(.vertical, 6)
            }
            Section {
                Picker("Show", selection: $filter) {
                    Text("All").tag(ItemKind?.none)
                    Text("Words").tag(ItemKind?.some(.word))
                    Text("Verb forms").tag(ItemKind?.some(.verbForm))
                    Text("Grammar").tag(ItemKind?.some(.grammar))
                }
                .pickerStyle(.segmented)
            }
            if active.isEmpty {
                EmptyState(title: "Nothing kept yet",
                           message: "Tap a word while reading and choose Remember to add it here.",
                           systemImage: "rectangle.stack.badge.plus")
            }
            group("New", new, stateByKey: stateByKey)
            group("Due today", due, stateByKey: stateByKey)
            group("Later", later, stateByKey: stateByKey)
        }
        .navigationTitle("Remember")
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

    @ViewBuilder
    private func group(_ title: String, _ cards: [Card], stateByKey: [String: ScheduleState]) -> some View {
        if !cards.isEmpty {
            Section("\(title) · \(cards.count)") {
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
        HStack(spacing: 10) {
            KindTag(kind: kind)
            VStack(alignment: .leading, spacing: 2) {
                Text(italian: CardText.title(card, model: model)).font(.body.weight(.semibold))
                if let detail = CardText.detail(card, model: model) {
                    Text(detail).font(.footnote).foregroundStyle(.secondary).lineLimit(1)
                }
            }
            Spacer()
            if let due {
                Text(due, format: .relative(presentation: .numeric))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.vertical, 2)
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

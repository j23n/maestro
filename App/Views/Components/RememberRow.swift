import SwiftData
import SwiftUI
import ItalianCore

/// One keepable item with its Remember / Added toggle (HANDOFF.md 3.1).
struct RememberRow: View {
    let item: RememberItem
    let title: String
    let detail: String?

    var body: some View {
        HStack(spacing: 10) {
            KindTag(kind: item.kind)
            VStack(alignment: .leading, spacing: 1) {
                Text(italian: title).font(.body.weight(.semibold))
                if let detail {
                    Text(detail).font(.footnote).foregroundStyle(.secondary).lineLimit(2)
                }
            }
            Spacer(minLength: 8)
            RememberButton(item: item, title: title)
        }
    }
}

/// The Remember / Added toggle: an outlined capsule that turns green once the item is kept.
struct RememberButton: View {
    let item: RememberItem
    let title: String

    @Environment(AppModel.self) private var model
    @Environment(Preferences.self) private var prefs
    @Environment(\.modelContext) private var context
    @Query private var matching: [Card]

    init(item: RememberItem, title: String) {
        self.item = item
        self.title = title
        let key = item.key
        _matching = Query(filter: #Predicate<Card> { $0.itemKey == key })
    }

    private var isAdded: Bool { matching.contains { $0.isActive } }

    var body: some View {
        Button {
            RememberStore(context: context, prefs: prefs, content: model.content).toggle(item)
        } label: {
            HStack(spacing: 4) {
                Image(systemName: isAdded ? "checkmark" : "plus").font(.caption.weight(.bold))
                Text(isAdded ? "Added" : "Remember")
            }
            .font(.subheadline.weight(.semibold))
            .lineLimit(1)
            .fixedSize()
            .padding(.horizontal, 12)
            .frame(minHeight: 32)
            .foregroundStyle(isAdded ? Theme.added.foreground : Theme.ink)
            .background(Capsule().fill(isAdded ? Theme.added.background : Color.clear))
            .overlay(Capsule().stroke(isAdded ? Theme.addedBorder : Theme.borderControl))
        }
        .buttonStyle(.plain)
        .contentShape(Rectangle())
        .frame(minHeight: 44)
        .accessibilityLabel(isAdded ? "Added to Remember. Remove \(title)" : "Remember \(title)")
    }
}

extension RememberItem {
    /// Title and detail for a Remember row.
    @MainActor func rowText(model: AppModel) -> (title: String, detail: String?) {
        switch kind {
        case .word:
            let gloss = model.content?.sense(senseID)?.gloss ?? model.content?.lemma(lemmaID)?.firstGloss
            return (LemmaID.headword(of: lemmaID), gloss)
        case .verbForm:
            let tag = FormTag(formTag)
            let detail = tag.map { t in [t.shortTenseLabel, t.person?.pronoun].compactMap { $0 }.joined(separator: ", ") }
            return (surface, detail)
        case .grammar:
            return (model.grammarTitle(grammarID), model.grammarTopic(grammarID)?.summary)
        }
    }
}

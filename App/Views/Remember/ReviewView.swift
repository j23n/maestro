import SwiftData
import SwiftUI
import ItalianCore
import SRSKit

/// Flashcard review (HANDOFF.md 3.4): the sentence with the item highlighted and a prompt; the
/// back shows the answer; Again / Hard / Good / Easy with the next interval. Mac keys: Space shows
/// the answer, 1 to 4 grade.
struct ReviewView: View {
    @Environment(AppModel.self) private var model
    @Environment(Preferences.self) private var prefs
    @Environment(\.modelContext) private var context
    @Environment(\.dismiss) private var dismiss
    @State private var queue: [Card] = []
    @State private var position = 0
    @State private var showAnswer = false
    @State private var shownAt = Date.now
    @State private var reviewed = 0
    @FocusState private var focused: Bool

    private var store: RememberStore { RememberStore(context: context, prefs: prefs, content: model.content) }

    var body: some View {
        NavigationStack {
            Group {
                if position < queue.count {
                    card(queue[position])
                } else {
                    done
                }
            }
            .navigationTitle(position < queue.count ? "\(position + 1) of \(queue.count)" : "Review")
            #if os(iOS)
            .navigationBarTitleDisplayMode(.inline)
            #endif
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Close") { dismiss() }
                }
            }
        }
        .focusable()
        .focused($focused)
        .focusEffectDisabled()
        .onKeyPress(.space) {
            guard !showAnswer, position < queue.count else { return .ignored }
            showAnswer = true
            return .handled
        }
        .onKeyPress(characters: CharacterSet(charactersIn: "1234")) { press in
            guard showAnswer, position < queue.count, let n = Int(press.characters), let rating = Rating(rawValue: n)
            else { return .ignored }
            grade(rating)
            return .handled
        }
        .onAppear {
            queue = store.queue()
            shownAt = .now
            focused = true
        }
    }

    private var done: some View {
        VStack(spacing: 16) {
            Image(systemName: "checkmark.circle").font(.system(size: 56)).foregroundStyle(Theme.added.foreground)
            Text(reviewed == 0 ? "Nothing to review" : "Done for now").font(.title2.weight(.bold))
            if reviewed > 0 { Text("You reviewed \(reviewed) cards.").foregroundStyle(.secondary) }
            Button("Close") { dismiss() }.buttonStyle(PrimaryButtonStyle(fullWidth: false))
        }
        .padding()
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func card(_ card: Card) -> some View {
        let kind = ItemKind(rawValue: card.kind) ?? .word
        return VStack(spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    HStack(spacing: 6) {
                        KindTag(kind: kind)
                        if let source = model.entries.first(where: { $0.id == card.sourceTextID })?.title {
                            Text(source).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                        }
                    }
                    front(card, kind: kind)
                    if showAnswer {
                        Divider()
                        back(card, kind: kind)
                    }
                }
                .padding(20)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(RoundedRectangle(cornerRadius: 18).fill(Theme.background))
                .overlay(RoundedRectangle(cornerRadius: 18).stroke(Theme.hairline))
                .padding(16)
                .frame(maxWidth: 640)
                .frame(maxWidth: .infinity)
            }
            controls(card)
                .padding(16)
                .frame(maxWidth: 640)
                .frame(maxWidth: .infinity)
        }
    }

    @ViewBuilder
    private func front(_ card: Card, kind: ItemKind) -> some View {
        if !card.sentenceText.isEmpty {
            Text(highlighted(card))
                .font(.system(size: 26, design: .serif))
                .lineSpacing(8)
        } else {
            Text(italian: CardText.title(card, model: model))
                .font(.system(size: 30, weight: .semibold, design: .serif))
        }
        Text(kind.prompt).font(.subheadline).foregroundStyle(.secondary)
    }

    @ViewBuilder
    private func back(_ card: Card, kind: ItemKind) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            switch kind {
            case .word:
                Text(italian: CardText.title(card, model: model)).font(.system(.title2, design: .serif).weight(.semibold))
                if let gloss = CardText.detail(card, model: model) { Text(gloss).font(.title3) }
            case .verbForm:
                Text(italian: card.surface).font(.system(.title2, design: .serif).weight(.semibold))
                if let tag = FormTag(card.formTag) {
                    Text("\(LemmaID.headword(of: card.lemmaID)) · \(tag.label)").font(.title3)
                    if let row = model.conjugator?.table(for: card.lemmaID)?.row(for: tag) {
                        Text(italian: row).font(.system(.body, design: .serif)).foregroundStyle(.secondary)
                    }
                }
            case .grammar:
                Text(model.grammarTitle(card.grammarID)).font(.title2.weight(.semibold))
                if let summary = model.grammarTopic(card.grammarID)?.summary { Text(markdown: summary).font(.title3) }
            }
            if !card.sentenceTranslation.isEmpty {
                Text(card.sentenceTranslation).font(.subheadline).foregroundStyle(.secondary).padding(.top, 6)
            }
        }
    }

    @ViewBuilder
    private func controls(_ card: Card) -> some View {
        if showAnswer {
            let previews = store.scheduler.preview(store.schedule(for: card.itemKey) ?? Schedule(), at: .now,
                                                   tzOffsetMinutes: TimeZone.current.secondsFromGMT() / 60)
            HStack(spacing: 8) {
                ForEach(Rating.allCases, id: \.self) { rating in
                    let colors = Theme.grade(rating.rawValue)
                    Button {
                        grade(rating)
                    } label: {
                        VStack(spacing: 2) {
                            Text(rating.label).font(.subheadline.weight(.semibold))
                            if let due = previews[rating] {
                                Text(ReviewQueue.label(from: .now, to: due)).font(.caption2).monospacedDigit()
                            }
                        }
                        .frame(maxWidth: .infinity, minHeight: 52)
                        .foregroundStyle(colors.foreground)
                        .background(colors.background, in: RoundedRectangle(cornerRadius: 12))
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("\(rating.label), next in \(previews[rating].map { ReviewQueue.label(from: .now, to: $0) } ?? "")")
                }
            }
        } else {
            Button {
                showAnswer = true
            } label: {
                Text("Show answer")
            }
            .buttonStyle(PrimaryButtonStyle())
        }
    }

    private func highlighted(_ card: Card) -> AttributedString {
        var a = AttributedString(card.sentenceText)
        a.languageIdentifier = "it-IT"
        for r in UTF16Range.list(from: card.highlightRanges) {
            if let range = Range(NSRange(location: r.start, length: r.length), in: a) {
                a[range].backgroundColor = Theme.selectionFill
                a[range].inlinePresentationIntent = .stronglyEmphasized
            }
        }
        return a
    }

    private func grade(_ rating: Rating) {
        guard position < queue.count else { return }
        let card = queue[position]
        let ms = Int(Date.now.timeIntervalSince(shownAt) * 1000)
        store.review(card, rating: rating, durationMs: ms)
        reviewed += 1
        // Again in a learning step comes back in this session.
        if let s = store.schedule(for: card.itemKey), s.due.timeIntervalSinceNow < 20 * 60 {
            queue.append(card)
        }
        position += 1
        showAnswer = false
        shownAt = .now
    }
}

import SwiftUI
import ItalianCore
import PackKit

/// Tap-for-help (HANDOFF.md 3.1): in a sheet on the iPhone, in the reader's inspector on the iPad
/// and the Mac.
struct HelpView: View {
    let help: HelpContent
    /// In a sheet with its own NavigationStack, rather than in the reader's inspector.
    var inSheet = false
    let close: () -> Void
    @Environment(AppModel.self) private var model
    @Environment(Preferences.self) private var prefs

    /// The sentence's translation shows beside the text (iPad and Mac), not in the iPhone's sheet.
    private var showsTranslation: Bool { !inSheet && prefs.translationInHelp }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                header
                if !help.splits.isEmpty {
                    VStack(alignment: .leading, spacing: 4) {
                        ForEach(help.splits, id: \.self) { split in
                            Text(italian: split).font(.system(.body, design: .serif))
                        }
                    }
                }
                if let noteText {
                    VStack(alignment: .leading, spacing: 4) {
                        if let first = help.grammarIDs.first {
                            Text(model.grammarTitle(first)).font(.subheadline.weight(.semibold))
                                .foregroundStyle(Theme.info.foreground)
                        }
                        Text(markdown: noteText).font(.subheadline)
                    }
                    .padding(12)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Theme.info.background, in: RoundedRectangle(cornerRadius: 12))
                }
                if showsTranslation {
                    VStack(alignment: .leading, spacing: 4) {
                        SectionLabel("Sentence")
                        Text(help.sentenceTranslation).font(.subheadline).foregroundStyle(.secondary)
                    }
                }
                if !help.items.isEmpty {
                    VStack(alignment: .leading, spacing: 10) {
                        SectionLabel("Remember")
                        ForEach(help.items) { item in
                            let text = item.rowText(model: model)
                            RememberRow(item: item, title: text.title, detail: text.detail)
                        }
                    }
                }
                links
            }
            .padding(20)
        }
        .accessibilityIdentifier("help")
        .modifier(SheetChrome(active: inSheet, title: help.surface, close: close))
    }

    private var noteText: String? {
        if let note = help.note { return note }
        if let first = help.grammarIDs.first { return model.grammarTopic(first)?.summary }
        return nil
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline) {
                Text(italian: help.surface)
                    .font(.system(size: 26, weight: .semibold, design: .serif))
                Button {
                    model.speech.say(help.surface)
                } label: {
                    Image(systemName: "speaker.wave.2.fill")
                        .frame(width: 44, height: 44)
                }
                .buttonStyle(.borderless)
                .accessibilityLabel("Play \(help.surface)")
                Spacer()
                if !inSheet {
                    Button(action: close) {
                        Image(systemName: "xmark")
                            .frame(width: 44, height: 44)
                    }
                    .buttonStyle(.borderless)
                    .accessibilityLabel("Close help")
                    .accessibilityIdentifier("closeHelp")
                }
            }
            if let gloss = help.gloss {
                Text(gloss).font(.title3)
            }
            if let headword = help.headword {
                Text("\(Text(italian: headword).bold())\(help.analysis.map { " · \($0)" } ?? "")")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
        }
    }

    @ViewBuilder private var links: some View {
        if let lemmaID = help.lemmaID, model.content?.lemma(lemmaID) != nil {
            VStack(alignment: .leading, spacing: 0) {
                Divider()
                if help.isVerb {
                    NavigationLink(value: Route.verb(lemmaID: lemmaID, formTag: help.formTag)) {
                        linkRow("Open \(LemmaID.headword(of: lemmaID))", systemImage: "tablecells")
                    }
                }
                NavigationLink(value: Route.entry(lemmaID)) {
                    linkRow("In dictionary", systemImage: "character.book.closed")
                }
                ForEach(help.grammarIDs, id: \.self) { g in
                    NavigationLink(value: Route.grammar(g)) {
                        linkRow(model.grammarTitle(g), systemImage: "text.book.closed")
                    }
                }
            }
            .buttonStyle(.plain)
        }
    }

    private func linkRow(_ title: String, systemImage: String) -> some View {
        HStack {
            Label(title, systemImage: systemImage)
            Spacer()
            Image(systemName: "chevron.right").font(.footnote).foregroundStyle(.tertiary)
        }
        .frame(minHeight: 44)
        .contentShape(Rectangle())
    }
}

/// The sheet's title and Done button. In the inspector, the reader's title and toolbar stay.
private struct SheetChrome: ViewModifier {
    let active: Bool
    let title: String
    let close: () -> Void

    func body(content: Content) -> some View {
        #if os(iOS)
        if active {
            content
                .navigationTitle(title)
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) {
                        Button("Done", action: close).accessibilityIdentifier("closeHelp")
                    }
                }
        } else {
            content
        }
        #else
        content
        #endif
    }
}

extension Text {
    /// Inline Markdown (*italic*, **bold**), falling back to the plain string.
    init(markdown: String) {
        if let attributed = try? AttributedString(markdown: markdown,
                                                  options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace)) {
            self.init(attributed)
        } else {
            self.init(markdown)
        }
    }
}

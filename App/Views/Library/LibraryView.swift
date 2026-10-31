import SwiftData
import SwiftUI

/// The library (HANDOFF.md 3.5): search, level chips, Continue reading, Good fit, By level.
struct LibraryView: View {
    @Environment(AppModel.self) private var model
    @Environment(Preferences.self) private var prefs
    @Query private var cards: [Card]
    @Query(sort: \TextProgress.updatedAt, order: .reverse) private var progress: [TextProgress]
    @State private var search = ""
    @State private var levelFilter: String?

    private var known: KnownWordsModel { KnownWordsModel(model: model, cards: cards, progress: progress) }

    private var progressByText: [String: TextProgress] {
        var map: [String: TextProgress] = [:]
        for p in progress where map[p.textID] == nil { map[p.textID] = p }
        return map
    }

    private var filtered: [LibraryEntry] {
        model.entries.filter { entry in
            (levelFilter == nil || entry.level == levelFilter)
                && (search.isEmpty || entry.title.localizedCaseInsensitiveContains(search)
                    || entry.collection.localizedCaseInsensitiveContains(search))
        }
    }

    var body: some View {
        let known = self.known
        let progressByText = self.progressByText
        List {
            if model.entries.isEmpty {
                EmptyState(title: "No texts yet",
                           message: "This build has no text packs. Run make content to build the starter texts.",
                           systemImage: "books.vertical")
            } else {
                Section { levelChips }
                    .listRowInsets(EdgeInsets(top: 4, leading: 16, bottom: 4, trailing: 16))
                    .listRowSeparator(.hidden)

                let continuing = filtered.filter {
                    guard let p = progressByText[$0.id] else { return false }
                    return p.finishedAt == nil && p.position > 0.02
                }
                if !continuing.isEmpty && search.isEmpty {
                    LabeledSection("Continue reading") {
                        ForEach(continuing.prefix(3)) { entry in
                            row(entry, known: known, progress: progressByText[entry.id])
                        }
                    }
                }

                let goodFit = filtered.filter { known.isGoodFit($0.id) && progressByText[$0.id]?.finishedAt == nil }
                if !goodFit.isEmpty && search.isEmpty {
                    Section {
                        ForEach(goodFit.prefix(4)) { entry in
                            row(entry, known: known, progress: progressByText[entry.id])
                        }
                    } header: {
                        SectionLabel("Good fit for you")
                    } footer: {
                        Text("Texts where you know about 90 to 97% of the words.")
                    }
                }

                ForEach(["A1", "A2", "B1", "B2"], id: \.self) { level in
                    let texts = filtered.filter { $0.level == level }
                    if !texts.isEmpty {
                        Section {
                            ForEach(texts) { entry in
                                row(entry, known: known, progress: progressByText[entry.id])
                            }
                        } header: {
                            let done = texts.filter { progressByText[$0.id]?.finishedAt != nil }.count
                            HStack {
                                SectionLabel("\(level) · \(levelName(level))")
                                Spacer()
                                Text("\(done) of \(texts.count) read").font(.caption).monospacedDigit().foregroundStyle(.secondary)
                            }
                        }
                    }
                }
            }
        }
        .plainPage()
        .navigationTitle("Read")
        .searchable(text: $search, prompt: "Search texts")
        .toolbar {
            #if os(iOS)
            ToolbarItem(placement: .topBarTrailing) {
                NavigationLink(value: Route.settings) {
                    Image(systemName: "gearshape")
                }
                .accessibilityLabel("Settings")
            }
            #endif
        }
    }

    private var levelChips: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                chip(nil, title: "All", count: model.entries.count)
                ForEach(["A1", "A2", "B1", "B2"], id: \.self) { level in
                    chip(level, title: level, count: model.entries.filter { $0.level == level }.count)
                }
            }
            .padding(.vertical, 4)
        }
    }

    private func chip(_ level: String?, title: String, count: Int) -> some View {
        let selected = levelFilter == level
        return Button {
            levelFilter = level
        } label: {
            ChipLabel(title: title, count: count, selected: selected)
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(selected ? .isSelected : [])
    }

    private func row(_ entry: LibraryEntry, known: KnownWordsModel, progress: TextProgress?) -> some View {
        NavigationLink(value: Route.text(entry.id)) {
            TextRow(entry: entry, knownPercent: known.percent(entry.id), progress: progress)
        }
    }

    private func levelName(_ level: String) -> String {
        switch level {
        case "A1": "Beginner"
        case "A2": "Elementary"
        case "B1": "Intermediate"
        default: "Upper intermediate"
        }
    }
}

struct TextRow: View {
    let entry: LibraryEntry
    let knownPercent: Int?
    let progress: TextProgress?

    var body: some View {
        HStack(alignment: .center, spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text(italian: entry.title)
                    .font(.system(.body, design: .serif).weight(.semibold))
                HStack(spacing: 6) {
                    LevelTag(level: entry.level)
                    Text("\(entry.collection) · \(entry.words) words")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }
            Spacer(minLength: 8)
            VStack(alignment: .trailing, spacing: 2) {
                if progress?.finishedAt != nil {
                    Label("Read", systemImage: "checkmark.circle.fill")
                        .labelStyle(.iconOnly)
                        .foregroundStyle(Theme.added.foreground)
                        .accessibilityLabel("Finished")
                } else if let p = progress, p.position > 0.02 {
                    Text("\(Int(p.position * 100))%").font(.footnote).monospacedDigit().foregroundStyle(.secondary)
                }
                if let knownPercent {
                    Text("\(knownPercent)% known").font(.caption).monospacedDigit().foregroundStyle(.secondary)
                }
            }
        }
        .padding(.vertical, 4)
    }
}

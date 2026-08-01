// The vocabulary the pack teaches, and where the learner stands on each
// word — the web app's /vocab page, rebuilt on the core's SM-2 fold.
//
// Two things share this file with the session's vocab activity: the card
// face and the three-way SM-2 rating. Reviewing a word from here and
// meeting it inside a lesson must schedule identically, so they run the
// same grades through the same event.

import SwiftUI

struct VocabularyScreen: View {
    let bridge: CoreBridge

    @State private var entries: [VocabEntry] = []
    @State private var query = ""
    @State private var level = "All"
    @State private var reviewing: VocabQueue?
    @State private var error: String?

    private var levels: [String] {
        ["All"] + Array(Set(entries.map(\.cefrLevel))).sorted()
    }

    private var filtered: [VocabEntry] {
        let needle = query.trimmingCharacters(in: .whitespaces).lowercased()
        return entries.filter { entry in
            guard level == "All" || entry.cefrLevel == level else { return false }
            guard !needle.isEmpty else { return true }
            return entry.lemma.lowercased().contains(needle)
                || entry.gloss.lowercased().contains(needle)
                || (entry.back?.lowercased().contains(needle) ?? false)
        }
    }

    /// Overdue cards first, then words a lesson has just handed over —
    /// the same order the session composer weights by.
    private var due: [VocabEntry] {
        entries
            .filter { ($0.status == "due" || $0.status == "discovered") && $0.isPractisable }
            .sorted {
                ($0.reviews == 0 ? 1 : 0, $0.dueInDays ?? 0)
                    < ($1.reviews == 0 ? 1 : 0, $1.dueInDays ?? 0)
            }
    }

    var body: some View {
        NavigationStack {
            List {
                // Stats and filter share a section: as two, the list's
                // section spacing opens a gap wide enough to read as a
                // break in the page.
                Section {
                    VocabStats(entries: entries)
                    if levels.count > 2 {
                        Picker("Level", selection: $level) {
                            ForEach(levels, id: \.self) { Text($0).tag($0) }
                        }
                        .pickerStyle(.segmented)
                        .padding(.bottom, 4)
                    }
                }
                .listRowInsets(EdgeInsets())
                .listRowBackground(Color.clear)
                .listRowSeparator(.hidden)

                if let error {
                    Section {
                        Text(error).font(.footnote).foregroundStyle(Color.mError)
                    }
                }

                ForEach(VocabStatus.allCases, id: \.rawValue) { status in
                    let words = filtered.filter { $0.status == status.rawValue }
                    if !words.isEmpty {
                        Section {
                            ForEach(words) { entry in
                                NavigationLink {
                                    VocabDetailView(entry: entry)
                                } label: {
                                    VocabRow(entry: entry)
                                }
                            }
                        } header: {
                            Text("\(status.title) · \(words.count)")
                        }
                    }
                }

                if entries.isEmpty && error == nil {
                    Section { Text("Loading…").foregroundStyle(Color.mTextMuted) }
                } else if filtered.isEmpty {
                    Section {
                        Text("No words match.").foregroundStyle(Color.mTextMuted)
                    }
                }
            }
            .listSectionSpacing(.compact)
            .creamBackground()
            .searchable(text: $query, prompt: "Search words")
            .navigationTitle("Vocabulary")
            .toolbar {
                ToolbarItem(placement: .primaryAction) {
                    Button(due.isEmpty ? "Practise" : "Review \(due.count)") {
                        startReview()
                    }
                    .disabled(!entries.contains(where: \.isPractisable))
                }
            }
            .fullScreenCover(item: $reviewing) { queue in
                VocabReviewView(bridge: bridge, queue: queue) {
                    reviewing = nil
                    load()
                }
            }
        }
        .task { load() }
    }

    private func load() {
        do { entries = try bridge.vocabulary() } catch { self.error = "\(error)" }
    }

    /// Due cards when there are any; otherwise a shuffled sample of what
    /// the pack has, so "practise more" is never a dead end.
    private func startReview() {
        let pool = due.isEmpty
            ? entries.filter(\.isPractisable).shuffled()
            : due
        guard !pool.isEmpty else { return }
        reviewing = VocabQueue(entries: Array(pool.prefix(20)))
    }
}

enum VocabStatus: String, CaseIterable {
    /// Order is the order the sections appear in: what needs doing, then
    /// what a lesson just handed over, then progress, then the rest.
    case due, discovered, learning, known, new

    var title: String {
        switch self {
        case .due: "Due now"
        case .discovered: "Met in a lesson"
        case .learning: "Learning"
        case .known: "Known"
        case .new: "Not started"
        }
    }

    var color: Color {
        switch self {
        case .due: .mTerracotta
        case .discovered: .mBlue
        case .learning: .mGold
        case .known: .mSage
        case .new: .mBorder
        }
    }

    static func color(for raw: String) -> Color {
        VocabStatus(rawValue: raw)?.color ?? .mBorder
    }
}

/// The counts the web page led with: how much there is, and how much of it
/// is waiting.
private struct VocabStats: View {
    let entries: [VocabEntry]

    private func count(_ status: VocabStatus) -> Int {
        entries.filter { $0.status == status.rawValue }.count
    }

    var body: some View {
        HStack(spacing: 0) {
            stat(entries.count, "words", .mCharcoal)
            stat(count(.due), "due", .mTerracotta)
            stat(count(.discovered), "met", .mBlue)
            stat(count(.learning), "learning", .mGold)
            stat(count(.known), "known", .mSage)
        }
        .card(padding: 16)
        .padding(.vertical, 6)
    }

    private func stat(_ value: Int, _ label: String, _ color: Color) -> some View {
        VStack(spacing: 2) {
            Text("\(value)")
                .font(.title3.weight(.semibold))
                .fontDesign(.serif)
                .foregroundStyle(color)
            Text(label)
                .font(.caption2)
                .foregroundStyle(Color.mTextMuted)
        }
        .frame(maxWidth: .infinity)
    }
}

private struct VocabRow: View {
    let entry: VocabEntry

    var body: some View {
        HStack(spacing: 10) {
            Circle()
                .fill(VocabStatus.color(for: entry.status))
                .frame(width: 7, height: 7)
            VStack(alignment: .leading, spacing: 2) {
                Text(entry.lemma)
                    .font(.callout.weight(.medium))
                    .foregroundStyle(Color.mCharcoal)
                Text(entry.gloss)
                    .font(.caption)
                    .foregroundStyle(Color.mTextMuted)
                    .lineLimit(1)
            }
            Spacer(minLength: 8)
            Badge(text: entry.cefrLevel)
        }
        .padding(.vertical, 2)
    }
}

struct VocabDetailView: View {
    let entry: VocabEntry

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                VStack(alignment: .leading, spacing: 10) {
                    Text(entry.lemma)
                        .font(.system(.largeTitle, design: .serif).weight(.semibold))
                        .foregroundStyle(Color.mCharcoal)
                    Text([entry.pos, entry.cefrLevel].filter { !$0.isEmpty }
                        .joined(separator: " · "))
                        .font(.caption)
                        .foregroundStyle(Color.mTextMuted)
                    Divider()
                    Text(entry.back ?? entry.gloss)
                        .font(.title3)
                        .foregroundStyle(Color.mText)
                    if let example = entry.example {
                        Text(example)
                            .font(.callout).italic()
                            .foregroundStyle(Color.mText)
                    }
                    if let gloss = entry.exampleGloss {
                        Text(gloss)
                            .font(.footnote)
                            .foregroundStyle(Color.mTextMuted)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .card()

                VStack(alignment: .leading, spacing: 8) {
                    Eyebrow(text: "Review schedule")
                    Text(scheduleLine)
                        .font(.callout)
                        .foregroundStyle(Color.mText)
                    if entry.reviews > 0 {
                        Text(
                            "\(entry.reviews) review"
                                + (entry.reviews == 1 ? "" : "s")
                                + String(format: " · ease %.2f", entry.easeFactor)
                        )
                        .font(.caption)
                        .foregroundStyle(Color.mTextMuted)
                    }
                    if !entry.isPractisable {
                        Text("The pack has no card for this word yet — it appears "
                            + "in readings and drills, but can't be reviewed on "
                            + "its own.")
                            .font(.caption)
                            .foregroundStyle(Color.mTextMuted)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .card()
            }
            .padding(20)
        }
        .background(Color.mCream)
        .navigationTitle(entry.lemma)
        .navigationBarTitleDisplayMode(.inline)
    }

    private var scheduleLine: String {
        guard let days = entry.dueInDays else { return "You haven't met this word yet." }
        // A word met in a lesson is due from that day, so it would otherwise
        // read as overdue before it was ever practised.
        if entry.reviews == 0 {
            guard let seen = entry.firstSeenDaysAgo else { return "Ready to review." }
            let when = seen == 0 ? "today" : "\(seen) day\(seen == 1 ? "" : "s") ago"
            return "Met in a lesson \(when) — ready to review."
        }
        if days < 0 { return "Overdue by \(-days) day\(-days == 1 ? "" : "s")." }
        if days == 0 { return "Due today." }
        return "Due in \(days) day\(days == 1 ? "" : "s")."
    }
}

// MARK: - Review

/// `fullScreenCover(item:)` needs an Identifiable, and the queue is what
/// identifies the run — a second tap on Review should start a new one.
struct VocabQueue: Identifiable {
    let entries: [VocabEntry]
    var id: String { entries.map(\.lemma).joined(separator: ",") }
}

struct VocabReviewView: View {
    let bridge: CoreBridge
    let queue: VocabQueue
    let onDone: () -> Void

    @State private var index = 0
    @State private var revealed = false

    var body: some View {
        NavigationStack {
            VStack(spacing: 20) {
                if index < queue.entries.count {
                    let entry = queue.entries[index]
                    Spacer()
                    VStack(spacing: 14) {
                        Eyebrow(text: "\(index + 1) of \(queue.entries.count)")
                        VocabCardFace(
                            front: entry.front ?? entry.lemma,
                            back: entry.back ?? entry.gloss,
                            example: entry.example,
                            exampleGloss: entry.exampleGloss,
                            revealed: revealed)
                    }
                    .frame(maxWidth: .infinity)
                    .card(padding: 28)
                    Spacer()

                    if revealed {
                        SrsRatingButtons { grade($0, entry: entry) }
                    } else {
                        Button {
                            revealed = true
                        } label: {
                            Text("Mostra").frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.borderedProminent)
                        .controlSize(.large)
                    }
                } else {
                    ContentUnavailableView(
                        "Review complete",
                        systemImage: "checkmark.circle",
                        description: Text(
                            "\(queue.entries.count) word"
                                + (queue.entries.count == 1 ? "" : "s")
                                + " rescheduled."))
                    Button {
                        onDone()
                    } label: {
                        Text("Fine").frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
                }
            }
            .padding(20)
            .background(Color.mCream)
            .navigationTitle("Review")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Chiudi") { onDone() }
                }
            }
        }
    }

    private func grade(_ rating: UInt8, entry: VocabEntry) {
        if let itemId = entry.itemId {
            try? bridge.recordVocabReview(
                itemId: itemId, srsRating: rating,
                evidenceJson: bridge.evidence(for: itemId))
        }
        revealed = false
        index += 1
    }
}

// MARK: - Shared with the session's vocab activity

/// The two faces of a card. Front always; the rest once revealed.
struct VocabCardFace: View {
    let front: String
    let back: String
    let example: String?
    let exampleGloss: String?
    let revealed: Bool

    var body: some View {
        VStack(spacing: 14) {
            Text(front)
                .font(.system(.largeTitle, design: .serif).weight(.semibold))
                .foregroundStyle(Color.mCharcoal)
                .multilineTextAlignment(.center)

            if revealed {
                Divider().padding(.vertical, 4)
                Text(back)
                    .font(.title3.weight(.semibold))
                    .foregroundStyle(Color.mText)
                    .multilineTextAlignment(.center)
                if let example {
                    Text(example)
                        .font(.callout).italic()
                        .foregroundStyle(Color.mText)
                        .multilineTextAlignment(.center)
                }
                if let exampleGloss {
                    Text(exampleGloss)
                        .font(.footnote)
                        .foregroundStyle(Color.mTextMuted)
                        .multilineTextAlignment(.center)
                }
            }
        }
    }
}

/// The SM-2 grades the fold understands: below 3 resets the interval,
/// 3 and up advances it.
struct SrsRatingButtons: View {
    let onGrade: (UInt8) -> Void

    var body: some View {
        VStack(spacing: 8) {
            Eyebrow(text: "How well did you know it?")
            HStack(spacing: 8) {
                Button("Di nuovo") { onGrade(1) }
                    .buttonStyle(.bordered).tint(.mTerracotta)
                Button("Difficile") { onGrade(3) }
                    .buttonStyle(.bordered).tint(.mGold)
                Button("Facile") { onGrade(5) }
                    .buttonStyle(.bordered).tint(.mSage)
            }
            .controlSize(.large)
        }
    }
}

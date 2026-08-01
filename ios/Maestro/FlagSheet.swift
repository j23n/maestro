// ⚠️ UNTESTED SCAFFOLD.
//
// Reporting a broken item. One sentence is the whole interaction: the
// learner is mid-lesson and the useful signal is "this one is wrong, and
// here's why in my words" — anything longer gets abandoned.
//
// The report is an event in the same append-only log as everything else,
// so it works offline and survives. It never reaches the network; it
// leaves the device only when the learner exports it from Progress.

import SwiftUI

/// `sheet(item:)` needs an Identifiable, and a bare item id isn't one.
struct FlagTarget: Identifiable {
    let id: String
    var seed: String = ""
}

struct FlagSheet: View {
    let bridge: CoreBridge
    /// The item being reported. Shown, because "which one was that?" is
    /// the first thing anyone reading the report will ask.
    let itemId: String
    /// Prefilled when we already know what went wrong — a rejected answer
    /// gets the learner most of the way to a useful sentence.
    var seed: String = ""

    @Environment(\.dismiss) private var dismiss
    @State private var note = ""
    @State private var error: String?
    @FocusState private var focused: Bool

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField(
                        "What's wrong with it?", text: $note,
                        axis: .vertical
                    )
                    .lineLimit(3 ... 6)
                    .focused($focused)
                } header: {
                    Text("Report a problem")
                } footer: {
                    Text(
                        "Goes into your own log. Nothing is sent anywhere — "
                            + "you can export your reports from the Progress tab."
                    )
                }

                Section {
                    Text(itemId)
                        .font(.caption.monospaced())
                        .foregroundStyle(.secondary)
                } header: {
                    Text("Item")
                }

                if let error {
                    Section { Text(error).foregroundStyle(.red).font(.callout) }
                }
            }
            .navigationTitle("Report a problem")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Send") { send() }
                        .disabled(note.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
            .onAppear {
                if note.isEmpty { note = seed }
                focused = true
            }
        }
    }

    private func send() {
        do {
            try bridge.flagItem(
                itemId: itemId,
                note: note.trimmingCharacters(in: .whitespacesAndNewlines))
            dismiss()
        } catch {
            self.error = "Couldn't save the report: \(error)"
        }
    }
}

/// The reports raised so far, and the way they get to whoever fixes the
/// content. Lives in the Progress tab because that's where "state of my
/// account" already is.
struct ReportedProblemsView: View {
    let bridge: CoreBridge

    @State private var flags: [Flag] = []
    @State private var exported: URL?
    @State private var error: String?

    var body: some View {
        List {
            if flags.isEmpty {
                ContentUnavailableView(
                    "No reports yet",
                    systemImage: "checkmark.circle",
                    description: Text(
                        "Tap “Report a problem” on any activity that looks wrong."))
            } else {
                Section {
                    ForEach(flags) { flag in
                        VStack(alignment: .leading, spacing: 4) {
                            Text(flag.note ?? "—")
                            Text(flag.itemId)
                                .font(.caption.monospaced())
                                .foregroundStyle(.secondary)
                            if let version = flag.packVersion {
                                Text("pack \(version)")
                                    .font(.caption2.monospaced())
                                    .foregroundStyle(.tertiary)
                            }
                        }
                        .padding(.vertical, 2)
                    }
                } footer: {
                    Text(
                        "Exporting writes a small file containing only these "
                            + "reports — not your learning history.")
                }

                Section {
                    if let exported {
                        ShareLink(item: exported) {
                            Label("Export reports", systemImage: "square.and.arrow.up")
                        }
                    } else {
                        Button {
                            prepareExport()
                        } label: {
                            Label("Prepare export", systemImage: "square.and.arrow.up")
                        }
                    }
                }
            }
            if let error {
                Section { Text(error).foregroundStyle(.red).font(.callout) }
            }
        }
        .navigationTitle("Reported problems")
        .task { load() }
    }

    private func load() {
        do { flags = try bridge.flags() } catch { self.error = "\(error)" }
    }

    private func prepareExport() {
        do { exported = try bridge.exportFlagsFile() } catch { self.error = "\(error)" }
    }
}

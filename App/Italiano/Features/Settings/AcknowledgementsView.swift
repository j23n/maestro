import SwiftUI

/// Settings → Acknowledgements (task M3.8, docs/13 § Licences): every credit, with the full OFL texts of the fonts
/// and the MIT notice of GRDB behind "Show licence".
struct AcknowledgementsView: View {
    let onDone: () -> Void
    @State private var expanded: Set<String> = []

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text("Acknowledgements").dsFont(Tokens.TypeScale.screenTitle).foregroundStyle(Color.ds.ink)
                    .accessibilityAddTraits(.isHeader)
                Spacer()
                Button("Done", action: onDone)
                    .buttonStyle(.dsSecondarySmall)
                    .keyboardShortcut(.cancelAction)
                    .accessibilityIdentifier("acknowledgements.done")
            }
            .padding(Tokens.Space.xxl)
            ScrollView {
                VStack(alignment: .leading, spacing: Tokens.Space.xxl) {
                    Text(Acknowledgements.intro).dsFont(Tokens.TypeScale.uiBody).foregroundStyle(Color.ds.secondary)
                    ForEach(Array(Acknowledgements.all.enumerated()), id: \.element.id) { n, entry in
                        entryView(entry, n: n)
                    }
                }
                .readableColumn()
                .padding(.bottom, Tokens.Space.xxl)
            }
            .accessibilityIdentifier("acknowledgements.list")
        }
        .background(Color.ds.background)
    }

    private func entryView(_ entry: Acknowledgement, n: Int) -> some View {
        VStack(alignment: .leading, spacing: Tokens.Space.s) {
            Text(entry.name).dsFont(Tokens.TypeScale.rowTitle).foregroundStyle(Color.ds.ink)
                .accessibilityAddTraits(.isHeader)
            Text(entry.credit).dsFont(Tokens.TypeScale.uiBody).foregroundStyle(Color.ds.ink)
                .fixedSize(horizontal: false, vertical: true)
            Text(entry.licence).dsFont(Tokens.TypeScale.uiCallout).foregroundStyle(Color.ds.secondary)
            if let link = entry.url.flatMap(URL.init(string:)) {
                Link(link.absoluteString, destination: link)
                    .dsFont(Tokens.TypeScale.uiCallout)
                    .accessibilityIdentifier("acknowledgements.link.\(n)")
            }
            if let text = Acknowledgements.licenceText(for: entry, in: Acknowledgements.bundleDirectories()) {
                Button(expanded.contains(entry.id) ? "Hide licence" : "Show licence") {
                    if expanded.contains(entry.id) { expanded.remove(entry.id) } else { expanded.insert(entry.id) }
                }
                .buttonStyle(.dsTextLink)
                .accessibilityIdentifier("acknowledgements.licence.\(n)")
                if expanded.contains(entry.id) {
                    Text(text).font(.footnote.monospaced()).foregroundStyle(Color.ds.secondary)
                        .textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                        .accessibilityIdentifier("acknowledgements.text.\(n)")
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

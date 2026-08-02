import SwiftUI

@main
struct MaestroApp: App {
    var body: some Scene {
        WindowGroup {
            RootView()
                .tint(.mTerracotta)
                // The palette is the warm light one from the web app; there
                // is no dark counterpart yet, and letting the system invert
                // it would put white system text on cream cards.
                .preferredColorScheme(.light)
        }
    }
}

struct RootView: View {
    @State private var bridge: CoreBridge?
    @State private var feedback: FeedbackService?
    @State private var error: String?

    var body: some View {
        Group {
            if let bridge, let feedback {
                TabView {
                    LearnPathView(bridge: bridge, feedback: feedback)
                        .tabItem { Label("Learn", systemImage: "book") }
                    VocabularyScreen(bridge: bridge)
                        .tabItem { Label("Vocabulary", systemImage: "textformat.abc") }
                    ProgressScreen(bridge: bridge)
                        .tabItem { Label("Progress", systemImage: "chart.bar") }
                }
            } else if let error {
                ContentUnavailableView(
                    "Couldn't open the content pack",
                    systemImage: "exclamationmark.triangle",
                    description: Text(error))
            } else {
                ProgressView("Opening…")
            }
        }
        .task {
            do {
                let opened = try CoreBridge()
                bridge = opened
                // No API key by default: the MVP is offline, so the only
                // tier that can run is on-device, and only if its eval
                // gate is open.
                feedback = FeedbackService(bridge: opened)
            } catch {
                self.error = "\(error)"
            }
        }
    }
}

extension SessionPlan: Hashable, Identifiable {
    var id: String { archetype + activities.map(\.itemId).joined() }
    static func == (l: SessionPlan, r: SessionPlan) -> Bool { l.id == r.id }
    func hash(into hasher: inout Hasher) { hasher.combine(id) }
}

// ⚠️ UNTESTED SCAFFOLD — see ios/README.md for what remains on the Mac.

import SwiftUI

@main
struct MaestroApp: App {
    var body: some Scene {
        WindowGroup {
            RootView()
        }
    }
}

struct RootView: View {
    @State private var bridge: CoreBridge?
    @State private var error: String?

    var body: some View {
        Group {
            if let bridge {
                TabView {
                    SessionLauncherView(bridge: bridge)
                        .tabItem { Label("Learn", systemImage: "book") }
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
            do { bridge = try CoreBridge() } catch { self.error = "\(error)" }
        }
    }
}

struct SessionLauncherView: View {
    let bridge: CoreBridge
    @State private var plan: SessionPlan?
    @State private var error: String?

    var body: some View {
        NavigationStack {
            VStack(spacing: 24) {
                Button("Start session (15 min)") { start(minutes: 15) }
                    .buttonStyle(.borderedProminent)
                Button("Quick drills (5 min)") { start(minutes: 5) }
                if let error {
                    Text(error)
                        .font(.caption).foregroundStyle(.red)
                        .multilineTextAlignment(.center).padding(.horizontal)
                }
            }
            .navigationTitle("Maestro")
            .navigationDestination(item: $plan) { plan in
                SessionView(bridge: bridge, plan: plan)
            }
        }
    }

    private func start(minutes: UInt32) {
        do {
            error = nil
            let composed = try bridge.composeSession(minutes: minutes)
            // An empty plan means no eligible content at all; pushing an
            // empty session would look like the app doing nothing.
            guard !composed.activities.isEmpty else {
                error = "No activities available — the pack has no content for "
                    + "this scenario yet."
                return
            }
            plan = composed
        } catch {
            self.error = "Couldn't build a session: \(error)"
        }
    }
}

extension SessionPlan: Hashable, Identifiable {
    var id: String { archetype + activities.map(\.itemId).joined() }
    static func == (l: SessionPlan, r: SessionPlan) -> Bool { l.id == r.id }
    func hash(into hasher: inout Hasher) { hasher.combine(id) }
}

// ⚠️ UNTESTED SCAFFOLD — see ios/README.md for what remains on the Mac.

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
                    SessionLauncherView(bridge: bridge, feedback: feedback)
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

struct SessionLauncherView: View {
    let bridge: CoreBridge
    let feedback: FeedbackService
    @State private var plan: SessionPlan?
    @State private var error: String?
    @State private var level = "A0"

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    VStack(alignment: .leading, spacing: 14) {
                        Eyebrow(text: "Today")
                        Text("Continue where you left off")
                            .font(.title3.weight(.semibold))
                            .fontDesign(.serif)
                            .foregroundStyle(Color.mCharcoal)
                        Text(
                            "A guided run through one scenario — a grammar card "
                                + "first, then drills, reading and speaking."
                        )
                        .font(.subheadline)
                        .foregroundStyle(Color.mTextMuted)

                        Button {
                            start(minutes: 15)
                        } label: {
                            Text("Start session · 15 min").frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.borderedProminent)
                        .controlSize(.large)

                        Button {
                            start(minutes: 5)
                        } label: {
                            Text("Quick drills · 5 min").frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.bordered)
                        .controlSize(.large)
                        .tint(.mTextMuted)
                    }
                    .card()

                    if let error {
                        Text(error)
                            .font(.footnote)
                            .foregroundStyle(Color.mError)
                            .padding(12)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(Color.mErrorBg, in: RoundedRectangle(cornerRadius: 8))
                    }
                }
                .padding(20)
            }
            .background(Color.mCream)
            .navigationTitle("Maestro")
            .navigationDestination(item: $plan) { plan in
                SessionView(
                    bridge: bridge, feedback: feedback, level: level, plan: plan)
            }
        }
    }

    private func start(minutes: UInt32) {
        do {
            error = nil
            // Prompts adapt to level; a stale one only makes feedback
            // slightly off-pitch, so a failure here isn't worth blocking on.
            level = (try? bridge.progress().cefr.level) ?? level
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

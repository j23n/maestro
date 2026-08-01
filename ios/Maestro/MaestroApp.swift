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

struct SessionLauncherView: View {
    let bridge: CoreBridge
    let feedback: FeedbackService
    /// The pushed session, as a one-element stack rather than a bound
    /// optional. Starting the next lesson from a recap replaces that
    /// element; assigning a new value to a presented `item:` binding
    /// leaves the finished session on screen.
    @State private var path: [SessionPlan] = []
    @State private var brief: LessonBrief?
    @State private var error: String?
    @State private var level = "A0"

    var body: some View {
        NavigationStack(path: $path) {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    LessonSplash(brief: brief)

                    VStack(spacing: 10) {
                        Button {
                            start(minutes: 15)
                        } label: {
                            Text("Start lesson · 15 min").frame(maxWidth: .infinity)
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
            .navigationDestination(for: SessionPlan.self) { plan in
                SessionView(
                    bridge: bridge, feedback: feedback, level: level, plan: plan,
                    onNextLesson: { start(minutes: 15) }
                )
                // Without a fresh identity the next lesson would inherit
                // the last one's progress.
                .id(plan.id)
            }
        }
        // Refreshed on return, not just at launch: finishing a lesson is
        // what changes which one comes next.
        .task(id: path.first?.id) { brief = try? bridge.nextLesson() }
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
            // Replace rather than push: lessons are siblings, and stacking
            // them would make Back walk the whole history.
            path = [composed]
        } catch {
            self.error = "Couldn't build a session: \(error)"
        }
    }
}

/// What the next lesson is about, ahead of starting it.
///
/// The web app opened every scenario with its scene: where you are, what
/// you're about to do, why it's worth knowing. "Continue where you left
/// off" said none of that, and said it identically every time.
struct LessonSplash: View {
    let brief: LessonBrief?

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            if let brief {
                HStack {
                    Eyebrow(text: brief.isFirstVisit ? "Next lesson" : "Again")
                    Spacer()
                    Badge(text: brief.cefrLevel)
                }
                Text(brief.label)
                    .font(.title3.weight(.semibold))
                    .fontDesign(.serif)
                    .foregroundStyle(Color.mCharcoal)
                if !brief.description.isEmpty {
                    Text(brief.description)
                        .font(.subheadline)
                        .foregroundStyle(Color.mTextMuted)
                        .fixedSize(horizontal: false, vertical: true)
                }
                // The scene is the hook and it only lands once; a replay
                // gets the plainer overview instead.
                if brief.isFirstVisit, !brief.sceneSetting.isEmpty {
                    Text(brief.sceneSetting)
                        .font(.callout)
                        .italic()
                        .foregroundStyle(Color.mText)
                        .lineSpacing(3)
                        .fixedSize(horizontal: false, vertical: true)
                } else if !brief.overview.isEmpty {
                    Text(brief.overview)
                        .font(.callout)
                        .foregroundStyle(Color.mText)
                        .lineSpacing(3)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if !brief.grammar.isEmpty {
                    Divider().overlay(Color.mBorder)
                    Text("You'll practise")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(Color.mTextMuted)
                    Text(brief.grammar.map(\.label).joined(separator: " · "))
                        .font(.footnote)
                        .foregroundStyle(Color.mText)
                        .fixedSize(horizontal: false, vertical: true)
                }
            } else {
                Eyebrow(text: "Today")
                Text("Ready when you are")
                    .font(.title3.weight(.semibold))
                    .fontDesign(.serif)
                    .foregroundStyle(Color.mCharcoal)
                Text(
                    "A guided run through one scenario — a grammar card first, "
                        + "then drills, reading and speaking."
                )
                .font(.subheadline)
                .foregroundStyle(Color.mTextMuted)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .card()
    }
}

extension SessionPlan: Hashable, Identifiable {
    var id: String { archetype + activities.map(\.itemId).joined() }
    static func == (l: SessionPlan, r: SessionPlan) -> Bool { l.id == r.id }
    func hash(into hasher: inout Hasher) { hasher.combine(id) }
}

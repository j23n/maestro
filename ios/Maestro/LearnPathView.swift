// The Learn tab: every lesson in the pack as a vertical path — CEFR
// section headings, one unit per scenario, a circular node per lesson.
// Completed nodes wear a checkmark, everything not yet played sits
// grayed, and the startable lesson carries a terracotta ring. Tapping
// any node opens its intro screen; only a `next` lesson can start (the
// composer always plays a scenario's next unplayed depth, so nothing
// else is honestly startable).

import SwiftUI
import UIKit

struct LearnPathView: View {
    let bridge: CoreBridge
    let feedback: FeedbackService
    /// Mixed stack: a LearnLesson pushes an intro screen, a SessionPlan
    /// a session. Starting a lesson replaces the whole stack — lessons
    /// are siblings, and stacking them would make Back walk history.
    @State private var nav = NavigationPath()
    @State private var path: LearnPath?
    @State private var error: String?
    @State private var level = "A0"

    var body: some View {
        NavigationStack(path: $nav) {
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    if let error {
                        Text(error)
                            .font(.footnote)
                            .foregroundStyle(Color.mError)
                            .padding(12)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(Color.mErrorBg, in: RoundedRectangle(cornerRadius: 8))
                    }
                    if let path {
                        // Sections are consecutive runs, so the offset is
                        // the identity — the same level can head two runs.
                        ForEach(Array(path.sections.enumerated()), id: \.offset) { _, section in
                            LearnSectionView(bridge: bridge, section: section)
                        }
                    } else {
                        ProgressView().frame(maxWidth: .infinity)
                    }
                }
                .padding(20)
            }
            .background(Color.mCream)
            .navigationTitle("Maestro")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        start(minutes: 5)
                    } label: {
                        Label("Quick drills", systemImage: "bolt")
                    }
                }
            }
            .navigationDestination(for: LearnLesson.self) { lesson in
                LessonIntroView(bridge: bridge, lesson: lesson) {
                    start(minutes: 15, scenarioId: lesson.scenarioId)
                }
            }
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
        // Refreshed on every navigation change, not just at launch:
        // finishing a session is what moves the path along.
        .task(id: nav.count) { path = try? bridge.learnPath() }
    }

    private func start(minutes: UInt32, scenarioId: String? = nil) {
        do {
            error = nil
            // Prompts adapt to level; a stale one only makes feedback
            // slightly off-pitch, so a failure here isn't worth blocking on.
            level = (try? bridge.progress().cefr.level) ?? level
            let composed = try bridge.composeSession(minutes: minutes, scenarioId: scenarioId)
            // An empty plan means no eligible content at all; pushing an
            // empty session would look like the app doing nothing.
            guard !composed.activities.isEmpty else {
                error = "No activities available — the pack has no content for "
                    + "this scenario yet."
                return
            }
            nav = NavigationPath([composed])
        } catch {
            self.error = "Couldn't build a session: \(error)"
        }
    }
}

private struct LearnSectionView: View {
    let bridge: CoreBridge
    let section: LearnSection

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Badge(text: section.cefrLevel)
            ForEach(section.units) { unit in
                LearnUnitView(bridge: bridge, unit: unit)
            }
        }
    }
}

/// One scenario on the path: its art and name heading its lessons.
private struct LearnUnitView: View {
    let bridge: CoreBridge
    let unit: LearnUnit

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 10) {
                if let art = bridge.media(at: unit.image).flatMap(UIImage.init(data:)) {
                    Image(uiImage: art)
                        .resizable()
                        .scaledToFill()
                        .frame(width: 28, height: 28)
                        .clipShape(RoundedRectangle(cornerRadius: 6))
                }
                Text(unit.label)
                    .font(.headline)
                    .fontDesign(.serif)
                    .foregroundStyle(Color.mCharcoal)
            }
            VStack(spacing: 14) {
                ForEach(unit.lessons) { lesson in
                    NavigationLink(value: lesson) {
                        LessonNodeView(bridge: bridge, lesson: lesson)
                    }
                    .buttonStyle(.plain)
                }
            }
            .frame(maxWidth: .infinity)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .card()
    }
}

/// One circular node: the lesson's drawing, grayed until played, checked
/// once done, ringed while it is the one to play.
private struct LessonNodeView: View {
    let bridge: CoreBridge
    let lesson: LearnLesson

    var body: some View {
        VStack(spacing: 6) {
            ZStack(alignment: .bottomTrailing) {
                Group {
                    if let art = bridge.media(at: lesson.image).flatMap(UIImage.init(data:)) {
                        Image(uiImage: art)
                            .resizable()
                            .scaledToFill()
                    } else {
                        Image(systemName: "book.closed")
                            .font(.title3)
                            .foregroundStyle(Color.mTextMuted)
                            .frame(maxWidth: .infinity, maxHeight: .infinity)
                            .background(Color.mSurface)
                    }
                }
                .frame(width: 72, height: 72)
                .clipShape(Circle())
                .grayscale(lesson.state == .completed ? 0 : 1)
                .opacity(lesson.state == .completed ? 1 : 0.5)
                .overlay(
                    Circle().strokeBorder(
                        lesson.state == .next ? Color.mTerracotta : Color.mBorder,
                        lineWidth: lesson.state == .next ? 3 : 1))

                if lesson.state == .completed {
                    Image(systemName: "checkmark.circle.fill")
                        .font(.title3)
                        .foregroundStyle(Color.mSuccess)
                        .background(Circle().fill(.white))
                }
            }
            Text(lesson.label)
                .font(.footnote)
                .foregroundStyle(lesson.state == .locked ? Color.mTextMuted : Color.mText)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity)
    }
}

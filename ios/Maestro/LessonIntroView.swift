// ⚠️ UNTESTED SCAFFOLD.
//
// A lesson's intro screen: the drawing, the goal in plain words, the
// summary, and chips for what is new (Nuovo), what comes back (Ripasso),
// and the can-dos it proves (Obiettivi). Viewable for every lesson;
// Start is enabled only for the `next` one — the composer plays a
// scenario's next unplayed depth and nothing else, so anything further
// along would silently play the wrong lesson.

import SwiftUI
import UIKit

struct LessonIntroView: View {
    let bridge: CoreBridge
    let lesson: LearnLesson
    /// Composes and pushes the session; LearnPathView owns the stack.
    let onStart: () -> Void

    @State private var detail: LessonDetail?
    @State private var loadError: String?

    /// The detail's state once loaded — the path's copy tides over the
    /// first frame.
    private var state: LessonState { detail?.state ?? lesson.state }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                if let detail {
                    if let art = bridge.media(at: detail.image).flatMap(UIImage.init(data:)) {
                        Image(uiImage: art)
                            .resizable()
                            .scaledToFill()
                            .frame(maxWidth: .infinity)
                            .frame(height: 200)
                            .clipShape(RoundedRectangle(cornerRadius: 10))
                    }
                    introCard(detail)
                } else if let loadError {
                    Text(loadError)
                        .font(.footnote)
                        .foregroundStyle(Color.mError)
                        .padding(12)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(Color.mErrorBg, in: RoundedRectangle(cornerRadius: 8))
                } else {
                    ProgressView().frame(maxWidth: .infinity)
                }
            }
            .padding(20)
        }
        .background(Color.mCream)
        .navigationTitle(lesson.label)
        .navigationBarTitleDisplayMode(.inline)
        .safeAreaInset(edge: .bottom) { startButton }
        .task {
            do { detail = try bridge.lessonDetail(lessonId: lesson.lessonId) }
            catch { loadError = "\(error)" }
        }
    }

    private func introCard(_ detail: LessonDetail) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Eyebrow(text: detail.scenarioLabel)
                Spacer()
                Badge(text: detail.cefrLevel)
            }
            Text(detail.label)
                .font(.title3.weight(.semibold))
                .fontDesign(.serif)
                .foregroundStyle(Color.mCharcoal)
            // The goal leads: what you'll walk out able to do
            // (docs/plans/07 §7).
            if !detail.goal.isEmpty {
                Text(detail.goal)
                    .font(.callout)
                    .italic()
                    .foregroundStyle(Color.mText)
                    .lineSpacing(3)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if !detail.summary.isEmpty {
                Text(detail.summary)
                    .font(.subheadline)
                    .foregroundStyle(Color.mTextMuted)
                    .fixedSize(horizontal: false, vertical: true)
            }
            // Vocabulary chips show the lemma itself — the Italian is the
            // point; grammar and functions show their spec labels. A stub
            // lesson declares nothing and degrades to the summary above.
            ChipSection(
                title: "Nuovo", tint: Color.mTerracotta,
                labels: detail.introduces.grammar.map(\.label)
                    + detail.introduces.functions.map(\.label)
                    + detail.introduces.vocab.map(\.id))
            ChipSection(
                title: "Ripasso", tint: Color.mSage,
                labels: detail.revisits.grammar.map(\.label)
                    + detail.revisits.functions.map(\.label)
                    + detail.revisits.vocab.map(\.id))
            ChipSection(
                title: "Obiettivi", tint: Color.mGold,
                labels: detail.capstones.map(\.label))
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .card()
    }

    @ViewBuilder
    private var startButton: some View {
        Group {
            switch state {
            case .next:
                Button(action: onStart) {
                    Text("Inizia la lezione").frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
            case .completed:
                Button {} label: {
                    Text("Completata").frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
                .disabled(true)
            case .locked:
                Button {} label: {
                    Text("Si sblocca più avanti").frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
                .disabled(true)
            }
        }
        .controlSize(.large)
        .padding(.horizontal, 20)
        .padding(.bottom, 8)
        .background(Color.mCream)
    }
}

/// A titled row of wrapping pills; hidden when there is nothing to list.
private struct ChipSection: View {
    let title: String
    let tint: Color
    let labels: [String]

    var body: some View {
        if !labels.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                Divider().overlay(Color.mBorder)
                Text(title.uppercased())
                    .font(.caption.weight(.semibold))
                    .tracking(0.8)
                    .foregroundStyle(tint)
                FlowLayout(spacing: 6) {
                    ForEach(labels, id: \.self) { label in
                        Text(label)
                            .font(.caption)
                            .foregroundStyle(tint)
                            .padding(.horizontal, 8)
                            .padding(.vertical, 3)
                            .background(tint.opacity(0.12), in: Capsule())
                    }
                }
            }
        }
    }
}

/// Minimal left-aligned wrap for the chips — SwiftUI has no built-in one.
private struct FlowLayout: Layout {
    var spacing: CGFloat = 6

    func sizeThatFits(
        proposal: ProposedViewSize, subviews: Subviews, cache: inout ()
    ) -> CGSize {
        let width = proposal.width ?? .infinity
        var x: CGFloat = 0, y: CGFloat = 0, rowHeight: CGFloat = 0
        for view in subviews {
            let size = fitted(view, in: width)
            if x > 0, x + size.width > width {
                x = 0
                y += rowHeight + spacing
                rowHeight = 0
            }
            x += size.width + spacing
            rowHeight = max(rowHeight, size.height)
        }
        return CGSize(width: width == .infinity ? x : width, height: y + rowHeight)
    }

    func placeSubviews(
        in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews,
        cache: inout ()
    ) {
        var x = bounds.minX, y = bounds.minY, rowHeight: CGFloat = 0
        for view in subviews {
            let size = fitted(view, in: bounds.width)
            if x > bounds.minX, x + size.width > bounds.maxX {
                x = bounds.minX
                y += rowHeight + spacing
                rowHeight = 0
            }
            view.place(
                at: CGPoint(x: x, y: y),
                proposal: ProposedViewSize(width: size.width, height: size.height))
            x += size.width + spacing
            rowHeight = max(rowHeight, size.height)
        }
    }

    /// A chip wider than the row wraps its text instead of overflowing.
    private func fitted(_ view: LayoutSubview, in width: CGFloat) -> CGSize {
        let ideal = view.sizeThatFits(.unspecified)
        guard width.isFinite, ideal.width > width else { return ideal }
        return view.sizeThatFits(ProposedViewSize(width: width, height: nil))
    }
}

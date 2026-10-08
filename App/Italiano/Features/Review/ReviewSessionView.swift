import LearningCore
import SwiftUI

/// A review session (`LibroPhone.png`): close, progress with `n / total`, then the card through the same exercise
/// views as lessons; Continue moves on (re-queueing an Again card). At the end, the session-complete screen.
struct ReviewSessionView: View {
    let model: ReviewSessionModel
    let services: PlayerServices
    let complete: () -> CompleteContent
    let onClose: () -> Void
    let onDone: () -> Void
    var onNextStory: (() -> Void)?

    var body: some View {
        VStack(spacing: 0) {
            if model.isFinished {
                SessionCompleteView(content: complete(), onDone: onDone, onNextStory: onNextStory)
            } else {
                HStack(spacing: Tokens.Space.l) {
                    Button(action: onClose) {
                        Image(systemName: "xmark").font(.system(size: 20, weight: .medium))
                            .foregroundStyle(Color.ds.ink)
                            .frame(width: Tokens.Size.minTouch, height: Tokens.Size.minTouch)
                    }
                    .buttonStyle(.plain)
                    .keyboardShortcut(.cancelAction)
                    .accessibilityLabel(Text("Close"))
                    .accessibilityIdentifier("player.close")
                    DSProgressBar(value: model.progress).accessibilityIdentifier("player.progress")
                    Text(model.counter).dsFont(Tokens.TypeScale.uiCallout).foregroundStyle(Color.ds.secondary)
                        .monospacedDigit()
                }
                .padding(.horizontal, Tokens.Space.l)
                .padding(.vertical, Tokens.Space.s)
                Divider()
                if let host = model.host, let payload = model.payload {
                    ExerciseHostView(
                        host: host, payload: payload, bundle: Self.emptyBundle, services: services,
                        onContinue: { model.advance() }
                    )
                    .id(model.index)
                }
            }
        }
        .background(Color.ds.background)
    }

    /// Review cards bring their own payloads; a source text is shown only inside lessons.
    static let emptyBundle = LessonBundle(lessonID: "review", unitID: "u00", title: "Review", steps: [], exercises: [:])
}

/// Session complete (`Complete.png`): Moka cheering, **Bravo!**, the summary card, the week, Done and Read the next
/// story.
struct SessionCompleteView: View {
    let content: CompleteContent
    let onDone: () -> Void
    var onNextStory: (() -> Void)?

    var body: some View {
        ScrollView {
            VStack(spacing: Tokens.Space.xxl) {
                Mascot(pose: .cheer, size: 150, decorative: true)
                VStack(spacing: Tokens.Space.s) {
                    ItalianText("Bravo!", style: Tokens.TypeScale.celebration)
                        .accessibilityAddTraits(.isHeader)
                    Text("Today's review is done.").dsFont(Tokens.TypeScale.uiBody).foregroundStyle(Color.ds.secondary)
                }
                Card {
                    row("Remembered", content.remembered)
                    CardDivider()
                    row("New words met", content.newWords)
                    if let again = content.practiseAgain {
                        CardDivider()
                        HStack(alignment: .firstTextBaseline) {
                            Text("To practise again").dsFont(Tokens.TypeScale.uiBody).foregroundStyle(Color.ds.ink)
                            Spacer()
                            ItalianText(again, style: Tokens.TypeScale.translation, italic: true)
                                .multilineTextAlignment(.trailing)
                        }
                    }
                    if let next = content.nextReview {
                        CardDivider()
                        row("Next review", next)
                    }
                }
                .accessibilityIdentifier("complete.summary")
                Text(content.weekLine).dsFont(Tokens.TypeScale.uiBody).foregroundStyle(Color.ds.ink)
                    .padding(Tokens.Space.xl)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(RoundedRectangle(cornerRadius: Tokens.Radius.card).fill(Color.ds.accentTint))
                    .accessibilityIdentifier("complete.week")
                Button("Done", action: onDone)
                    .buttonStyle(.dsPrimary)
                    .keyboardShortcut(.return, modifiers: [])
                    .accessibilityIdentifier("complete.done")
                if let onNextStory {
                    Button("Read the next story", action: onNextStory)
                        .buttonStyle(.dsSecondary)
                        .accessibilityIdentifier("complete.nextStory")
                }
            }
            .readableColumn()
            .padding(.vertical, Tokens.Space.xxl)
        }
    }

    private func row(_ title: String, _ value: String) -> some View {
        HStack {
            Text(title).dsFont(Tokens.TypeScale.uiBody).foregroundStyle(Color.ds.ink)
            Spacer()
            Text(value).dsFont(Tokens.TypeScale.uiBody).fontWeight(.semibold).foregroundStyle(Color.ds.ink)
        }
        .accessibilityElement(children: .combine)
    }
}

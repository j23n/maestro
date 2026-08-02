// Writing capture. Two layers, in this order:
//
//  1. A deterministic rubric that always runs — length, the grammar the
//     task asked for, the vocabulary it expects. Offline, instant, and
//     the only thing the learner is actually owed.
//  2. LLM grading on top when a backend is available AND its eval gate is
//     open: did they answer the prompt, and what did they get wrong.
//
// Writing prompts ship with no acceptable answers, so `scoreAttempt` would
// mark every submission wrong — this view never calls it. The evidence
// event it records is `partial` until graded, because "they wrote
// something on topic" is weaker evidence than a scored drill.

import SwiftUI
import UIKit

struct WritingActivityView: View {
    let bridge: CoreBridge
    let feedback: FeedbackService
    let activity: PlannedActivity
    let level: String
    let onDone: () -> Void

    @State private var payload: WritingPayload?
    @State private var text = ""
    @State private var rubric: RubricResult?
    @State private var loadError: String?

    private var wordCount: Int {
        text.split(whereSeparator: \.isWhitespace).count
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            if let loadError {
                ActivityErrorView(itemId: activity.itemId, message: loadError, onSkip: onDone)
            } else if let payload {
                ScrollView {
                    VStack(alignment: .leading, spacing: 14) {
                        Eyebrow(text: "Writing")
                        if let path = payload.image,
                            let art = bridge.media(at: path).flatMap(UIImage.init(data:)) {
                            Image(uiImage: art)
                                .resizable()
                                .scaledToFill()
                                .frame(maxWidth: .infinity)
                                .frame(maxHeight: 180)
                                .clipShape(RoundedRectangle(cornerRadius: 8))
                        }
                        Text(payload.prompt)
                            .font(.callout)
                            .foregroundStyle(Color.mText)
                            .fixedSize(horizontal: false, vertical: true)

                        TextEditor(text: $text)
                            .font(.callout)
                            .scrollContentBackground(.hidden)
                            .padding(8)
                            .frame(minHeight: 140)
                            .background(Color.mSurface, in: RoundedRectangle(cornerRadius: 8))
                            .overlay(
                                RoundedRectangle(cornerRadius: 8)
                                    .strokeBorder(Color.mBorder))
                            .disabled(rubric != nil)

                        Text("\(wordCount) / \(payload.minWords) parole")
                            .font(.caption)
                            .foregroundStyle(
                                wordCount >= payload.minWords
                                    ? Color.mTextMuted : Color.mGold)

                        if let rubric {
                            RubricView(rubric: rubric)
                            FeedbackPanel(feedback: feedback)
                            if let model = payload.modelAnswer {
                                DisclosureGroup("Una versione possibile") {
                                    Text(model)
                                        .font(.callout).italic()
                                        .foregroundStyle(Color.mText)
                                }
                                .tint(Color.mTextMuted)
                            }
                        }
                    }
                    .card()
                    .padding(20)
                }

                Group {
                    if rubric == nil {
                        Button { submit(payload) } label: {
                            Text("Consegna").frame(maxWidth: .infinity)
                        }
                        .disabled(wordCount == 0)
                    } else {
                        Button { onDone() } label: {
                            Text("Continua").frame(maxWidth: .infinity)
                        }
                    }
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .padding(.horizontal, 20)
                .padding(.bottom, 8)
            } else {
                ProgressView()
            }
        }
        .task {
            do { payload = try bridge.itemPayload(WritingPayload.self, id: activity.itemId) }
            catch { loadError = "\(error)" }
        }
    }

    private func submit(_ payload: WritingPayload) {
        let result = RubricResult(submission: text, payload: payload)
        rubric = result
        try? bridge.recordAttempt(
            itemId: activity.itemId,
            // Deterministically we only know they wrote something on task;
            // the LLM verdict, if it arrives, folds back separately.
            outcome: result.meetsRubric ? "partial" : "incorrect",
            modality: "writing",
            evidenceJson: bridge.evidence(for: activity.itemId),
            response: text)

        Task {
            await feedback.request(
                kind: "writing_feedback",
                itemId: activity.itemId,
                submission: text,
                variables: [
                    "level": level,
                    "prompt": payload.prompt,
                    "submission": text,
                    "weakness_tags": payload.requiredGrammar.joined(separator: ", "),
                ])
        }
    }
}

/// What can be checked without a model: length, and whether the task's
/// own requirements were reached for.
struct RubricResult {
    let words: Int
    let minWords: Int
    let vocabUsed: [String]
    let vocabMissing: [String]

    init(submission: String, payload: WritingPayload) {
        let lowered = submission.lowercased()
        words = submission.split(whereSeparator: \.isWhitespace).count
        minWords = payload.minWords
        vocabUsed = payload.requiredVocab.filter { lowered.contains($0.lowercased()) }
        vocabMissing = payload.requiredVocab.filter { !lowered.contains($0.lowercased()) }
    }

    var meetsLength: Bool { words >= minWords }
    var meetsRubric: Bool { meetsLength && vocabMissing.isEmpty }
}

struct RubricView: View {
    let rubric: RubricResult

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Label(
                rubric.meetsLength
                    ? "Long enough (\(rubric.words) words)"
                    : "A bit short — \(rubric.words) of \(rubric.minWords) words",
                systemImage: rubric.meetsLength ? "checkmark.circle" : "info.circle"
            )
            .foregroundStyle(rubric.meetsLength ? Color.mSuccess : Color.mGold)

            if !rubric.vocabUsed.isEmpty {
                Label(
                    "Used: \(rubric.vocabUsed.joined(separator: ", "))",
                    systemImage: "checkmark.circle"
                ).foregroundStyle(Color.mSuccess)
            }
            if !rubric.vocabMissing.isEmpty {
                Label(
                    "Didn't use: \(rubric.vocabMissing.joined(separator: ", "))",
                    systemImage: "circle.dashed"
                ).foregroundStyle(Color.mTextMuted)
            }
        }
        .font(.footnote)
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            rubric.meetsRubric ? Color.mSuccessBg : Color.mSurface,
            in: RoundedRectangle(cornerRadius: 8))
    }
}

/// The LLM tier's output — or an honest account of why there isn't any.
struct FeedbackPanel: View {
    let feedback: FeedbackService

    var body: some View {
        switch feedback.state {
        case .idle:
            EmptyView()
        case .running:
            HStack(spacing: 8) {
                ProgressView()
                Text("Checking your writing…")
                    .font(.footnote).foregroundStyle(Color.mTextMuted)
            }
        case .queued(let why):
            VStack(alignment: .leading, spacing: 4) {
                Label("Saved for detailed feedback", systemImage: "tray.full")
                    .font(.footnote).foregroundStyle(Color.mText)
                Text(why).font(.caption).foregroundStyle(Color.mTextMuted)
            }
        case .failed(let why):
            VStack(alignment: .leading, spacing: 4) {
                Label("Couldn't get detailed feedback", systemImage: "exclamationmark.triangle")
                    .font(.footnote).foregroundStyle(Color.mGold)
                Text(why).font(.caption).foregroundStyle(Color.mTextMuted)
            }
        case .done:
            if let response = feedback.response {
                VStack(alignment: .leading, spacing: 10) {
                    if let strengths = response.strengths {
                        Label(strengths, systemImage: "hand.thumbsup")
                            .font(.footnote).foregroundStyle(Color.mSuccess)
                    }
                    ForEach(Array(response.errors.enumerated()), id: \.offset) { _, mistake in
                        VStack(alignment: .leading, spacing: 2) {
                            if let quote = mistake.quote, let correction = mistake.correction {
                                Text("\(quote) → \(correction)")
                                    .font(.footnote.bold())
                                    .foregroundStyle(Color.mTerracotta)
                            }
                            if let explanation = mistake.explanation {
                                Text(explanation)
                                    .font(.caption).foregroundStyle(Color.mTextMuted)
                            }
                        }
                    }
                    if let model = response.modelAnswer {
                        Text(model)
                            .font(.footnote).italic().foregroundStyle(Color.mText)
                    }
                }
            }
        }
    }
}

import LearningCore
import SwiftUI

/// Placement after onboarding (docs/06 §19): the intro, the adaptive blocks (one attempt per item, no feedback, a
/// progress bar), then "We'll start you at Unit N" with Start there and Start from the beginning. Leaving at any
/// point offers Start from the beginning. RootView shows it while `AppModel.placementPending` is set; finishing
/// clears it and the tabs appear, with the catch-up cards on Today.
struct PlacementHost: View {
    let deps: AppDependencies
    @State private var launch: AppModel.PlacementLaunch?
    @State private var services: PlayerServices?
    @State private var failed = false
    @State private var confirmLeave = false
    @State private var startedAt = Date()

    var body: some View {
        Group {
            if let launch, let services {
                switch launch.model.phase {
                case .intro:
                    PlacementIntroView(
                        onStart: {
                            startedAt = Date()
                            launch.model.start()
                        }, onFromBeginning: fromBeginning)
                case .playing:
                    AssessmentSessionView(
                        title: launch.model.blockLine, progress: launch.model.progress, counter: nil,
                        host: launch.model.host, payload: launch.model.payload,
                        position: launch.model.session.answeredCount, bundle: launch.model.bundle,
                        services: services, onClose: { confirmLeave = true }, onContinue: { launch.model.advance() }
                    )
                    .confirmationDialog(PlacementCopy.leaveTitle, isPresented: $confirmLeave, titleVisibility: .visible)
                    {
                        Button("Start from the beginning", role: .destructive, action: fromBeginning)
                            .accessibilityIdentifier("placement.fromBeginning")
                        Button("Keep going", role: .cancel) {}
                            .accessibilityIdentifier("placement.keepGoing")
                    } message: {
                        Text(PlacementCopy.leaveMessage)
                    }
                case .result:
                    if let result = deps.app.placementResult(launch.model) {
                        PlacementResultView(content: result, onStartThere: startThere, onFromBeginning: fromBeginning)
                    } else {
                        MissingContentPage(onContinue: fromBeginning)
                    }
                }
            } else if failed {
                MissingContentPage(onContinue: fromBeginning)
            } else {
                ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .task { await load() }
        // "Simulate speech by typing" asks for the transcript here too (speaking items).
        .debugOverlay(deps.services.debug, step: nil, exercise: launch?.model.payload?.id)
        // The tabs aren't up yet: placement's listening items still log `audioPlayed`.
        .onAppear { deps.audioPlayer.onStop = { [app = deps.app] report in app.audioPlayed(report) } }
    }

    private func load() async {
        do {
            guard let l = try await deps.app.startPlacement() else {
                failed = true
                return
            }
            let resolver: any AudioResolving = deps.app.audioCatalog ?? StaticAudioResolver()
            services = PlayerServices(
                audio: ExerciseAudio(player: deps.audioPlayer, resolver: resolver),
                speech: SpeechCapture(recognizer: deps.speech))
            launch = l
        } catch {
            failed = true
        }
    }

    private var activeSeconds: Int { Int(Date().timeIntervalSince(startedAt)) }

    private func startThere() {
        guard let launch, let completion = launch.model.completion else { return fromBeginning() }
        services?.audio.stop()
        deps.app.finishPlacement(completion, launch: launch, activeSeconds: activeSeconds)
    }

    private func fromBeginning() {
        services?.audio.stop()
        deps.app.startFromTheBeginning(launch: launch, activeSeconds: activeSeconds)
    }
}

/// "Let's find your level": what placement is, then Start or Start from the beginning.
struct PlacementIntroView: View {
    let onStart: () -> Void
    let onFromBeginning: () -> Void

    var body: some View {
        AssessmentPage(pose: .hello, title: PlacementCopy.introTitle, identifier: "placement.intro") {
            Text(PlacementCopy.introBody).dsFont(Tokens.TypeScale.uiBody).foregroundStyle(Color.ds.ink)
            Text(PlacementCopy.introRules).dsFont(Tokens.TypeScale.uiBody).foregroundStyle(Color.ds.secondary)
            HStack(alignment: .top, spacing: Tokens.Space.l) {
                Mascot(pose: .think, size: 56, decorative: true, isHint: true)
                Text(PlacementCopy.mokaLine).dsFont(Tokens.TypeScale.translation).foregroundStyle(Color.ds.secondary)
            }
        } buttons: {
            Button("Start", action: onStart)
                .buttonStyle(.dsPrimary)
                .keyboardShortcut(.return, modifiers: [])
                .accessibilityIdentifier("placement.start")
            Button("Start from the beginning", action: onFromBeginning)
                .buttonStyle(.dsSecondary)
                .accessibilityIdentifier("placement.fromBeginning")
        }
    }
}

/// "We'll start you at Unit N: *title*" with Start there and Start from the beginning.
struct PlacementResultView: View {
    let content: PlacementResultContent
    let onStartThere: () -> Void
    let onFromBeginning: () -> Void

    var body: some View {
        AssessmentPage(pose: .cheer, title: content.headline, identifier: "placement.result") {
            VStack(alignment: .leading, spacing: Tokens.Space.xs) {
                ItalianText(content.titleIt, style: Tokens.TypeScale.unitTitle, italic: true)
                if !content.titleEn.isEmpty {
                    Text(content.titleEn).dsFont(Tokens.TypeScale.translation).foregroundStyle(Color.ds.secondary)
                }
            }
            .accessibilityElement(children: .combine)
            Text(content.detail).dsFont(Tokens.TypeScale.uiBody).foregroundStyle(Color.ds.ink)
        } buttons: {
            Button("Start there", action: onStartThere)
                .buttonStyle(.dsPrimary)
                .keyboardShortcut(.return, modifiers: [])
                .accessibilityIdentifier("placement.startThere")
            Button("Start from the beginning", action: onFromBeginning)
                .buttonStyle(.dsSecondary)
                .accessibilityIdentifier("placement.fromBeginning")
        }
    }
}

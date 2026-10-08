import LearningCore
import SwiftUI

/// The final A1 check (docs/06 §20): the intro with the five sections, the items with check-mode rules (speaking
/// always recorded), then the result with the indicative pass and **Export for examiner**, which builds the zip and
/// opens the share sheet (docs/12). Presented over the app from the final review unit.
struct FinalCheckHost: View {
    let deps: AppDependencies
    let onDismiss: () -> Void
    @State private var launch: AppModel.FinalCheckLaunch?
    @State private var services: PlayerServices?
    @State private var outcome: AppModel.FinalCheckOutcome?
    @State private var failed = false
    @State private var confirmLeave = false
    @State private var startedAt = Date()
    @State private var miniPreview: FinalMiniPreview?

    var body: some View {
        Group {
            if let outcome {
                FinalCheckResultView(content: outcome.result, export: outcome.export, deps: deps, onDone: onDismiss)
            } else if let launch, let services {
                switch launch.model.phase {
                case .intro:
                    FinalCheckIntroView(
                        sections: launch.model.sections, excluded: launch.model.excluded,
                        onStart: {
                            // Eligibility (docs/05): words the learner never met are shown before the first item.
                            if launch.missing.isEmpty {
                                begin()
                            } else {
                                miniPreview = FinalMiniPreview(pairs: launch.missing)
                            }
                        }, onClose: onDismiss)
                case .playing:
                    AssessmentSessionView(
                        title: launch.model.currentSection?.title, progress: launch.model.progress,
                        counter: launch.model.counter, host: launch.model.host, payload: launch.model.payload,
                        position: launch.model.index, bundle: launch.model.bundle, services: services,
                        onClose: { confirmLeave = true },
                        onContinue: {
                            launch.model.advance()
                            if launch.model.phase == .finished { complete() }
                        },
                        debug: deps.services.debug
                    )
                    .confirmationDialog("Leave the final check?", isPresented: $confirmLeave, titleVisibility: .visible)
                    {
                        Button("Leave", role: .destructive, action: leave)
                            .accessibilityIdentifier("final.leave")
                        Button("Keep going", role: .cancel) {}
                            .accessibilityIdentifier("final.keepGoing")
                    } message: {
                        Text(FinalCheckCopy.leaveMessage)
                    }
                case .finished:
                    ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
                        .onAppear(perform: complete)
                }
            } else if failed {
                MissingContentPage(onContinue: onDismiss)
            } else {
                ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .task { await load() }
        // "Simulate speech by typing" asks for the transcript here too (the speaking section).
        .debugOverlay(deps.services.debug, step: nil, exercise: launch?.model.payload?.id)
        .sheet(item: $miniPreview) { request in
            MiniPreviewSheet(words: deps.app.words(for: request.pairs), services: services) {
                deps.app.introduceForFinalCheck(request.pairs)
                miniPreview = nil
                begin()
            }
            .interactiveDismissDisabled()
        }
    }

    private func begin() {
        startedAt = Date()
        launch?.model.start()
    }

    private func load() async {
        do {
            guard let l = try await deps.app.startFinalCheck() else {
                failed = true
                return
            }
            let resolver: any AudioResolving = deps.app.audioCatalog ?? StaticAudioResolver()
            let speech = SpeechCapture(recognizer: deps.speech)
            // Speaking items always record (docs/09), whatever else is set.
            speech.recordingDestination = { [model = l.model] in model.recordingDestination() }
            services = PlayerServices(
                audio: ExerciseAudio(player: deps.audioPlayer, resolver: resolver), speech: speech)
            launch = l
        } catch {
            failed = true
        }
    }

    private var activeSeconds: Int { Int(Date().timeIntervalSince(startedAt)) }

    private func complete() {
        guard outcome == nil, let launch else { return }
        services?.audio.stop()
        deps.app.endSession(
            sessionID: launch.sessionID, kind: .final, startedAt: launch.startedAt, activeSeconds: activeSeconds)
        outcome = deps.app.completeFinalCheck(launch)
        if outcome == nil { onDismiss() }
    }

    private func leave() {
        services?.audio.stop()
        if let launch { deps.app.abandonFinalCheck(launch, activeSeconds: activeSeconds) }
        onDismiss()
    }
}

/// The final check's intro: the five sections, the rules, and that speaking is recorded.
struct FinalCheckIntroView: View {
    let sections: [FinalCheckSessionModel.Section]
    let excluded: Set<String>
    let onStart: () -> Void
    let onClose: () -> Void

    var body: some View {
        AssessmentPage(pose: .hello, title: FinalCheckCopy.title, identifier: "final.intro") {
            Text(FinalCheckCopy.introBody).dsFont(Tokens.TypeScale.uiBody).foregroundStyle(Color.ds.ink)
            Card {
                ForEach(Array(sections.enumerated()), id: \.element.id) { n, s in
                    if n > 0 { CardDivider() }
                    HStack {
                        Text(s.title).dsFont(Tokens.TypeScale.uiBody).foregroundStyle(Color.ds.ink)
                        Spacer()
                        Text(excluded.contains(s.id) ? "Not on this device" : "12 points")
                            .dsFont(Tokens.TypeScale.uiCallout).foregroundStyle(Color.ds.secondary)
                    }
                    .accessibilityElement(children: .combine)
                    .accessibilityIdentifier("final.section.\(s.id)")
                }
            }
            Text(FinalCheckCopy.introRules).dsFont(Tokens.TypeScale.uiBody).foregroundStyle(Color.ds.secondary)
            if !excluded.isEmpty {
                Text(FinalCheckCopy.noSpeech).dsFont(Tokens.TypeScale.uiCallout).foregroundStyle(Color.ds.warningText)
            }
        } buttons: {
            Button("Start", action: onStart)
                .buttonStyle(.dsPrimary)
                .keyboardShortcut(.return, modifiers: [])
                .accessibilityIdentifier("final.start")
            Button("Not now", action: onClose)
                .buttonStyle(.dsSecondary)
                .keyboardShortcut(.cancelAction)
                .accessibilityIdentifier("final.notNow")
        }
    }
}

/// The result (docs/06 §20): each section out of 12 with the indicative pass, the practice-check line, and
/// **Export for examiner**.
struct FinalCheckResultView: View {
    let content: FinalCheckResultContent
    /// The sitting's record (nil when it couldn't be saved on this device).
    let export: ExaminerExport?
    let deps: AppDependencies
    let onDone: () -> Void
    @State private var exportResult: AppModel.ExaminerExportResult?

    var body: some View {
        AssessmentPage(
            pose: content.indicativePass ? .cheer : .think, title: FinalCheckCopy.title, identifier: "final.result"
        ) {
            Text(content.headline).dsFont(Tokens.TypeScale.uiTitle).foregroundStyle(Color.ds.ink)
            Card {
                ForEach(Array(content.sections.enumerated()), id: \.offset) { n, s in
                    if n > 0 { CardDivider() }
                    VStack(alignment: .leading, spacing: Tokens.Space.s) {
                        HStack {
                            Text(s.title).dsFont(Tokens.TypeScale.uiBody).foregroundStyle(Color.ds.ink)
                            Spacer()
                            if !s.excluded {
                                Image(systemName: s.passed ? "checkmark.circle.fill" : "circle")
                                    .foregroundStyle(s.passed ? Color.ds.success : Color.ds.inputBorder)
                                    .accessibilityHidden(true)
                            }
                            Text(s.score).dsFont(Tokens.TypeScale.uiBody).fontWeight(.semibold)
                                .foregroundStyle(Color.ds.ink)
                        }
                        if !s.excluded { DSProgressBar(value: s.fraction) }
                    }
                    .accessibilityElement(children: .combine)
                    .accessibilityValue(
                        Text(s.excluded ? "" : s.passed ? "reached the pass mark" : "below the pass mark")
                    )
                    .accessibilityIdentifier("final.section.\(n)")
                }
            }
            Text(content.passRule).dsFont(Tokens.TypeScale.uiCallout).foregroundStyle(Color.ds.secondary)
            Text(FinalCheckCopy.disclaimer).dsFont(Tokens.TypeScale.uiCallout).fontWeight(.semibold)
                .foregroundStyle(Color.ds.ink)
                .accessibilityIdentifier("final.disclaimer")
            Text(export == nil ? FinalCheckCopy.exportUnsaved : FinalCheckCopy.exportStatus(exportResult))
                .dsFont(Tokens.TypeScale.uiCallout).foregroundStyle(Color.ds.secondary)
                .accessibilityIdentifier("final.exportStatus")
        } buttons: {
            if let export, exportResult != .shared {
                ExaminerExportButton(export: export, deps: deps) { exportResult = $0 }
            }
            Button("Done", action: onDone)
                .buttonStyle(.dsPrimary)
                .keyboardShortcut(.return, modifiers: [])
                .accessibilityIdentifier("final.done")
        }
    }
}

/// **Export for examiner**: builds the zip and opens the share sheet through `ExportSharing`; the app deletes the
/// recordings only when the share completes (docs/12).
struct ExaminerExportButton: View {
    let export: ExaminerExport
    let deps: AppDependencies
    let onResult: (AppModel.ExaminerExportResult) -> Void
    @State private var sharing = false

    var body: some View {
        Button {
            sharing = true
            Task {
                let result = await deps.app.exportForExaminer(export, sharing: deps.exportSharing)
                sharing = false
                onResult(result)
            }
        } label: {
            Label("Export for examiner", systemImage: "square.and.arrow.up")
        }
        .buttonStyle(.dsSecondary)
        .disabled(sharing)
        .accessibilityLabel(Text("Export for examiner"))
        .accessibilityIdentifier("final.export")
    }
}

/// The final review unit's card for the final check (docs/05 § Final A1 check: once Unit 12 is completed), inside
/// the unit overview's scrolling content: **Take the final check**, and **Export for examiner** for the newest
/// sitting still kept on this device (looked up when the sittings change, not on every render).
struct FinalCheckCard: View {
    let deps: AppDependencies
    let unit: UnitID
    let onStart: () -> Void
    @State private var pending: ExaminerExport?
    @State private var exportResult: AppModel.ExaminerExportResult?

    var body: some View {
        if deps.app.offersFinalCheck(in: unit) {
            Card {
                VStack(alignment: .leading, spacing: Tokens.Space.m) {
                    Text(FinalCheckCopy.title).dsFont(Tokens.TypeScale.uiTitle).foregroundStyle(Color.ds.ink)
                        .accessibilityAddTraits(.isHeader)
                    Text(FinalCheckCopy.introBody).dsFont(Tokens.TypeScale.uiCallout)
                        .foregroundStyle(Color.ds.secondary)
                    Button("Take the final check", action: onStart)
                        .buttonStyle(.dsPrimary)
                        .accessibilityIdentifier("final.open")
                    if let pending {
                        ExaminerExportButton(export: pending, deps: deps) { exportResult = $0 }
                    }
                    if let exportResult {
                        Text(FinalCheckCopy.exportStatus(exportResult)).dsFont(Tokens.TypeScale.uiCallout)
                            .foregroundStyle(Color.ds.secondary)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .task(id: deps.app.finalCheckFilesChanged) { pending = await deps.app.pendingExaminerExport() }
        }
    }
}

struct FinalCheckRequest: Identifiable {
    let id = UUID()
}

/// The final check's "Before we go on": the words its items need that the learner never met.
struct FinalMiniPreview: Identifiable {
    let id = UUID()
    let pairs: [ItemSkillPair]
}

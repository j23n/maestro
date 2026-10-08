import LearningCore
import SwiftUI
import UniformTypeIdentifiers

/// Settings → Debug (builds with `ITA_DEBUG_MENU` only; docs/02 § App configuration): every item of the Debug menu.
struct DebugSettingsSection: View {
    @Bindable var model: DebugMenuModel
    /// Shown here, never mid-lesson (docs/02 § Logging and errors).
    var storageError: String?
    @State private var confirmReset = false
    @State private var exporting = false

    var body: some View {
        SettingsGroup("Debug") {
            Stepper(
                value: Binding(get: { model.clockOffsetDays }, set: { model.setClockOffset(days: $0) }), in: -60...60
            ) {
                row("Clock offset", value: offsetText)
            }
            .accessibilityLabel(Text("Clock offset"))
            .accessibilityValue(Text(offsetText))
            .accessibilityIdentifier("debug.clockOffset")

            HStack(spacing: Tokens.Space.m) {
                Picker("Jump to unit", selection: $model.jumpTarget) {
                    ForEach(model.units) { unit in
                        Text(unit.title).tag(Optional(unit.id))
                    }
                }
                .accessibilityIdentifier("debug.jumpUnit")
                Button("Jump") { Task { await model.jump() } }
                    .buttonStyle(.dsSecondarySmall)
                    .disabled(model.jumpTarget == nil || model.isWorking)
                    .accessibilityLabel(Text("Jump to the chosen unit"))
                    .accessibilityIdentifier("debug.jump")
            }

            Button("Rebuild state from events") { Task { await model.rebuild() } }
                .buttonStyle(.dsTextLink)
                .disabled(model.isWorking)
                .accessibilityIdentifier("debug.rebuild")

            Button("Export the learner database") {
                Task {
                    await model.exportDatabase()
                    exporting = model.exportedFile != nil
                }
            }
            .buttonStyle(.dsTextLink)
            .disabled(model.isWorking)
            .accessibilityIdentifier("debug.export")

            Toggle(
                "Simulate speech by typing",
                isOn: Binding(get: { model.simulateSpeech }, set: { on in Task { await model.setSimulateSpeech(on) } })
            )
            .disabled(model.speech == nil)
            .accessibilityIdentifier("debug.simulateSpeech")

            Toggle("Show eligibility in lessons", isOn: $model.showEligibility)
                .accessibilityIdentifier("debug.eligibilityToggle")

            Toggle("Show draft markers", isOn: $model.showDraftMarkers)
                .accessibilityIdentifier("debug.drafts")

            Toggle("Auto-answer in lessons", isOn: $model.showAutoAnswer)
                .accessibilityIdentifier("debug.autoAnswerSwitch")

            Button("Reset local data…", role: .destructive) { confirmReset = true }
                .buttonStyle(.dsTextLink)
                .disabled(model.isWorking)
                .accessibilityIdentifier("debug.reset")

            if let status = model.status {
                Text(status).dsFont(Tokens.TypeScale.uiCallout).foregroundStyle(Color.ds.secondary)
                    .textSelection(.enabled)
                    .accessibilityIdentifier("debug.status")
            }
            if let storageError {
                Text("Last storage error: \(storageError)").font(.footnote.monospaced())
                    .foregroundStyle(Color.ds.secondary).textSelection(.enabled)
                    .accessibilityIdentifier("debug.storageError")
            }
        }
        .toggleStyle(DSToggleStyle())
        .confirmationDialog("Reset local data?", isPresented: $confirmReset, titleVisibility: .visible) {
            Button("Reset", role: .destructive) { Task { await model.resetLocalData() } }
                .accessibilityIdentifier("debug.resetConfirm")
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("This erases your progress on this device and, with sync on, in iCloud. Device settings stay.")
        }
        .fileExporter(
            isPresented: $exporting, item: model.exportedFile.map(LearnerDatabaseFile.init),
            contentTypes: [.database], defaultFilename: model.exportedFile?.lastPathComponent
        ) { _ in
            model.exportFinished()
        } onCancellation: {
            model.exportFinished()
        }
    }

    private var offsetText: String {
        switch model.clockOffsetDays {
        case 0: "none"
        case let d where d > 0: "+\(d) days"
        case let d: "\(d) days"
        }
    }

    private func row(_ title: String, value: String) -> some View {
        HStack {
            Text(title).dsFont(Tokens.TypeScale.uiBody).foregroundStyle(Color.ds.ink)
            Spacer()
            Text(value).dsFont(Tokens.TypeScale.uiBody).foregroundStyle(Color.ds.secondary)
        }
    }
}

/// The exported learner database for the save panel (macOS: user-selected files, docs/02) or the Files picker.
struct LearnerDatabaseFile: Transferable {
    let url: URL

    static var transferRepresentation: some TransferRepresentation {
        FileRepresentation(exportedContentType: .database) { file in SentTransferredFile(file.url) }
    }
}

extension View {
    /// The Debug menu's overlay in the lesson and review players, placement and the final check: a draft marker, the
    /// eligibility of what is on screen, and the typed answer for simulated speech. Draws nothing unless the Debug
    /// menu turned it on.
    func debugOverlay(_ model: DebugMenuModel?, step: StepID?, exercise: ExerciseID?) -> some View {
        modifier(DebugOverlay(model: model, step: step, exercise: exercise))
    }
}

extension View {
    /// The Debug menu's auto-answer bar (M6.3) over a player: answer the exercise on screen correctly, wrongly, or
    /// correctly and continue (`AutoAnswer`). Draws nothing unless the Debug menu or `-ITAAutoAnswer` turned it on,
    /// so builds without the Debug menu never show it.
    func autoAnswerBar(_ debug: DebugMenuModel?, host: ExerciseHostModel?, advance: @escaping () -> Void) -> some View {
        modifier(AutoAnswerBar(debug: debug, host: host, advance: advance))
    }
}

private struct AutoAnswerBar: ViewModifier {
    let debug: DebugMenuModel?
    let host: ExerciseHostModel?
    let advance: () -> Void

    @ViewBuilder func body(content: Content) -> some View {
        if let debug, debug.autoAnswerEnabled {
            content.overlay(alignment: .bottomTrailing) {
                HStack(spacing: Tokens.Space.xs) {
                    button("checkmark", label: "Answer correctly", identifier: "debug.autoAnswer") {
                        AutoAnswer.answerOnPage(host, .correct, advance: advance)
                    }
                    .disabled(host == nil)
                    button("xmark", label: "Answer wrongly", identifier: "debug.autoAnswerWrong") {
                        AutoAnswer.answerOnPage(host, .wrong, advance: advance)
                    }
                    .disabled(host == nil)
                    button("forward.end", label: "Answer and continue", identifier: "debug.autoAdvance") {
                        AutoAnswer.answerAndContinue(host, advance: advance)
                    }
                }
                .padding(Tokens.Space.xs)
                .background(Capsule().fill(Color.ds.surface.opacity(0.9)))
                .padding(.trailing, Tokens.Space.s)
                .padding(.bottom, Tokens.Space.xxl * 3)
            }
        } else {
            content
        }
    }

    private func button(
        _ symbol: String, label: String, identifier: String, action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            Image(systemName: symbol).font(.system(size: 14, weight: .semibold))
                .foregroundStyle(Color.ds.secondary)
                .frame(width: 32, height: 32)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(Text(label))
        .accessibilityIdentifier(identifier)
    }
}

private struct DebugOverlay: ViewModifier {
    let model: DebugMenuModel?
    let step: StepID?
    let exercise: ExerciseID?
    @State private var showReport = false

    @ViewBuilder func body(content: Content) -> some View {
        if let model {
            content
                .overlay(alignment: .topTrailing) { badges(model) }
                .safeAreaInset(edge: .bottom) {
                    if let speech = model.speech, let prompt = speech.prompt {
                        SimulatedSpeechPanel(speech: speech, prompt: prompt)
                    }
                }
                .sheet(isPresented: $showReport) {
                    EligibilitySheet(reports: model.eligibility(step: step, exercise: exercise)) {
                        showReport = false
                    }
                }
        } else {
            content
        }
    }

    @ViewBuilder private func badges(_ model: DebugMenuModel) -> some View {
        let reports = model.eligibility(step: step, exercise: exercise)
        HStack(spacing: Tokens.Space.s) {
            if model.isDraft(step) {
                Text("DRAFT").dsFont(Tokens.TypeScale.uiMicro).foregroundStyle(Color.ds.onAccent)
                    .padding(.horizontal, Tokens.Space.s).padding(.vertical, Tokens.Space.xs)
                    .background(Capsule().fill(Color.ds.accent))
                    .accessibilityLabel(Text("Draft content"))
                    .accessibilityIdentifier("debug.draftBadge")
            }
            if !reports.isEmpty {
                Button {
                    showReport = true
                } label: {
                    Text(reports.allSatisfy(\.isEligible) ? "Eligible" : "Missing \(reports.flatMap(\.missing).count)")
                        .dsFont(Tokens.TypeScale.uiMicro)
                }
                .buttonStyle(.dsSecondarySmall)
                .accessibilityLabel(Text("Eligibility of this screen"))
                .accessibilityIdentifier("debug.eligibilityBadge")
            }
        }
        .padding(.top, Tokens.Space.xxl * 2)
        .padding(.trailing, Tokens.Space.l)
    }
}

/// The requirements of the step and exercise on screen.
private struct EligibilitySheet: View {
    let reports: [EligibilityReport]
    let onDone: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: Tokens.Space.l) {
            HStack {
                Text("Eligibility").dsFont(Tokens.TypeScale.uiTitle).foregroundStyle(Color.ds.ink)
                    .accessibilityAddTraits(.isHeader)
                Spacer()
                Button("Done", action: onDone)
                    .buttonStyle(.dsSecondarySmall)
                    .keyboardShortcut(.cancelAction)
                    .accessibilityIdentifier("debug.eligibilityDone")
            }
            ScrollView {
                VStack(alignment: .leading, spacing: Tokens.Space.xxl) {
                    ForEach(reports, id: \.title) { report in
                        VStack(alignment: .leading, spacing: Tokens.Space.xs) {
                            Text(report.title).dsFont(Tokens.TypeScale.uiBody).foregroundStyle(Color.ds.ink)
                            Text(report.summary).dsFont(Tokens.TypeScale.uiCallout)
                                .foregroundStyle(Color.ds.secondary)
                            ForEach(report.requirements, id: \.pair) { r in
                                Text(r.line).font(.footnote.monospaced())
                                    .foregroundStyle(r.isIntroduced ? Color.ds.secondary : Color.ds.ink)
                            }
                        }
                    }
                }
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .accessibilityIdentifier("debug.eligibilityReport")
        }
        .padding(Tokens.Space.xxl)
        .frame(idealWidth: 420, idealHeight: 480)
        .background(Color.ds.background)
    }
}

/// "Simulate speech by typing": what the learner would have said.
private struct SimulatedSpeechPanel: View {
    let speech: SimulatedSpeechRecognizer
    let prompt: SimulatedSpeechRecognizer.Prompt
    @State private var text = ""
    @FocusState private var focused: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: Tokens.Space.s) {
            Text("Simulated speech: type what you'd say").dsFont(Tokens.TypeScale.uiCaption)
                .foregroundStyle(Color.ds.secondary)
            if let expected = prompt.expected.first {
                Text("Expected: \(expected)").dsFont(Tokens.TypeScale.uiCaption).foregroundStyle(Color.ds.secondary)
            }
            HStack(spacing: Tokens.Space.m) {
                TextField("What you said", text: $text)
                    .textFieldStyle(.roundedBorder)
                    .focused($focused)
                    .onSubmit(submit)
                    .accessibilityIdentifier("debug.speechField")
                Button("Say it", action: submit)
                    .buttonStyle(.dsSecondarySmall)
                    .accessibilityIdentifier("debug.speechSubmit")
                Button("Cancel") { speech.cancel() }
                    .buttonStyle(.dsTextLink)
                    .accessibilityIdentifier("debug.speechCancel")
            }
        }
        .padding(Tokens.Space.l)
        .background(Color.ds.surface)
        .onAppear { focused = true }
        .id(prompt.id)
    }

    private func submit() {
        speech.submit(text)
        text = ""
    }
}

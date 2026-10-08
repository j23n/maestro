import Foundation
import LearningCore
import Observation

/// Where the Debug menu keeps its own switches between launches (device-local, never synced, never in the learner
/// database). `UserDefaults` in the app; a dictionary in tests.
@MainActor
protocol DebugPreferences: AnyObject {
    func integer(forKey key: String) -> Int
    func bool(forKey key: String) -> Bool
    func set(_ value: Int, forKey key: String)
    func set(_ value: Bool, forKey key: String)
}

extension UserDefaults: DebugPreferences {}

/// Settings → Debug (task M3.3; docs/02 § App configuration), only in builds with `ITA_DEBUG_MENU`: clock offset,
/// jump to unit, rebuild state from events, export the learner DB, simulate speech by typing, show eligibility for
/// the current screen, show draft markers, and reset local data. Every change to the learner's data goes through
/// events or the store's own operations; nothing here edits the event log.
@MainActor
@Observable
final class DebugMenuModel {
    enum Key {
        static let clockOffsetDays = "ITADebugClockOffsetDays"
        static let showEligibility = "ITADebugShowEligibility"
        static let showDraftMarkers = "ITADebugShowDraftMarkers"
    }

    @ObservationIgnored let app: AppModel
    @ObservationIgnored let clock: DebugClock?
    @ObservationIgnored let speech: SimulatedSpeechRecognizer?
    @ObservationIgnored private let preferences: any DebugPreferences
    @ObservationIgnored private let exportFolder: URL

    /// The player overlay lists the current step's and exercise's requirements.
    var showEligibility: Bool { didSet { preferences.set(showEligibility, forKey: Key.showEligibility) } }
    /// The player overlay marks unapproved (draft) steps of a dev pack.
    var showDraftMarkers: Bool { didSet { preferences.set(showDraftMarkers, forKey: Key.showDraftMarkers) } }
    /// The unit "Jump" goes to.
    var jumpTarget: UnitID?
    /// Draft steps of the bundled pack (empty for a release pack).
    private(set) var draftSteps: Set<StepID> = []
    /// One line about the last action ("Jumped to Unit 2 · 2 events").
    private(set) var status: String?
    /// The last export, for the share or save sheet.
    private(set) var exportedFile: URL?
    private(set) var isWorking = false

    /// The clock offset a launch starts with (`DebugClock(offsetDays:)`).
    static func storedClockOffset(_ preferences: any DebugPreferences) -> Int {
        preferences.integer(forKey: Key.clockOffsetDays)
    }

    init(
        app: AppModel, clock: DebugClock?, speech: SimulatedSpeechRecognizer?, preferences: any DebugPreferences,
        exportFolder: URL = FileManager.default.temporaryDirectory
    ) {
        self.app = app
        self.clock = clock
        self.speech = speech
        self.preferences = preferences
        self.exportFolder = exportFolder
        showEligibility = preferences.bool(forKey: Key.showEligibility)
        showDraftMarkers = preferences.bool(forKey: Key.showDraftMarkers)
    }

    /// After launch: the pack's draft steps, and the first unit as the jump target.
    func load() async {
        if let reader = app.reader, let outline = try? await reader.courseOutline() {
            draftSteps = Set(outline.flatMap { $0.steps.filter(\.isDraft).map(\.id) })
        }
        if jumpTarget == nil { jumpTarget = app.outline.units.first?.id }
    }

    // MARK: Clock offset

    var clockOffsetDays: Int { clock?.offsetDays ?? 0 }

    /// "Today" moves by whole days; kept for the next launch too.
    func setClockOffset(days: Int) {
        guard let clock else { return }
        clock.offsetDays = days
        preferences.set(days, forKey: Key.clockOffsetDays)
        status = days == 0 ? "Clock: device time" : "Clock: \(days > 0 ? "+" : "")\(days) days"
    }

    // MARK: Jump to unit

    struct UnitChoice: Identifiable, Equatable, Sendable {
        let id: UnitID
        /// "Unit 2 · Al bar" (the title comes from the pack).
        let title: String
    }

    /// The units "Jump to" offers.
    var units: [UnitChoice] {
        app.outline.units.map { UnitChoice(id: $0.id, title: "Unit \($0.number) · \($0.titleIt)") }
    }

    func jump() async {
        guard let unit = jumpTarget else { return }
        await run { [app] in
            let written = try await app.debugJump(to: unit)
            return written == 0 ? "Already at \(unit)" : "Jumped to \(unit) · \(written) events"
        }
    }

    /// `-ITAJumpToUnit` (`LaunchArguments`).
    func jumpAtLaunch(to unit: UnitID) async {
        jumpTarget = unit
        await run { [app] in
            try await app.debugJumpAtLaunch(to: unit)
            return "Launched at \(unit)"
        }
    }

    // MARK: Rebuild, export, reset

    func rebuild() async {
        await run { [app] in
            let events = try await app.debugRebuild()
            return "Rebuilt from \(events) events"
        }
    }

    func exportDatabase() async {
        await run { [app, exportFolder] in
            let url = try await app.debugExportDatabase(to: exportFolder)
            self.exportedFile = url
            return "Exported \(url.lastPathComponent)"
        }
    }

    /// The file exporter saved the copy or was cancelled: the temporary copy goes (a learner database holds
    /// everything the learner did, so it never lingers in the temporary folder).
    func exportFinished() {
        if let file = exportedFile { try? FileManager.default.removeItem(at: file) }
        exportedFile = nil
    }

    func resetLocalData() async {
        await run { [app] in
            try await app.debugResetLocalData()
            return "Local data reset"
        }
    }

    // MARK: Simulated speech

    var simulateSpeech: Bool { speech?.isSimulating ?? false }

    /// Speaking exercises appear while simulating, whatever the device can do; switched off, the real
    /// recogniser decides again.
    func setSimulateSpeech(_ on: Bool) async {
        guard let speech else { return }
        speech.isSimulating = on
        app.canSpeak = on ? true : await speech.availability().canSpeak
        status = on ? "Speech: type what you'd say" : "Speech: device recogniser"
    }

    // MARK: The player overlay

    /// The current step's and exercise's requirements, when "Show eligibility" is on.
    func eligibility(step: StepID?, exercise: ExerciseID?) -> [EligibilityReport] {
        guard showEligibility, let content = app.content, let state = app.state else { return [] }
        return [
            step.flatMap { EligibilityReport.step($0, content: content, state: state) },
            exercise.flatMap { EligibilityReport.exercise($0, content: content, state: state) },
        ].compactMap { $0 }
    }

    /// Whether to mark this step as a draft.
    func isDraft(_ step: StepID?) -> Bool {
        guard showDraftMarkers, let step else { return false }
        return draftSteps.contains(step)
    }

    // MARK: -

    private func run(_ action: () async throws -> String) async {
        isWorking = true
        defer { isWorking = false }
        do {
            status = try await action()
        } catch {
            status = "Failed: \(error)"
        }
    }
}

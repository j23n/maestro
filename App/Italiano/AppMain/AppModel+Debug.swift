import Foundation
import LearningCore
import Storage

/// The Debug menu's jump to a unit (docs/02 § App configuration), expressed as events like everything else (the log
/// is append-only, CLAUDE.md rule 5): a `placementCompleted` that starts at the unit, so the units before it are
/// skipped and it is open, and one placement-style `introduced` event (via `debug`) for every item of the earlier
/// units, per its status. Nothing is invented for FSRS: those pairs have no memory until they are reviewed.
enum DebugJump {
    struct Plan: Equatable, Sendable {
        var placement: PlacementCompletedPayload?
        var introduced: IntroducedPayload?

        var isEmpty: Bool { placement == nil && introduced == nil }
    }

    /// What jumping to `unit` still has to write; empty when the learner already stands there (so relaunching with
    /// `-ITAJumpToUnit` writes nothing and a half-done step resumes). Nil for a unit the pack doesn't have.
    static func plan(to unit: UnitID, state: LearnerState, content: ContentIndex) -> Plan? {
        guard content.unitOrd(unit) != nil else { return nil }
        let placement =
            state.placement?.startUnit == unit ? nil : PlacementCompletedPayload(startUnit: unit, blocks: [])
        let pairs = (Introductions.placementPayload(startUnit: unit, content: content)?.pairs ?? [])
            .filter { !state.isIntroduced($0) }
        return Plan(
            placement: placement, introduced: pairs.isEmpty ? nil : IntroducedPayload(pairs: pairs, via: .debug))
    }
}

extension AppModel {
    enum DebugError: Error, Equatable, CustomStringConvertible {
        case notReady
        case unknownUnit(UnitID)

        var description: String {
            switch self {
            case .notReady: "The learner database isn't open."
            case .unknownUnit(let unit): "The course has no unit \(unit)."
            }
        }
    }

    /// Jumps to `unit` (see `DebugJump`) and waits until the events are stored. Returns how many were written.
    @discardableResult
    func debugJump(to unit: UnitID) async throws(DebugError) -> Int {
        await settle()
        guard let state, let content, let factory else { throw .notReady }
        guard let plan = DebugJump.plan(to: unit, state: state, content: content) else { throw .unknownUnit(unit) }
        var events: [Event] = []
        if let p = plan.placement { events.append(factory.placementCompleted(p)) }
        if let p = plan.introduced, let e = factory.introduced(p) { events.append(e) }
        write(events)
        await settle()
        return events.count
    }

    /// `-ITAJumpToUnit`: onboarding with its defaults first when it hasn't run, so the app opens on Today.
    func debugJumpAtLaunch(to unit: UnitID) async throws(DebugError) {
        if !isOnboarded {
            completeOnboarding(
                OnboardingAnswers(
                    reason: nil, name: "", forms: .both, country: nil, goal: LearnerSettings().goalDaysPerWeek,
                    beginner: content?.units.first?.id == unit, consent: nil))
        }
        try await debugJump(to: unit)
    }

    /// "Rebuild state from events": replays the whole log and rewrites the derived tables (docs/05 § Replay).
    /// Returns the number of events replayed.
    func debugRebuild() async throws -> Int {
        await settle()
        guard let store else { throw DebugError.notReady }
        try await store.rebuildAll()  // the store's state stream brings the new state to `state`
        return try await store.eventCount()
    }

    /// "Export the learner DB": a self-contained copy in `folder`, named after today's local date.
    func debugExportDatabase(to folder: URL) async throws -> URL {
        await settle()
        guard let store else { throw DebugError.notReady }
        let day = LocalDay.string(ms: env.clock.nowMs(), tzOffsetMinutes: env.clock.tzOffsetMinutes())
        let url = folder.appendingPathComponent("learner-\(day).sqlite")
        try await store.exportCopy(to: url)
        return url
    }

    /// "Reset local data" (docs/08 § Reset progress): with sync running, the sync driver erases this device's
    /// progress and deletes the iCloud zone; otherwise the store erases it. Device settings stay; onboarding runs
    /// again because its synced answers are gone, and so do the final check's recordings and exports.
    func debugResetLocalData() async throws {
        await settle()
        guard let store else { throw DebugError.notReady }
        if let sync, !(sync is DisabledSync) {
            await sync.resetProgress()
        } else {
            try await store.eraseProgress()
        }
        deleteFinalCheckFiles()
        isOnboarded = (try? await store.settingRecord(SettingKey.profileForms.rawValue)) != nil
    }
}

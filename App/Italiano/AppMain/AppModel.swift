import Foundation
import LearningCore
import Observation
import Storage

/// The app's runtime (docs/02 § App): the content pack, the learner store and the engine, loaded once at launch,
/// plus everything the screens derive from them. Platform-neutral, so the launch path is tested on Linux against
/// the mini pack; the SwiftUI shell (RootView) only draws it.
@MainActor
@Observable
final class AppModel {
    enum Phase: Equatable {
        case loading
        case ready
        /// The bundled pack's schema doesn't match this build (docs/02 § Logging and errors): `error.packMismatch`.
        case packMismatch(String)
        case failed(String)
    }

    struct Environment: Sendable {
        var packURL: URL
        /// nil → `Application Support/Italiano/learner.sqlite`.
        var learnerURL: URL?
        var clock: any LearningCore.Clock
        var ids: any UUIDSource
        var platform: Platform
    }

    let env: Environment
    private(set) var phase: Phase = .loading
    private(set) var state: LearnerState?
    private(set) var settings = LearnerSettings()
    private(set) var outline = CourseOutline(units: [])
    /// One sentence when the learner database had to be recovered at launch (M3.9).
    private(set) var recoveryNotice: String?
    /// Speech recognition is available and switched on (docs/09); the Settings screen and the recogniser set it.
    var canSpeak = false
    /// A write that failed after launch: never shown mid-lesson (docs/02 § Logging and errors); the Debug menu
    /// shows it and the App's adapter logs it with os.Logger.
    private(set) var lastStorageError: String?

    @ObservationIgnored private(set) var reader: PackReader?
    @ObservationIgnored private(set) var store: LearnerStore?
    @ObservationIgnored private(set) var content: ContentIndex?
    @ObservationIgnored private(set) var factory: EventFactory?
    @ObservationIgnored private(set) var knownForms: KnownForms = .empty
    @ObservationIgnored private(set) var audioCatalog: PackAudioCatalog?
    @ObservationIgnored private var words: [ItemID: WordInfo] = [:]
    @ObservationIgnored private(set) var wordSources: [WordSource] = []
    @ObservationIgnored private var countries: [String: LearnerProfile.Country] = [:]
    @ObservationIgnored private var lastWrite: Task<Void, Never>?
    @ObservationIgnored private var observers: [Task<Void, Never>] = []

    init(env: Environment) { self.env = env }

    // MARK: - Launch

    func start() async {
        let reader: PackReader
        let content: ContentIndex
        do {
            reader = try await PackReader.open(url: env.packURL)
            content = try await reader.contentIndex()
            outline = CourseOutline(try await reader.courseOutline())
            knownForms = try await reader.knownForms()
            audioCatalog = try await reader.audioCatalog()
            let items = try await reader.allItems()
            words = Dictionary(items.map { ($0.id, WordInfo($0)) }, uniquingKeysWith: { a, _ in a })
            wordSources = items.enumerated().map { n, item in
                WordSource(info: WordInfo(item), kind: item.kind, scheduledSkills: item.scheduledSkills, order: n)
            }
            countries = Dictionary(
                try await reader.countries().map { ($0.id, $0.profileCountry) }, uniquingKeysWith: { a, _ in a })
        } catch {
            if case .schemaMismatch = error {
                phase = .packMismatch(String(describing: error))
            } else {
                phase = .failed(String(describing: error))
            }
            return
        }
        do {
            let url = try env.learnerURL ?? LearnerStore.defaultURL()
            let opened = try await LearnerStore.openRecovering(
                url: url, content: content, clock: env.clock, ids: env.ids)
            let store = opened.store
            if opened.recovery != nil {
                recoveryNotice =
                    "Your progress on this device couldn't be read, so it was set aside; "
                    + "it comes back from iCloud if sync is on."
            }
            factory = try await store.makeEventFactory(packVersion: reader.meta.packVersion, ids: env.ids)
            self.reader = reader
            self.content = content
            self.store = store
            state = store.state
            settings = store.settings
            observe(store)
            phase = .ready
        } catch {
            phase = .failed(String(describing: error))
        }
    }

    private func observe(_ store: LearnerStore) {
        observers.append(
            Task { [weak self] in
                for await s in store.states() { self?.state = s }
            })
        observers.append(
            Task { [weak self] in
                for await s in store.settingsUpdates() { self?.settings = s }
            })
    }

    // MARK: - Events

    /// Appends this device's events in call order (docs/05: append-only); `settle()` waits for them.
    func write(_ events: [Event]) {
        guard let store, !events.isEmpty else { return }
        let previous = lastWrite
        lastWrite = Task { [weak self] in
            await previous?.value
            do {
                let result = try await store.append(events)
                self?.state = result.state
            } catch {
                self?.lastStorageError = String(describing: error)
            }
        }
    }

    func write(_ event: Event) { write([event]) }

    /// Waits until every event written so far is stored and derived.
    func settle() async { await lastWrite?.value }

    // MARK: - Settings (docs/08: device or synced scope is the key's)

    func set(_ key: SettingKey, to value: JSONValue) {
        guard let store else { return }
        let previous = lastWrite
        lastWrite = Task { [weak self] in
            await previous?.value
            do {
                _ = try await store.set(key, to: value)
                self?.settings = store.settings
            } catch {
                self?.lastStorageError = String(describing: error)
            }
        }
    }

    // MARK: - What the screens show

    var profile: LearnerProfile {
        LearnerProfile(
            forms: settings.profileForms, strictForms: settings.strictForms,
            name: settings.profileName.isEmpty ? nil : settings.profileName,
            country: settings.profileCountry.flatMap { countries[$0] })
    }

    var today: TodayContent? {
        guard let state, let content else { return nil }
        let plan = Planner(
            content: content, state: state, device: DeviceCapabilities(speechAvailable: canSpeak),
            settings: PlannerSettings(settings)
        ).today(clock: env.clock)
        return TodayCopy.make(
            plan: plan, outline: outline, words: words, nowMs: env.clock.nowMs(),
            tzOffsetMinutes: env.clock.tzOffsetMinutes())
    }

    var courseProgress: CourseProgress? {
        guard let state, let content else { return nil }
        return CourseProgress(state: state, content: content)
    }

    var courseRows: [CourseRow] {
        courseProgress.map { CourseCopy.rows(outline: outline, progress: $0) } ?? []
    }

    var courseFooter: String? { courseProgress.flatMap { CourseCopy.footer(outline: outline, progress: $0) } }

    var wordRows: [WordRow] {
        guard let state else { return [] }
        return WordsCopy.rows(sources: wordSources, state: state, nowMs: env.clock.nowMs(),
                              tzOffsetMinutes: env.clock.tzOffsetMinutes())
    }

    func overview(unit: UnitID) -> UnitOverview? {
        guard let u = outline.unit(unit), let p = courseProgress else { return nil }
        return CourseCopy.overview(unit: u, progress: p)
    }

    // MARK: - Playing a step

    /// What the player needs for one sitting.
    struct PlayerLaunch {
        let model: LessonPlayerModel
        let environment: ExerciseEnvironment
        let sink: EventAttemptSink
        let sessionID: String
        let startedAt: Int64
        let kind: SessionKind
    }

    /// Loads the step's lesson (or the unit-level step) and resumes it from the attempts already stored.
    func launch(step: StepID) async throws(PackError) -> PlayerLaunch? {
        guard let reader, let factory, let state else { return nil }
        let bundle = try await LessonLoader.bundle(for: step, reader: reader)
        let answered = bundle.steps.reduce(into: Set<ExerciseID>()) { set, s in
            set.formUnion(state.stepProgress(s.id)?.finalExercises ?? [])
        }
        let isCheck = bundle.steps.contains { $0.payload.kind == .check }
        let sessionID = env.ids.next()
        let sink = EventAttemptSink(factory: factory, context: isCheck ? .check : .lesson, sessionID: sessionID) {
            [weak self] event in self?.write(event)
        }
        let clock = env.clock
        let environment = ExerciseEnvironment(
            context: isCheck ? .check : .lesson, profile: profile, knownForms: knownForms,
            nowMs: { clock.nowMs() }, canSpeak: canSpeak)
        return PlayerLaunch(
            model: LessonPlayerModel(bundle: bundle, answered: answered, startingAt: step), environment: environment,
            sink: sink, sessionID: sessionID, startedAt: env.clock.nowMs(), kind: isCheck ? .check : .lesson)
    }

    /// Step events for a move in the player: `stepCompleted`, then the new step's introductions and
    /// `stepStarted` (docs/05 § Introductions). Returns the words the learner hasn't met that the new step needs:
    /// the mini-preview ("Before we go on") shows them, and `introduceMissing` records them after Continue.
    @discardableResult
    func stepChanged(_ change: LessonPlayerModel.StepChange, sessionID: String) -> [ItemSkillPair] {
        guard let factory, let content, let state else { return [] }
        var events: [Event] = []
        if let done = change.completed { events.append(factory.stepCompleted(done, sessionId: sessionID)) }
        var missing: [ItemSkillPair] = []
        if let started = change.started, let step = content.step(started) {
            let entry = Eligibility.enter(step, state: state, content: content)
            if let via = entry.via, let e = factory.introduced(entry.introductions, via: via, stepId: started) {
                events.append(e)
            }
            if Progression.shouldWriteStepStarted(started, state: state) {
                events.append(factory.stepStarted(started, sessionId: sessionID))
            }
            missing = entry.missing
        }
        write(events)
        return missing
    }

    /// The mini-preview's Continue: the missing pairs are introduced `via: catchup`.
    func introduceMissing(_ pairs: [ItemSkillPair], step: StepID) {
        guard let factory, let e = factory.introduced(pairs, via: .catchup, stepId: step) else { return }
        write(e)
    }

    /// The words for a mini-preview's meet cards.
    func words(for pairs: [ItemSkillPair]) -> [WordInfo] {
        var seen: Set<ItemID> = []
        return pairs.compactMap { p in seen.insert(p.itemId).inserted ? words[p.itemId] : nil }
    }

    /// A tapped word in a text (docs/05 § Events, `glossTapped`).
    func glossTapped(text: TextID, line: Int, token: Int, item: ItemID?) {
        guard let factory else { return }
        write(factory.glossTapped(textId: text, line: line, token: token, itemId: item))
    }

    /// Playback stopped or ended (`audioPlayed`); the player adapters report it through `AudioPlaying.onStop`.
    func audioPlayed(_ r: PlaybackReport) {
        guard let factory, r.playedMs > 0 else { return }
        write(factory.audioPlayed(audioId: AudioID(rawValue: r.audioID), textId: r.textID.map(TextID.init(rawValue:)),
                                  rate: r.rate, playedMs: r.playedMs, context: r.context))
    }

    /// Closing or finishing the player writes the `session` event (docs/05: `platform` feeds the sync status).
    func endSession(_ launch: PlayerLaunch, activeSeconds: Int) {
        guard let factory else { return }
        write(
            factory.session(
                sessionId: launch.sessionID, kind: launch.kind, platform: env.platform, startedAt: launch.startedAt,
                endedAt: env.clock.nowMs(), activeSeconds: activeSeconds))
    }
}

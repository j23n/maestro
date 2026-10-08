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
    /// False until onboarding has run on any of the learner's devices (it writes the synced `profile.forms`).
    private(set) var isOnboarded = true
    /// Placement comes next: onboarding said "Yes, I know a little" (AppModel+Placement.swift).
    var placementPending = false
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
    @ObservationIgnored private(set) var words: [ItemID: WordInfo] = [:]
    @ObservationIgnored private(set) var wordSources: [WordSource] = []
    @ObservationIgnored private var countries: [String: LearnerProfile.Country] = [:]
    @ObservationIgnored private var countryNames: [OnboardingModel.CountryChoice] = []
    @ObservationIgnored private var lastWrite: Task<Void, Never>?
    @ObservationIgnored private var observers: [Task<Void, Never>] = []
    /// Sync (or `DisabledSync`): steps that complete ask it to sync now (docs/08).
    @ObservationIgnored var sync: (any SyncControlling)?

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
            let packCountries = try await reader.countries()
            countries = Dictionary(packCountries.map { ($0.id, $0.profileCountry) }, uniquingKeysWith: { a, _ in a })
            countryNames = packCountries.map { .init(id: $0.id, nameIt: $0.nameIt, nameEn: $0.nameEn) }
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
            isOnboarded = (try? await store.settingRecord(SettingKey.profileForms.rawValue)) != nil
            await prepareAssessments()
            phase = .ready
        } catch {
            phase = .failed(String(describing: error))
        }
    }

    /// After an account switch the sync driver opens a fresh database for the new account: use it from now on.
    func replaceStore(_ newStore: LearnerStore) async {
        await settle()
        observers.forEach { $0.cancel() }
        observers = []
        store = newStore
        state = newStore.state
        settings = newStore.settings
        if let reader {
            factory = try? await newStore.makeEventFactory(packVersion: reader.meta.packVersion, ids: env.ids)
        }
        observe(newStore)
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

    // MARK: - Onboarding

    struct OnboardingAnswers: Sendable, Equatable {
        var reason: String?
        var name: String
        var forms: LearnerForms
        var country: String?
        var goal: Int
        var beginner: Bool
        /// Study builds: the research consent answer (docs/12); nil elsewhere.
        var consent: Bool?
    }

    /// The research consent text's version (docs/12; the text itself is the owner's, `TODO(owner)` in the screen).
    static let consentTextVersion = "draft-1"

    /// Countries for "Where do you live?", in English alphabetical order (the learner looks for their own country's
    /// English name; the Italian name is shown with it).
    var countryChoices: [OnboardingModel.CountryChoice] {
        countryNames.sorted { $0.nameEn < $1.nameEn }
    }

    /// The masculine and feminine nationality that illustrate "Which forms fit you?" (docs/07), from the pack so no
    /// Italian is hard-coded: the United States when the pack has it, else the first country whose forms differ.
    var formsExample: OnboardingModel.FormsExample? {
        let differing = countries.values.filter { $0.nationalityM != $0.nationalityF }
        guard let country = countries["us"] ?? differing.min(by: { $0.id < $1.id }) else { return nil }
        return .init(masculine: country.nationalityM, feminine: country.nationalityF)
    }

    /// Writes the answers as settings and one `onboardingCompleted` event (docs/05 § Events).
    func completeOnboarding(_ a: OnboardingAnswers) {
        if let reason = a.reason { set(.profileReason, to: .string(reason)) }
        if !a.name.isEmpty { set(.profileName, to: .string(a.name)) }
        if let country = a.country { set(.profileCountry, to: .string(country)) }
        set(.goalDaysPerWeek, to: .number(Double(a.goal)))
        set(.profileForms, to: .string(a.forms.rawValue))
        if let consent = a.consent { setStudyConsent(consent) }  // study builds only (docs/12)
        if let factory {
            write(
                factory.onboardingCompleted(
                    OnboardingCompletedPayload(
                        reason: a.reason, forms: a.forms, country: a.country, beginner: a.beginner)))
        }
        offerPlacement(beginner: a.beginner)
        isOnboarded = true
    }

    /// Settings → Research (study builds, docs/12): turning sharing on records a new consent dated now, so only
    /// events from then on upload; turning it off records the refusal and uploads stop.
    func setStudyConsent(_ granted: Bool) {
        let consent = StudyConsent(version: Self.consentTextVersion, date: env.clock.nowMs(), granted: granted)
        set(.studyConsent, to: consent.json)
        if granted, settings.studyInstallId == nil { set(.studyInstallId, to: .string(env.ids.next())) }
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
        return WordsCopy.rows(
            sources: wordSources, state: state, nowMs: env.clock.nowMs(),
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
        /// Unit checks: the answers to score when the check step completes.
        let checkRecorder: CheckRecorder?
    }

    /// Loads the step's lesson (or the unit-level step) and resumes it from the attempts already stored.
    func launch(step: StepID, fresh: Bool = false) async throws(PackError) -> PlayerLaunch? {
        guard let reader, let factory, let state else { return nil }
        let bundle = try await LessonLoader.bundle(for: step, reader: reader)
        // `fresh`: a retake starts from the first page whatever was answered before.
        let answered =
            fresh
            ? []
            : bundle.steps.reduce(into: Set<ExerciseID>()) { set, s in
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
        let recorder: CheckRecorder? = isCheck ? CheckRecorder() : nil
        if let recorder { sink.onRecord = { recorder.record($0) } }
        return PlayerLaunch(
            model: LessonPlayerModel(bundle: bundle, answered: answered, startingAt: step), environment: environment,
            sink: sink, sessionID: sessionID, startedAt: env.clock.nowMs(), kind: isCheck ? .check : .lesson,
            checkRecorder: recorder)
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
        if change.completed != nil, let sync {
            Task { [weak self] in
                await self?.settle()
                await sync.syncNow()
            }
        }
        return missing
    }

    /// Scores a finished unit check (docs/05 § Checks) and writes `checkCompleted`: can-dos, focus items for the
    /// wrong answers and the unit's completion follow from it in replay. Speaking sections are excluded when the
    /// device can't take them.
    @discardableResult
    func completeCheck(_ launch: PlayerLaunch) -> CheckResultContent? {
        guard let recorder = launch.checkRecorder, let content, let factory,
            let check = content.check(forUnit: launch.model.bundle.unitID)
        else { return nil }
        let excluded = canSpeak ? [] : check.speechOnlySections(content: content)
        let result = CheckScoring.score(
            check: check, answers: recorder.answers, excludedSections: excluded,
            content: content)
        write(factory.checkCompleted(result.payload))
        var titles: [String: String] = [:]
        for step in launch.model.bundle.steps {
            if case .check(_, _, let sections) = step.payload {
                for s in sections { titles[s.id] = s.titleEn }
            }
        }
        return CheckResultContent(result: result, titles: titles, words: words)
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
        write(
            factory.audioPlayed(
                audioId: AudioID(rawValue: r.audioID), textId: r.textID.map(TextID.init(rawValue:)),
                rate: r.rate, playedMs: r.playedMs, context: r.context))
    }

    /// Closing or finishing the player writes the `session` event (docs/05: `platform` feeds the sync status).
    func endSession(_ launch: PlayerLaunch, activeSeconds: Int) {
        endSession(
            sessionID: launch.sessionID, kind: launch.kind, startedAt: launch.startedAt,
            activeSeconds: activeSeconds)
    }

    func endSession(sessionID: String, kind: SessionKind, startedAt: Int64, activeSeconds: Int) {
        guard let factory else { return }
        write(
            factory.session(
                sessionId: sessionID, kind: kind, platform: env.platform, startedAt: startedAt,
                endedAt: env.clock.nowMs(), activeSeconds: activeSeconds))
    }

    /// "Tomorrow": when the next card falls due after now (the session-complete screen).
    var nextReview: String? {
        guard let state else { return nil }
        let now = env.clock.nowMs()
        guard let due = state.memory.values.map(\.dueMs).filter({ $0 > now }).min() else { return nil }
        let tz = env.clock.tzOffsetMinutes()
        return WordsCopy.nextReviewText(
            dueMs: due, today: LocalDay.dayNumber(ms: now, tzOffsetMinutes: tz),
            tzOffsetMinutes: tz)
    }

    var week: WeekProgress? {
        guard let state else { return nil }
        return Progress.week(
            state: state, now: env.clock.nowMs(), tzOffsetMinutes: env.clock.tzOffsetMinutes(),
            goal: settings.goalDaysPerWeek)
    }

    // MARK: - Review sessions

    struct ReviewLaunch {
        let model: ReviewSessionModel
        let sessionID: String
        let startedAt: Int64
    }

    /// Today's review (or, with nothing due, the catch-up cards after placement): the engine's session, with every
    /// bank exercise its cards (and their re-queues) can use loaded up front. Nil when there is nothing to review.
    func startReview() async throws(PackError) -> ReviewLaunch? {
        guard let reader, let content, let state, let factory else { return nil }
        let builder = Planner(
            content: content, state: state, device: DeviceCapabilities(speechAvailable: canSpeak),
            settings: PlannerSettings(settings)
        ).sessionBuilder
        let sessionID = env.ids.next()
        let now = env.clock.nowMs()
        let tz = env.clock.tzOffsetMinutes()
        var session = builder.build(sessionId: sessionID, now: now, tzOffsetMinutes: tz)
        if session.cards.isEmpty { session = builder.buildCatchUp(sessionId: sessionID, now: now, tzOffsetMinutes: tz) }
        guard !session.cards.isEmpty else { return nil }
        var ids: Set<ExerciseID> = []
        for card in session.cards { ids.formUnion(try await reader.exerciseIDs(targeting: card.pair)) }
        let bank = Dictionary(
            try await reader.exercises(Array(ids).sorted()).map { ($0.id, $0.payload) }, uniquingKeysWith: { a, _ in a }
        )
        let words = self.words
        let payloads: (ReviewCard) -> ExercisePayload? = { card in
            switch card.exercise {
            case .bank(let id, _):
                return bank[id]
            case .generated(let g):
                let unit = content.item(g.itemId)?.unitId ?? UnitID(rawValue: "u00")
                return GeneratedPayloads.payload(for: g, unit: unit, display: { words[$0] })
            }
        }
        let sink = EventAttemptSink(factory: factory, context: .review, sessionID: sessionID) { [weak self] event in
            self?.write(event)
        }
        let clock = env.clock
        let environment = ExerciseEnvironment(
            context: .review, profile: profile, knownForms: knownForms, nowMs: { clock.nowMs() }, canSpeak: canSpeak)
        let newPairs = Set(session.cards.map(\.pair).filter { state.memory[$0] == nil })
        let model = ReviewSessionModel(
            session: session, builder: builder, env: environment, sink: sink, newPairs: newPairs, payloads: payloads)
        return ReviewLaunch(model: model, sessionID: sessionID, startedAt: now)
    }
}

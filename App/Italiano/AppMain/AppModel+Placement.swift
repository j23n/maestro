import Foundation
import LearningCore
import Storage

// Placement in the app container (docs/05 § Placement, docs/06 §19): offered after onboarding when the learner said
// "Yes, I know a little" and the pack can run it; the sitting's events; "Start there" and "Start from the
// beginning". Platform-neutral, so it compiles and is tested on Linux.

extension AppModel {
    /// What the placement screens need for one sitting.
    struct PlacementLaunch {
        let model: PlacementSessionModel
        let sessionID: String
        let startedAt: Int64
    }

    /// The pack has placement questions to ask (a skeleton or partial pack may not: then nobody is offered it).
    var canRunPlacement: Bool {
        guard let content else { return false }
        return PlacementSession(assessment: content.placement, content: content) != nil
    }

    /// Onboarding's last answer: placement comes next when the learner knows some Italian and the pack can run it.
    func offerPlacement(beginner: Bool) {
        placementPending = !beginner && canRunPlacement
    }

    /// At launch: if the learner said they know some Italian but placement never finished (the app was closed
    /// during it) and they haven't started anything since, offer it again.
    func restorePlacementOffer() async {
        guard isOnboarded, canRunPlacement, let state, let store,
            Self.mayStillOfferPlacement(state: state)
        else { return }
        let onboarding = ((try? await store.events()) ?? []).reversed().lazy.compactMap { event in
            if case .onboardingCompleted(let p) = event.payload { p } else { nil }
        }.first
        if let onboarding { placementPending = !onboarding.beginner }
    }

    /// Placement is still on offer only before any placement and before the learner has started anything.
    static func mayStillOfferPlacement(state: LearnerState) -> Bool {
        state.placement == nil && state.steps.isEmpty && state.introductions.isEmpty && state.memory.isEmpty
    }

    /// Loads every exercise placement can ask (40 at most) and the texts they play or show.
    func startPlacement() async throws(PackError) -> PlacementLaunch? {
        guard let reader, let content, let factory,
            let session = PlacementSession(assessment: content.placement, content: content)
        else { return nil }
        let ids = session.assessment.blocks.flatMap(\.exerciseIds)
        let bundle = try await AssessmentLoader.bundle(
            id: "placement", title: "Placement", unit: content.units.first?.id ?? "u00", exerciseIDs: ids,
            reader: reader)
        let sessionID = env.ids.next()
        let sink = EventAttemptSink(factory: factory, context: .placement, sessionID: sessionID) { [weak self] e in
            self?.write(e)
        }
        let clock = env.clock
        let environment = ExerciseEnvironment(
            context: .placement, profile: profile, knownForms: knownForms, nowMs: { clock.nowMs() },
            canSpeak: canSpeak)
        let model = PlacementSessionModel(
            session: session, content: content, bundle: bundle, env: environment, sink: sink)
        return PlacementLaunch(model: model, sessionID: sessionID, startedAt: env.clock.nowMs())
    }

    /// The result screen for the start unit.
    func placementResult(_ model: PlacementSessionModel) -> PlacementResultContent? {
        guard let content, let start = model.startUnit else { return nil }
        return PlacementResultContent(startUnit: start, content: content, outline: outline)
    }

    /// "Start there" or "Start from the beginning": `placementCompleted`, plus the skipped units' introductions for
    /// "Start there" (docs/05 § Placement). The units before the start unit become skipped and their scheduled
    /// pairs wait in the catch-up queue. The `session` event is written when the sitting began.
    func finishPlacement(_ completion: PlacementCompletion, launch: PlacementLaunch?, activeSeconds: Int) {
        guard let factory else { return }
        if let launch, launch.model.hasStarted {
            endSession(
                sessionID: launch.sessionID, kind: .placement, startedAt: launch.startedAt,
                activeSeconds: activeSeconds)
        }
        write(Self.placementEvents(completion, factory: factory))
        placementPending = false
        if let sync {
            Task { [weak self] in
                await self?.settle()
                await sync.syncNow()
            }
        }
    }

    /// "Start from the beginning" without a pack session (the intro, or a pack that can't load its questions).
    func startFromTheBeginning(launch: PlacementLaunch?, activeSeconds: Int) {
        guard let content else { return }
        let completion =
            launch?.model.fromBeginning ?? Placement.startFromBeginning(content: content)
        if let completion {
            finishPlacement(completion, launch: launch, activeSeconds: activeSeconds)
        } else {
            placementPending = false
        }
    }

    /// `placementCompleted`, then the `introduced` event (via `placement`) when units were skipped.
    static func placementEvents(_ completion: PlacementCompletion, factory: EventFactory) -> [Event] {
        var events = [factory.placementCompleted(completion.completed)]
        if let introduced = completion.introduced, let e = factory.introduced(introduced) { events.append(e) }
        return events
    }

    /// At launch, after the stores are open: placement's offer and the final check's 30-day clean-up.
    func prepareAssessments() async {
        await restorePlacementOffer()
        purgeExpiredRecordings()
    }
}

/// A `LessonBundle` for an assessment that isn't a step (placement, the final check): its exercises, the texts they
/// show or play, the words in those texts and the speakers' names.
enum AssessmentLoader {
    static func bundle(
        id: String, title: String, unit: UnitID, exerciseIDs: [ExerciseID], reader: PackReader
    ) async throws(PackError) -> LessonBundle {
        let exercises = try await reader.exercises(exerciseIDs)
        let textIDs = Array(Set(exercises.compactMap(\.payload.sourceTextID))).sorted()
        let texts = try await reader.texts(textIDs)
        let items = try await reader.items(Array(Set(texts.flatMap(\.itemIds))).sorted())
        let characters = try await reader.characters()
        return LessonBundle(
            lessonID: LessonID(rawValue: id), unitID: unit, title: title, steps: [],
            exercises: Dictionary(exercises.map { ($0.id, $0.payload) }, uniquingKeysWith: { a, _ in a }),
            texts: Dictionary(texts.map { ($0.id, PlayerText($0)) }, uniquingKeysWith: { a, _ in a }),
            items: Dictionary(items.map { ($0.id, WordInfo($0)) }, uniquingKeysWith: { a, _ in a }),
            characters: Dictionary(characters.map { ($0.id, $0.name) }, uniquingKeysWith: { a, _ in a }))
    }
}

import Foundation

/// Why derived state must be rebuilt from scratch at launch (docs/05 § Replay, docs/03 `derived_meta`).
public enum RebuildReason: String, Sendable, Equatable {
    case noDerivedState, derivedVersionChanged, contentChanged
}

/// The pure reducer `(LearnerState, Event, ContentIndex) → LearnerState` (docs/05 § Replay).
///
/// - Memory: first attempts only, through `RatingPolicy` and `FSRS6`; each target with its own outcome.
/// - Introductions: the first one per pair wins.
/// - Step progress with the derived resume cursor; unit progress (ADR-16, placement skips); can-dos; exercise
///   history; focus items after a failed check; daily activity per local day.
/// - Events referencing IDs missing from the pack still count for memory when the item exists; otherwise they are
///   skipped and logged. Unknown event types are ignored.
public enum Replay {
    /// Bump whenever reducer logic changes; a different stored value triggers `rebuildAll` at launch.
    public static let derivedVersion = 1
    /// Failed-check focus items stay first in reviews for 3 days.
    public static let focusDurationMs: Int64 = 3 * LocalDay.msPerDay
    /// How many recent review sessions feed the median seconds per card.
    public static let secondsPerCardSampleLimit = 50

    static let fsrs = FSRS6()

    // MARK: Entry points

    /// The state before any event: one row per unit, Unit 0 available.
    public static func initialState(content: ContentIndex) -> LearnerState {
        var state = LearnerState()
        Progression.refreshUnitStates(&state, content: content)
        return state
    }

    /// Applies one event. Pure: the input state is not modified.
    public static func apply(_ state: LearnerState, _ event: Event, content: ContentIndex,
                             logger: any CoreLogger = NoOpLogger()) -> LearnerState
    {
        var next = state
        reduce(&next, event, content: content, logger: logger)
        return next
    }

    /// Applies one event in place (the same logic as `apply`, without copying the state).
    public static func reduce(_ state: inout LearnerState, _ event: Event, content: ContentIndex,
                              logger: any CoreLogger = NoOpLogger())
    {
        switch event.payload {
        case .introduced(let p): applyIntroduced(&state, p, event, content, logger)
        case .attempt(let p): applyAttempt(&state, p, event, content, logger)
        case .stepStarted(let p): applyStepStarted(&state, p, event, content, logger)
        case .stepCompleted(let p): applyStepCompleted(&state, p, event, content, logger)
        case .session(let p): applySession(&state, p, event)
        case .checkCompleted(let p): applyCheckCompleted(&state, p, event, content, logger)
        case .placementCompleted(let p): applyPlacement(&state, p, event, content, logger)
        case .glossTapped, .audioPlayed, .onboardingCompleted: break
        case .unknown(let type, _): logger.log("replay: ignored event \(event.id) of unknown type '\(type)'")
        }
        if state.lastApplied.map({ $0 < event.key }) ?? true { state.lastApplied = event.key }
    }

    /// Events in replay order `(at, id)`, each event once (copies of one event sort next to each other).
    public static func ordered(_ events: [Event]) -> [Event] {
        let sorted = events.sorted { a, b in
            a.at != b.at ? a.at < b.at : a.id.utf8.lexicographicallyPrecedes(b.id.utf8)
        }
        var out: [Event] = []
        out.reserveCapacity(sorted.count)
        for event in sorted where out.last.map({ $0.at != event.at || $0.id != event.id }) ?? true {
            out.append(event)
        }
        return out
    }

    /// Full rebuild: start empty and apply every event in `(at, id)` order. Idempotent.
    public static func rebuildAll(events: [Event], content: ContentIndex, logger: any CoreLogger = NoOpLogger())
        -> LearnerState
    {
        var state = initialState(content: content)
        for event in ordered(events) { reduce(&state, event, content: content, logger: logger) }
        return state
    }

    public enum IncrementalResult: Equatable, Sendable {
        case applied(LearnerState)
        /// An event sorts before the last applied one (a late sync): run `rebuildAll` over the whole log.
        case needsRebuild
    }

    /// The incremental path: applies new events that all sort after `lastApplied`. Events equal to the last applied
    /// one are duplicates and are skipped. If any sorts earlier, the caller must rebuild.
    public static func applyIncremental(_ state: LearnerState, events: [Event], content: ContentIndex,
                                        logger: any CoreLogger = NoOpLogger()) -> IncrementalResult
    {
        var next = state
        return applyIncremental(to: &next, events: events, content: content, logger: logger)
            ? .applied(next) : .needsRebuild
    }

    /// The incremental path in place (no copy of the state: use it on the hot path of every new event). Returns
    /// false, leaving the state untouched, when an event sorts before the last applied one and a rebuild is needed.
    public static func applyIncremental(to state: inout LearnerState, events: [Event], content: ContentIndex,
                                        logger: any CoreLogger = NoOpLogger()) -> Bool
    {
        let batch = ordered(events)
        if let last = state.lastApplied, let first = batch.first, first.key < last { return false }
        for event in batch where event.key != state.lastApplied {
            reduce(&state, event, content: content, logger: logger)
        }
        return true
    }

    /// Rebuild triggers at launch: no derived state yet, a changed `derived_version`, or a changed pack
    /// `meta.content_hash`.
    public static func rebuildReason(storedDerivedVersion: Int?, storedContentHash: String?, content: ContentIndex)
        -> RebuildReason?
    {
        guard let storedDerivedVersion, let storedContentHash else { return .noDerivedState }
        if storedDerivedVersion != derivedVersion { return .derivedVersionChanged }
        if storedContentHash != content.contentHash { return .contentChanged }
        return nil
    }

    // MARK: Event handlers

    static func applyIntroduced(_ state: inout LearnerState, _ p: IntroducedPayload, _ event: Event,
                                _ content: ContentIndex, _ logger: any CoreLogger)
    {
        for item in p.items {
            guard content.item(item.itemId) != nil else {
                logger.log("replay: event \(event.id) introduces \(item.itemId), which is not in the pack; skipped")
                continue
            }
            for skill in item.skills {
                let pair = ItemSkillPair(item.itemId, skill)
                if state.introductions[pair] == nil {
                    state.introductions[pair] = Introduction(at: event.at, via: p.via)
                }
            }
        }
    }

    static func applyAttempt(_ state: inout LearnerState, _ p: AttemptPayload, _ event: Event,
                             _ content: ContentIndex, _ logger: any CoreLogger)
    {
        var knownTargets: [AttemptTarget] = []
        knownTargets.reserveCapacity(p.targets.count)
        for target in p.targets where content.item(target.itemId) != nil {
            // Each pair once per attempt (the first occurrence counts).
            if !knownTargets.contains(where: { $0.itemId == target.itemId && $0.skill == target.skill }) {
                knownTargets.append(target)
            }
        }
        guard !knownTargets.isEmpty || content.exercise(p.exerciseId) != nil || p.exerciseId.rawValue.hasPrefix("gen:")
        else {
            logger.log("replay: attempt \(event.id) on \(p.exerciseId) references nothing in the pack; skipped")
            return
        }
        if p.targets.contains(where: { content.item($0.itemId) == nil }) {
            logger.log("replay: attempt \(event.id) has targets missing from the pack; they were skipped")
        }
        let day = event.localDay

        // Memory: first attempts only (RatingPolicy).
        for target in knownTargets {
            guard
                let rating = RatingPolicy.rating(format: p.format, outcome: target.outcome, mode: p.mode,
                                                 attemptIndex: p.attemptIndex, context: p.context)
            else { continue }
            let pair = target.pair
            let previous = state.memory[pair]
            state.memory[pair] = fsrs.review(previous, rating: rating, atMs: event.at)
            if previous == nil, p.context == .review, state.introductions[pair]?.via == .placement,
                content.item(target.itemId)?.skills[target.skill]?.scheduled == true
            {
                state.catchUpStarted[day, default: 0] += 1
            }
        }

        // Format rotation for the card selector.
        if p.attemptIndex == 1 {
            for target in knownTargets { state.formatLastUsed[target.itemId, default: [:]][p.format] = event.at }
        }

        // Exercise history.
        var history =
            state.exerciseHistory[p.exerciseId]
            ?? ExerciseHistory(lastAt: event.at, attempts: 0, firstTryCorrect: 0, lastOutcome: p.outcome,
                               lastContext: p.context)
        history.lastAt = event.at
        history.attempts += 1
        if p.attemptIndex == 1, p.outcome == .correct || p.outcome == .correctWithNote {
            history.firstTryCorrect += 1
        }
        history.lastOutcome = p.outcome
        history.lastContext = p.context
        state.exerciseHistory[p.exerciseId] = history

        // Derived resume cursor: attempts made in the step (lesson or check context). Conversation turns never finish
        // the exercise (resuming restarts the dialogue).
        if let stepId = p.stepId, p.context == .lesson || p.context == .check, p.turnId == nil, p.isFinal,
            let step = content.step(stepId),
            var progress = state.steps[stepId], progress.isOpen, step.presentationOrder.contains(p.exerciseId)
        {
            progress.finalExercises.insert(p.exerciseId)
            // The answered prefix only grows: advance from the current cursor.
            let order = step.presentationOrder
            while progress.cursor < order.count, progress.finalExercises.contains(order[progress.cursor]) {
                progress.cursor += 1
            }
            state.steps[stepId] = progress
        }

        // Daily activity and the per-session card count (median seconds per card).
        if p.context == .review, p.attemptIndex == 1 {
            state.dailyActivity[day, default: DailyActivity(day: day)].cardsReviewed += 1
            state.openReviewSessions[p.sessionId, default: 0] += 1
        }
    }

    static func applyStepStarted(_ state: inout LearnerState, _ p: StepEventPayload, _ event: Event,
                                 _ content: ContentIndex, _ logger: any CoreLogger)
    {
        guard let step = content.step(p.stepId) else {
            logger.log("replay: event \(event.id) starts \(p.stepId), which is not in the pack; skipped")
            return
        }
        var progress = state.steps[p.stepId] ?? StepProgress()
        if progress.startedAt == nil { progress.startedAt = event.at }
        // The last stepStarted is the open one: the cursor counts from it.
        progress.openStartedAt = event.at
        progress.finalExercises = []
        progress.cursor = 0
        state.steps[p.stepId] = progress

        var unit = state.units[step.unitId] ?? UnitProgress()
        if unit.startedAt == nil {
            unit.startedAt = event.at
            state.units[step.unitId] = unit
            Progression.refreshUnitStates(&state, content: content)
        }
    }

    static func applyStepCompleted(_ state: inout LearnerState, _ p: StepEventPayload, _ event: Event,
                                   _ content: ContentIndex, _ logger: any CoreLogger)
    {
        // A completed step counts for the learner's day even if the pack no longer has it.
        let day = event.localDay
        state.dailyActivity[day, default: DailyActivity(day: day)].stepsCompleted += 1
        guard content.step(p.stepId) != nil else {
            logger.log("replay: event \(event.id) completes \(p.stepId), which is not in the pack; skipped")
            return
        }
        var progress = state.steps[p.stepId] ?? StepProgress()
        if progress.completedAt == nil { progress.completedAt = event.at }
        progress.openStartedAt = nil
        progress.finalExercises = []
        progress.cursor = 0
        state.steps[p.stepId] = progress
    }

    static func applySession(_ state: inout LearnerState, _ p: SessionPayload, _ event: Event) {
        let day = event.localDay
        state.dailyActivity[day, default: DailyActivity(day: day)].activeSeconds += max(0, p.activeSeconds)
        guard p.kind == .review, let cards = state.openReviewSessions.removeValue(forKey: p.sessionId) else { return }
        if cards > 0, p.activeSeconds > 0 {
            state.secondsPerCardSamples.append(Double(p.activeSeconds) / Double(cards))
            if state.secondsPerCardSamples.count > secondsPerCardSampleLimit {
                state.secondsPerCardSamples.removeFirst(state.secondsPerCardSamples.count - secondsPerCardSampleLimit)
            }
        }
    }

    static func applyCheckCompleted(_ state: inout LearnerState, _ p: CheckCompletedPayload, _ event: Event,
                                    _ content: ContentIndex, _ logger: any CoreLogger)
    {
        let unitId: UnitID
        switch p.kind {
        case .unit:
            guard let check = content.check(p.checkId) else {
                logger.log("replay: event \(event.id) completes check \(p.checkId), which is not in the pack; skipped")
                return
            }
            unitId = check.unitId
            if !p.passed { addFocusItems(&state, check: check, at: event.at, content: content) }
        case .final:
            var record =
                state.finalCheck
                ?? CheckRecord(bestScore: p.overall, passed: p.passed, firstCompletedAt: event.at, attempts: 0)
            record.bestScore = max(record.bestScore, p.overall)
            record.passed = record.passed || p.passed
            record.attempts += 1
            state.finalCheck = record
            guard let finalUnit = content.finalUnit else {
                reachCanDos(&state, p.canDosReached, at: event.at, content: content, logger: logger)
                return
            }
            unitId = finalUnit.id
        }
        // Retakes keep the best score; passed once any attempt passed (docs/05 § Unit check scoring).
        var unit = state.units[unitId] ?? UnitProgress()
        unit.checkScore = max(unit.checkScore ?? p.overall, p.overall)
        unit.checkPassed = (unit.checkPassed ?? false) || p.passed
        if unit.completedAt == nil { unit.completedAt = event.at }
        state.units[unitId] = unit
        reachCanDos(&state, p.canDosReached, at: event.at, content: content, logger: logger)
        Progression.refreshUnitStates(&state, content: content)
    }

    static func reachCanDos(_ state: inout LearnerState, _ canDos: [CanDoID], at: Int64, content: ContentIndex,
                            logger: any CoreLogger)
    {
        let known = Set(content.canDos.map(\.id))
        for canDo in canDos {
            guard known.contains(canDo) else {
                logger.log("replay: can-do \(canDo) is not in the pack; skipped")
                continue
            }
            if state.canDos[canDo] == nil { state.canDos[canDo] = at }
        }
    }

    /// The primary targets of wrong check items become focus items for 3 days (docs/05 § Unit check scoring).
    /// "Wrong" means the item's latest check answer earned nothing (wrong, revealed or skipped).
    static func addFocusItems(_ state: inout LearnerState, check: ContentIndex.Check, at: Int64,
                              content: ContentIndex)
    {
        let until = at + focusDurationMs
        let reason = "check:\(check.id.rawValue)"
        for exerciseId in check.exerciseIds {
            guard let exercise = content.exercise(exerciseId), !exercise.targets.isEmpty,
                let history = state.exerciseHistory[exerciseId], history.lastContext == .check,
                history.lastOutcome.checkCredit == 0
            else { continue }
            for target in exercise.targets {
                let existing = state.focusItems[target]?.until ?? until
                state.focusItems[target] = FocusItem(reason: reason, until: max(existing, until))
            }
        }
    }

    static func applyPlacement(_ state: inout LearnerState, _ p: PlacementCompletedPayload, _ event: Event,
                               _ content: ContentIndex, _ logger: any CoreLogger)
    {
        guard content.unit(p.startUnit) != nil else {
            logger.log("replay: placement \(event.id) starts at \(p.startUnit), which is not in the pack; skipped")
            return
        }
        state.placement = PlacementRecord(startUnit: p.startUnit, at: event.at)
        Progression.refreshUnitStates(&state, content: content)
    }
}

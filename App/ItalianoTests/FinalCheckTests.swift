import Foundation
import LearningCore
import Storage
import Testing

@testable import Italiano

/// M8.2 (docs/05 § Final A1 check, docs/06 §20, docs/09 § Transcription, docs/12 § Final check export): a sitting
/// through the real exercise models with the speaking item recorded, the score, the examiner export's exact
/// contents and its zip. The container's paths (record, share, deletion) are in `AssessmentContainerTests`.
@MainActor
@Suite struct FinalCheckTests {
    typealias A = AssessmentCourse
    let folder = FileManager.default.temporaryDirectory
        .appendingPathComponent("italiano-final-\(UUID().uuidString)", isDirectory: true)
    let clock = FixedClock(ms: 1_791_271_800_000, tzOffsetMinutes: 120)  // Tue 6 Oct 2026, 09:30 in Rome

    struct Sitting {
        let model: FinalCheckSessionModel
        let recordings: SpeakingRecordings
        let speech: SpeechCapture
        let recognizer: FakeSpeechRecognizer
        let events: () -> [Event]
        let factory: EventFactory
    }

    func sitting(canSpeak: Bool = true) throws -> Sitting {
        let factory = EventFactory(
            deviceId: "device-a", packVersion: A.content.packVersion, clock: clock, ids: SeededUUIDSource(seed: "f"))
        let recordings = SpeakingRecordings(
            directory: folder.appendingPathComponent("final-check/s-final"), ids: SeededUUIDSource(seed: "r"))
        let log = FinalCheckLog(recordings: recordings)
        var events: [Event] = []
        let sink = EventAttemptSink(factory: factory, context: .final, sessionID: "s-final") { e in
            log.append(e)
            events.append(e)
        }
        let final = try #require(A.content.finalCheck)
        var env = ExerciseEnvironment.preview(context: .final)
        env.canSpeak = canSpeak
        let model = FinalCheckSessionModel(
            sections: A.finalSections.map { .init(id: $0.id, title: $0.title, exerciseIds: $0.ids) },
            excluded: canSpeak ? [] : FinalCheck.speechOnlySections(final, content: A.content),
            bundle: A.bundle(try A.finalPayloads()), env: env, sink: sink, log: log)
        let recognizer = FakeSpeechRecognizer(
            availability: canSpeak ? .available : .unsupported,
            scripted: [SpeechResult(transcript: "Buongiorno! Quant'è?", alternatives: [], confidence: 0.9)])
        recognizer.recordingStub = Data("m4a bytes".utf8)
        let speech = SpeechCapture(recognizer: recognizer)
        speech.recordingDestination = { [weak model] in model?.recordingDestination() }
        return Sitting(
            model: model, recordings: recordings, speech: speech, recognizer: recognizer, events: { events },
            factory: factory)
    }

    /// Answers every item like the views do: the right option except the second listening item, the registration
    /// form, and the talk task spoken once (a second try is ignored in a check), or skipped.
    func sit(_ s: Sitting, skipTalk: Bool = false) async throws {
        s.model.start()
        while s.model.phase == .playing {
            switch s.model.host {
            case .choice(let m):
                m.select(
                    s.model.currentExercise == "fin.listening.02"
                        ? (m.correctIndex + 1) % m.options.count : m.correctIndex)
            case .writing(let m):
                m.fieldValues = ["Anna", "inglese"]
                m.submit()
                m.submit()
                #expect(m.isAssessment)
            case .talk(let m):
                #expect(!m.canType)  // speech is required in checks
                #expect(m.canSkip && m.answeredLine == "Answer recorded.")
                if skipTalk {
                    // The learner started speaking, then gave up.
                    let partial = try #require(s.model.recordingDestination())
                    try Data("partial".utf8).write(to: partial)
                    m.skip()
                    #expect(m.isFinished && !m.canSkip)
                } else {
                    let r = try #require(await s.speech.capture(expected: [m.talk.model.text]))
                    m.submitSpoken(r)
                    #expect(!m.canSkip)
                }
                m.submitTyped()  // no second attempt in a check
                m.skip()
            default:
                Issue.record("unexpected item \(String(describing: s.model.currentExercise))")
            }
            s.model.advance()
        }
    }

    func export(_ s: Sitting, result: FinalCheckResult, installId: String? = "6f1c0e1a-study") -> ExaminerExport {
        ExaminerExport(
            sittingId: "s-final", checkCompletedEventId: "e-completed", installId: installId,
            takenAt: clock.nowMs(), tzOffsetMinutes: 120, packVersion: "0.9.0", appVersion: "1.0 (7)",
            passMarkPerSection: 7,
            sections: A.finalSections.map { .init(id: $0.id, title: $0.title, exerciseIds: $0.ids) }, result: result,
            formats: Dictionary(uniqueKeysWithValues: A.content.exercises.map { ($0.id, $0.format) }),
            scores: Dictionary(uniqueKeysWithValues: A.content.exercises.map { ($0.id, Double($0.score)) }),
            checkAnswers: s.model.recorder.answers, answers: s.model.log.answers)
    }

    @Test func aSittingIsScoredRecordedAndExported() async throws {
        let s = try sitting()
        #expect(s.model.phase == .intro && s.model.counter == "1 / 6")
        try await sit(s)
        #expect(s.model.phase == .finished && s.model.progress == 1)

        // The talk answer was recorded to <exerciseId>-<attemptId>.m4a: the attempt's own event ID.
        let attempts = s.events().compactMap { e -> (String, AttemptPayload)? in
            if case .attempt(let a) = e.payload { (e.id, a) } else { nil }
        }
        #expect(attempts.count == 6)
        #expect(attempts.allSatisfy { $0.1.context == .final && $0.1.attemptIndex == 1 })
        let talk = try #require(attempts.first { $0.1.exerciseId == "fin.speaking.01" })
        #expect(talk.1.mode == .spoken && talk.1.response == "Buongiorno! Quant'è?")
        let recording = try #require(s.model.log.answers["fin.speaking.01"]?.first?.recording)
        #expect(recording == "fin.speaking.01-\(talk.0).m4a")
        #expect(s.model.log.recordingURLs == [s.recordings.directory.appendingPathComponent(recording)])
        #expect(FileManager.default.fileExists(atPath: s.model.log.recordingURLs[0].path))
        #expect(s.recognizer.recordedURLs.count == 1)

        // Score: listening 2 of 4 raw → 6/12, reading, structures 12/12, writing 1 of 2 fields, speaking 2 of 2.
        let final = try #require(A.content.finalCheck)
        let result = CheckScoring.scoreFinal(
            final, answers: s.model.recorder.answers, excludedSections: s.model.excluded, content: A.content)
        #expect(result.sections.map(\.id) == ["listening", "reading", "structures", "writing", "speaking"])
        #expect(result.sections[0].points == 6 && !result.sections[0].passed)
        #expect(result.sections[1].points == 12 && result.sections[2].points == 12)
        #expect(result.sections[4].points == 12)
        #expect(!result.indicativePass)
        let screen = FinalCheckResultContent(
            result: result, titles: Dictionary(uniqueKeysWithValues: A.finalSections.map { ($0.id, $0.title) }),
            passMark: 7)
        #expect(screen.sections.map(\.score).first == "6 of 12")
        #expect(screen.headline == "Not every section reached 7 of 12 yet.")
        #expect(screen.passRule == "Indicative pass: 7 of 12 in every section.")
        #expect(FinalCheckCopy.disclaimer == "This is a practice check, not an official certificate.")

        // The export: exactly README.txt, responses.json, writing/*.txt, speaking/*.m4a.
        let export = export(s, result: result)
        #expect(export.fileName == "final-check-6f1c0e1a-study-2026-10-06-0930.zip")
        let entries = try export.entries(recordings: s.recordings.directory)
        #expect(
            entries.map(\.path) == [
                "README.txt", "responses.json", "writing/fin.writing.01.txt", "speaking/fin.speaking.01-\(talk.0).m4a",
            ])
        #expect(String(decoding: entries[2].data, as: UTF8.self) == "Nome: Anna\nNazionalità: inglese\n")
        #expect(entries[3].data == Data("m4a bytes".utf8))
        let readme = String(decoding: entries[0].data, as: UTF8.self)
        #expect(readme.contains("Install ID: 6f1c0e1a-study"))
        #expect(readme.contains("not an official certificate"))
        #expect(readme.contains("- Listening: 6 of 12"))
        #expect(readme.contains("indicative pass: 7 of 12 in every section"))

        let responses = try JSONDecoder().decode(ExaminerExport.Responses.self, from: entries[1].data)
        #expect(responses == export.responses)
        #expect(responses.installId == "6f1c0e1a-study" && responses.takenAt == "2026-10-06T09:30:00+02:00")
        #expect(responses.passMarkPerSection == 7)
        #expect(responses.sections.map(\.points) == result.sections.map(\.points))
        #expect(responses.items.map(\.exerciseId) == A.finalSections.flatMap(\.ids).map(\.rawValue))
        let listening2 = try #require(responses.items.first { $0.exerciseId == "fin.listening.02" })
        #expect(listening2.score == 2 && listening2.earned == 0 && listening2.answers.first?.outcome == "wrong")
        let spoken = try #require(responses.items.first { $0.exerciseId == "fin.speaking.01" })
        #expect(spoken.answers.count == 1)
        #expect(spoken.answers.first?.recording == "speaking/fin.speaking.01-\(talk.0).m4a")
        #expect(spoken.answers.first?.response == "Buongiorno! Quant'è?")
        #expect(responses.items.first { $0.format == "writing" }?.writingFile == "writing/fin.writing.01.txt")
        // Exactly the keys docs/12 documents (`turnId` only appears for a conversation's turns).
        #expect(try Self.keys(entries[1].data) == Self.documentedKeys())

        // The zip reads back with the same files and valid checksums.
        let zip = try export.archive(recordings: s.recordings.directory)
        let files = try ZipReader.read(zip)
        #expect(files.map(\.path) == entries.map(\.path))
        #expect(files.map(\.data) == entries.map(\.data))
        #expect(files.allSatisfy { $0.crcMatches })

        // A recording that went missing is left out, and its answer names none.
        try FileManager.default.removeItem(at: s.model.log.recordingURLs[0])
        let without = try export.entries(recordings: s.recordings.directory)
        #expect(without.map(\.path) == ["README.txt", "responses.json", "writing/fin.writing.01.txt"])
        let stripped = try JSONDecoder().decode(ExaminerExport.Responses.self, from: without[1].data)
        #expect(stripped.items.flatMap(\.answers).allSatisfy { $0.recording == nil })

        // Without an install ID the name has only the date and time.
        let anonymous = self.export(s, result: result, installId: nil)
        #expect(anonymous.fileName == "final-check-2026-10-06-0930.zip")
        #expect(anonymous.readme.contains("Install ID: none (this device hasn't joined the study)"))

        // The record round-trips through sitting.json.
        let files2 = FinalCheckFiles(root: folder)
        try files2.save(export)
        #expect(files2.sittings() == [export])
    }

    @Test func aSkippedTalkItemEarnsNothingAndKeepsNoRecording() async throws {
        let s = try sitting()
        try await sit(s, skipTalk: true)
        #expect(s.model.phase == .finished)
        let talk = s.events().compactMap { e -> AttemptPayload? in
            if case .attempt(let a) = e.payload, a.exerciseId == "fin.speaking.01" { a } else { nil }
        }
        #expect(talk.count == 1)
        #expect(talk.first?.outcome == .skipped && talk.first?.mode == .spoken && talk.first?.response == nil)
        #expect(s.model.recorder.answers["fin.speaking.01"] == .outcome(.skipped))
        let result = CheckScoring.scoreFinal(
            try #require(A.content.finalCheck), answers: s.model.recorder.answers, content: A.content)
        #expect(result.sections.last?.points == 0 && result.sections.last?.excluded == false)
        // The recording the learner gave up on never joins the answer, and goes with the other pending ones.
        #expect(s.model.log.answers["fin.speaking.01"]?.first?.recording == nil)
        s.recordings.discardPending()
        let left = try? FileManager.default.contentsOfDirectory(atPath: s.recordings.directory.path)
        #expect((left ?? []).isEmpty)
    }

    @Test func talkAndConversationSkipOnlyInChecks() throws {
        let talk = try PayloadFixtures.exercise("u02.task.talk")
        var practice = ExerciseEnvironment.preview(context: .lesson)
        practice.canSpeak = true
        let inLesson = try #require(TalkModel(payload: talk, env: practice, sink: nil))
        #expect(!inLesson.canSkip && inLesson.answeredLine == "Answer saved.")
        inLesson.skip()
        #expect(!inLesson.isFinished)
        var check = ExerciseEnvironment.preview(context: .check)
        check.canSpeak = true
        let recorder = RecordingAttemptSink()
        let inCheck = try #require(TalkModel(payload: talk, env: check, sink: recorder))
        #expect(inCheck.canSkip && inCheck.answeredLine == "Answer saved.")  // unit checks record no audio
        inCheck.skip()
        #expect(inCheck.isFinished && recorder.drafts.map(\.outcome) == [.skipped])

        let conversation = try PayloadFixtures.exercise("u02.l1.ex25")
        let convRecorder = RecordingAttemptSink()
        let conv = try #require(ConversationModel(payload: conversation, env: check, sink: convRecorder))
        #expect(conv.canSkip && !conv.canType)
        conv.skip()
        #expect(conv.isFinished && !conv.canSkip)
        let draft = try #require(convRecorder.drafts.first)
        #expect(draft.outcome == .skipped && draft.turnID == conv.conversation.start)
        #expect(draft.checkAnswer == .goals(completed: 0, total: conv.conversation.goals.count))
        let lesson = try #require(ConversationModel(payload: conversation, env: practice, sink: nil))
        #expect(!lesson.canSkip)
    }

    @Test func withoutSpeechTheSpeakingSectionIsLeftOutAndFlagged() async throws {
        let s = try sitting(canSpeak: false)
        #expect(s.model.excluded == ["speaking"])
        #expect(s.model.order.map(\.exercise) == A.finalSections.dropLast().flatMap(\.ids))
        try await sit(s)
        let final = try #require(A.content.finalCheck)
        let result = CheckScoring.scoreFinal(
            final, answers: s.model.recorder.answers, excludedSections: s.model.excluded, content: A.content)
        #expect(result.sections.last?.excluded == true)
        let screen = FinalCheckResultContent(result: result, titles: [:], passMark: 7)
        #expect(screen.sections.last?.score == "Not taken")
        #expect(s.model.log.recordingURLs.isEmpty)
    }

    @Test func pendingRecordingsAreReplacedAttachedOrDiscarded() throws {
        let dir = folder.appendingPathComponent("final-check/s-1")
        let r = SpeakingRecordings(directory: dir, ids: SeededUUIDSource(seed: "p"))
        let first = try #require(r.destination(for: "fin.speaking.01"))
        try Data("a".utf8).write(to: first)
        let second = try #require(r.destination(for: "fin.speaking.01"))  // nothing was heard the first time
        #expect(!FileManager.default.fileExists(atPath: first.path))
        try Data("b".utf8).write(to: second)
        let attached = try #require(r.attach(attemptID: "e-1", exercise: "fin.speaking.01"))
        #expect(attached.lastPathComponent == "fin.speaking.01-e-1.m4a" && r.byAttempt["e-1"] == attached)
        #expect(r.attach(attemptID: "e-2", exercise: "fin.speaking.01") == nil)  // no new recording
        let stray = try #require(r.destination(for: "fin.speaking.02"))
        try Data("c".utf8).write(to: stray)
        r.discardPending()
        #expect(!FileManager.default.fileExists(atPath: stray.path))
        r.delete([attached])
        #expect(!FileManager.default.fileExists(atPath: attached.path) && r.byAttempt.isEmpty)
    }

    /// docs/09, docs/12: at launch, sittings taken more than 30 days ago, folders without a record and leftover
    /// zips go; a recent sitting stays.
    @Test func sittingsGoAfterThirtyDaysAndZipsAtLaunch() async throws {
        let s = try sitting()
        try await sit(s)
        let result = CheckScoring.scoreFinal(
            try #require(A.content.finalCheck), answers: s.model.recorder.answers, content: A.content)
        let files = FinalCheckFiles(root: folder)
        let recent = export(s, result: result)
        try files.save(recent)
        let old = ExaminerExport(
            sittingId: "s-old", checkCompletedEventId: "e-old", installId: nil,
            takenAt: clock.nowMs() - 31 * 86_400_000, tzOffsetMinutes: 120, packVersion: "0.9.0", appVersion: nil,
            passMarkPerSection: 7, sections: [], result: result, formats: [:], scores: [:], checkAnswers: [:],
            answers: [:])
        try files.save(old)
        let unfinished = files.sittingDirectory("s-crashed")
        try FileManager.default.createDirectory(at: unfinished, withIntermediateDirectories: true)
        try Data("x".utf8).write(to: unfinished.appendingPathComponent("fin.speaking.01-pending-1.m4a"))
        let zip = try files.writeZip(recent)
        #expect(zip.deletingLastPathComponent() == files.exportsDirectory)
        #expect(files.sittings().map(\.sittingId) == ["s-final", "s-old"])

        #expect(files.purge(nowMs: clock.nowMs()) == 2)
        #expect(files.sittings().map(\.sittingId) == ["s-final"])
        #expect(!FileManager.default.fileExists(atPath: unfinished.path))
        #expect(!FileManager.default.fileExists(atPath: files.exportsDirectory.path))
        #expect(FileManager.default.fileExists(atPath: s.model.log.recordingURLs[0].path))
        files.deleteAll()
        #expect(files.sittings().isEmpty)
    }

    /// M1: two sittings on the same day keep their own folders and zip names.
    @Test func twoSittingsOnOneDayKeepTheirOwnFilesAndNames() async throws {
        let s = try sitting()
        try await sit(s)
        let result = CheckScoring.scoreFinal(
            try #require(A.content.finalCheck), answers: s.model.recorder.answers, content: A.content)
        let morning = export(s, result: result)
        let afternoon = ExaminerExport(
            sittingId: "s-final-2", checkCompletedEventId: "e-2", installId: "6f1c0e1a-study",
            takenAt: clock.nowMs() + 5 * 3_600_000, tzOffsetMinutes: 120, packVersion: "0.9.0", appVersion: nil,
            passMarkPerSection: 7, sections: [], result: result, formats: [:], scores: [:], checkAnswers: [:],
            answers: [:])
        #expect(morning.fileName != afternoon.fileName)
        #expect(afternoon.fileName == "final-check-6f1c0e1a-study-2026-10-06-1430.zip")
        let files = FinalCheckFiles(root: folder)
        #expect(files.sittingDirectory("s-final") != files.sittingDirectory("s-final-2"))
        try files.save(morning)
        try files.save(afternoon)
        #expect(files.sittings().map(\.sittingId) == ["s-final-2", "s-final"])
    }

    /// M6: the writer's bytes for a tiny archive are exactly the committed golden file, which
    /// `pipeline/tests/test_examiner_zip.py` reads with Python's `zipfile`.
    @Test func zipHeadersFollowTheFormat() throws {
        #expect(CRC32.checksum(Data("123456789".utf8)) == 0xCBF4_3926)
        // 6 Oct 2026, 09:30:00 at UTC+2 → DOS date (46 << 9 | 10 << 5 | 6), time (9 << 11 | 30 << 5).
        let (time, date) = StoredZip.dosDateTime(ms: 1_791_271_800_000, tzOffsetMinutes: 120)
        #expect(date == UInt16(46 << 9 | 10 << 5 | 6) && time == UInt16(9 << 11 | 30 << 5))
        let entries: [StoredZip.Entry] = [
            .init(path: "README.txt", data: Data("Italiano: final A1 check\n".utf8)),
            .init(path: "responses.json", data: Data("{\"schema\": 1}\n".utf8)),
            .init(path: "writing/è.txt", data: Data("Nome: Anna\n".utf8)),
            .init(
                path: "speaking/fin.speaking.01-e1.m4a",
                data: Data([0x00, 0x00, 0x00, 0x18, 0x66, 0x74, 0x79, 0x70, 0xFF])
            ),
            .init(path: "empty.txt", data: Data()),
        ]
        let zip = try StoredZip.archive(entries, modified: 1_791_271_800_000, tzOffsetMinutes: 120)
        let golden = try Data(
            contentsOf: PayloadFixtures.repoRoot.appendingPathComponent("fixtures/export/stored-zip-golden.zip"))
        #expect(zip == golden)
        #expect(try ZipReader.read(zip).map(\.path) == entries.map(\.path))
        #expect(throws: StoredZip.Failure.badPath("../x")) {
            try StoredZip.archive([.init(path: "../x", data: Data())], modified: 0, tzOffsetMinutes: 0)
        }
    }

    /// The app container on the mini pack: no final unit there, so nothing is offered or kept.
    @Test func theMiniPackOffersNoFinalCheck() async throws {
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let app = AppModel(
            env: .init(
                packURL: PackAdaptersTests.packURL, learnerURL: folder.appendingPathComponent("learner.sqlite"),
                clock: clock, ids: SeededUUIDSource(seed: "mini"), platform: .iPhone))
        await app.start()
        #expect(!app.offersFinalCheck(in: "u02") && !app.offersFinalCheck(in: "u99"))
        #expect(try await app.startFinalCheck() == nil)
        #expect(await app.pendingExaminerExport() == nil)
        #expect(app.finalCheckFiles?.sittingsDirectory.path == folder.appendingPathComponent("final-check").path)
    }

    // MARK: - responses.json keys

    /// Every key of every object in a JSON document, by where it sits (`items[].answers[]`).
    static func keys(_ json: Data) throws -> Set<String> {
        var out: Set<String> = []
        func walk(_ value: Any, _ path: String) {
            if let object = value as? [String: Any] {
                for (k, v) in object {
                    out.insert(path + k)
                    walk(v, path + k + (v is [Any] ? "[]." : "."))
                }
            } else if let array = value as? [Any] {
                for v in array { walk(v, path) }
            }
        }
        walk(try JSONSerialization.jsonObject(with: json), "")
        return out
    }

    /// The keys of docs/12's `responses.json` example.
    static func documentedKeys() throws -> Set<String> {
        let doc = try String(
            contentsOf: PayloadFixtures.repoRoot.appendingPathComponent("docs/12-study-privacy.md"), encoding: .utf8)
        let start = try #require(doc.range(of: "```json\n{\n  \"schema\": 1"))
        let end = try #require(doc.range(of: "\n```", range: start.upperBound..<doc.endIndex))
        let json = doc[doc.index(start.lowerBound, offsetBy: 8)..<end.lowerBound]
        return try keys(Data(json.utf8))
    }
}

import Foundation
import LearningCore
import Storage
import Testing

@testable import Italiano

/// M8.2 (docs/05 § Final A1 check, docs/06 §20, docs/09 § Transcription, docs/12 § Final check export): a sitting
/// through the real exercise models with the speaking item recorded, the score, the examiner export's exact
/// contents and its zip.
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
            directory: folder.appendingPathComponent("recordings"), ids: SeededUUIDSource(seed: "r"))
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
    /// form, and the talk task spoken once (a second try is ignored in a check).
    func sit(_ s: Sitting) async throws {
        s.model.start()
        while s.model.phase == .playing {
            switch s.model.host {
            case .choice(let m):
                m.select(s.model.currentExercise == "fin.listening.02" ? (m.correctIndex + 1) % m.options.count : m.correctIndex)
            case .writing(let m):
                m.fieldValues = ["Anna", "inglese"]
                m.submit()
                m.submit()
                #expect(m.isAssessment)
            case .talk(let m):
                #expect(!m.canType)  // speech is required in checks
                let r = try #require(await s.speech.capture(expected: [m.talk.model.text]))
                m.submitSpoken(r)
                m.submitTyped()  // no second attempt in a check
            default:
                Issue.record("unexpected item \(String(describing: s.model.currentExercise))")
            }
            s.model.advance()
        }
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
        #expect(recording.lastPathComponent == "fin.speaking.01-\(talk.0).m4a")
        #expect(FileManager.default.fileExists(atPath: recording.path))
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
            result: result, titles: Dictionary(uniqueKeysWithValues: A.finalSections.map { ($0.id, $0.title) }))
        #expect(screen.sections.map(\.score).first == "6 of 12")
        #expect(screen.headline == "Not every section reached 7 of 12 yet.")
        #expect(FinalCheckCopy.disclaimer == "This is a practice check, not an official certificate.")

        // The export: exactly README.txt, responses.json, writing/*.txt, speaking/*.m4a.
        let export = ExaminerExport(
            installId: "6f1c0e1a-study", takenAt: clock.nowMs(), tzOffsetMinutes: 120, packVersion: "0.9.0",
            appVersion: "1.0 (7)",
            sections: A.finalSections.map { .init(id: $0.id, title: $0.title, exerciseIds: $0.ids) }, result: result,
            formats: Dictionary(uniqueKeysWithValues: A.content.exercises.map { ($0.id, $0.format) }),
            scores: Dictionary(uniqueKeysWithValues: A.content.exercises.map { ($0.id, Double($0.score)) }),
            checkAnswers: s.model.recorder.answers, answers: s.model.log.answers)
        #expect(export.fileName == "final-check-6f1c0e1a-study-2026-10-06.zip")
        let entries = try export.entries()
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

        let responses = try JSONDecoder().decode(ExaminerExport.Responses.self, from: entries[1].data)
        #expect(responses.installId == "6f1c0e1a-study" && responses.takenAt == "2026-10-06T09:30:00+02:00")
        #expect(responses.sections.map(\.points) == result.sections.map(\.points))
        #expect(responses.items.map(\.exerciseId) == A.finalSections.flatMap(\.ids).map(\.rawValue))
        let listening2 = try #require(responses.items.first { $0.exerciseId == "fin.listening.02" })
        #expect(listening2.score == 2 && listening2.earned == 0 && listening2.answers.first?.outcome == "wrong")
        let spoken = try #require(responses.items.first { $0.exerciseId == "fin.speaking.01" })
        #expect(spoken.answers.count == 1)
        #expect(spoken.answers.first?.recording == "speaking/fin.speaking.01-\(talk.0).m4a")
        #expect(spoken.answers.first?.response == "Buongiorno! Quant'è?")
        #expect(responses.items.first { $0.format == "writing" }?.writingFile == "writing/fin.writing.01.txt")
        // No profile data: the name and country never go in.
        #expect(!String(decoding: entries[1].data, as: UTF8.self).contains("profile"))

        // The zip reads back with the same files and valid checksums.
        let zip = try StoredZip.archive(entries, modified: export.takenAt, tzOffsetMinutes: 120)
        let files = try ZipReader.read(zip)
        #expect(files.map(\.path) == entries.map(\.path))
        #expect(files.map(\.data) == entries.map(\.data))
        #expect(files.allSatisfy { $0.crcMatches })

        // Without an install ID the name has only the date.
        let anonymous = ExaminerExport(
            installId: nil, takenAt: clock.nowMs(), tzOffsetMinutes: 120, packVersion: "0.9.0", appVersion: nil,
            sections: [], result: result, formats: [:], scores: [:], checkAnswers: [:], answers: [:])
        #expect(anonymous.fileName == "final-check-2026-10-06.zip")
        #expect(anonymous.readme.contains("Install ID: none (this device hasn't joined the study)"))
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
        let screen = FinalCheckResultContent(result: result, titles: [:])
        #expect(screen.sections.last?.score == "Not taken")
        #expect(s.model.log.recordingURLs.isEmpty)
    }

    @Test func pendingRecordingsAreReplacedAttachedOrDiscarded() throws {
        let dir = folder.appendingPathComponent("recordings")
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

    @Test func recordingsAndExportsGoAfterThirtyDays() throws {
        let dir = folder.appendingPathComponent("recordings")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let now: Int64 = 1_791_271_800_000
        let old = dir.appendingPathComponent("old.m4a")
        let recent = dir.appendingPathComponent("recent.m4a")
        for (url, days) in [(old, 31.0), (recent, 29.0)] {
            try Data("x".utf8).write(to: url)
            try FileManager.default.setAttributes(
                [.modificationDate: Date(timeIntervalSince1970: Double(now) / 1000 - days * 86_400)],
                ofItemAtPath: url.path)
        }
        #expect(SpeakingRecordings.purge(directory: dir, nowMs: now) == 1)
        #expect(!FileManager.default.fileExists(atPath: old.path))
        #expect(FileManager.default.fileExists(atPath: recent.path))
    }

    @Test func zipHeadersFollowTheFormat() throws {
        #expect(CRC32.checksum(Data("123456789".utf8)) == 0xCBF4_3926)
        // 6 Oct 2026, 09:30:00 at UTC+2 → DOS date (46 << 9 | 10 << 5 | 6), time (9 << 11 | 30 << 5).
        let (time, date) = StoredZip.dosDateTime(ms: 1_791_271_800_000, tzOffsetMinutes: 120)
        #expect(date == UInt16(46 << 9 | 10 << 5 | 6) && time == UInt16(9 << 11 | 30 << 5))
        let zip = try StoredZip.archive(
            [.init(path: "a.txt", data: Data("ciao".utf8)), .init(path: "dir/è.txt", data: Data())],
            modified: 1_791_271_800_000, tzOffsetMinutes: 120)
        #expect(try ZipReader.read(zip).map(\.path) == ["a.txt", "dir/è.txt"])
        #expect(throws: StoredZip.Failure.badPath("../x")) {
            try StoredZip.archive([.init(path: "../x", data: Data())], modified: 0, tzOffsetMinutes: 0)
        }
    }

    /// The app container on the mini pack: no final unit there, so it isn't offered; an export written to
    /// `exports/` is the one the final review unit shares again.
    @Test func theContainerOffersAndKeepsExports() async throws {
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let app = AppModel(
            env: .init(
                packURL: PackAdaptersTests.packURL, learnerURL: folder.appendingPathComponent("learner.sqlite"),
                clock: clock, ids: SeededUUIDSource(seed: "mini"), platform: .iPhone))
        await app.start()
        #expect(!app.offersFinalCheck(in: "u02") && !app.offersFinalCheck(in: "u99"))
        #expect(try await app.startFinalCheck() == nil)
        #expect(app.latestExaminerExport == nil)
        #expect(app.recordingsDirectory?.lastPathComponent == "recordings")
        let result = CheckScoring.scoreFinal(
            try #require(A.content.finalCheck), answers: [:], content: A.content)
        let export = ExaminerExport(
            installId: nil, takenAt: clock.nowMs(), tzOffsetMinutes: 120, packVersion: "0.9.0", appVersion: nil,
            sections: [], result: result, formats: [:], scores: [:], checkAnswers: [:], answers: [:])
        let url = try app.writeExaminerExport(export)
        #expect(url.deletingLastPathComponent().lastPathComponent == "exports")
        #expect(app.latestExaminerExport == url)
        #expect(try ZipReader.read(Data(contentsOf: url)).map(\.path) == ["README.txt", "responses.json"])
    }
}

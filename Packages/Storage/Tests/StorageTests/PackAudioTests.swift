import Foundation
import LearningCore
import Testing

@testable import Storage

/// M5.1: the pack builder's audio as the reader sees it. `fixtures/packs/mini.sqlite` is built from three committed
/// mock renders (docs/04 § Pack build › Tiny test packs): the check's two-line audio text `u02.check.01.audio` with
/// every word token timed, the item `w:cornetto` and the dictation `u02.l1.ex13`; their encoded files are in
/// `fixtures/packs/Audio/`. The timings follow `PackTokenTiming`'s contract: `line` 1-based, `index` 0-based within
/// the line's tokens, media time in ms from the start of the file.
@Suite struct PackAudioTests {
    static let mini = Repo.url("fixtures/packs/mini.sqlite")
    static var hasMini: Bool { FileManager.default.fileExists(atPath: mini.path) }

    @Test(.enabled(if: hasMini))
    func theTimelineOfABuiltTextFollowsItsTokens() async throws {
        let reader = try PackReader(url: Self.mini)
        let text = try await reader.text("u02.check.01.audio")
        let audioID = try #require(text.audioId)
        let audio = try #require(try await reader.audio(audioID))
        #expect(audio.file == String(audioID.rawValue.dropFirst(2)) + ".m4a")
        #expect(audio.fileURL == reader.audioDirectory.appendingPathComponent(audio.file))
        #expect(FileManager.default.fileExists(atPath: audio.fileURL.path))
        #expect(text.durationMs == audio.durationMs && audio.durationMs > 0)
        #expect(audio.voice.hasPrefix("mock:"))  // synthetic renders say so

        #expect(text.lines.count == 2)
        for line in text.lines {
            let start = try #require(line.startMs)
            let end = try #require(line.endMs)
            #expect(start < end && end <= audio.durationMs)
            #expect(line.tokenTimings.count == line.text.tokens.count)
            for (index, (token, timing)) in zip(line.text.tokens, line.tokenTimings).enumerated() {
                if token.kind == .punct {
                    #expect(timing == nil)
                    continue
                }
                let t = try #require(timing, "\(line.number):\(index) \(token.surface) has no timing")
                #expect(t.line == line.number && t.index == index)
                #expect(start <= t.startMs && t.startMs <= t.endMs && t.endMs <= end)
            }
        }
        // Giulia, then a customer (ch:extra): the second line starts 600 ms after the first ends (docs/04 § Audio).
        let first = text.lines[0]
        let second = text.lines[1]
        #expect(try #require(second.startMs) - (try #require(first.endMs)) == 600)

        let timeline = text.timeline
        // Buongiorno, Cosa, prende · Un, caffè, e, un, cornetto, per, favore
        #expect(timeline.count == 10)
        #expect(timeline.map(\.startMs) == timeline.map(\.startMs).sorted())
        #expect(timeline.first?.line == 1 && timeline.first?.index == 0)
        #expect(timeline.last?.line == 2 && timeline.last?.index == 7)
        #expect(try await reader.timeline(forAudio: audioID) == timeline)

        let catalog = try await reader.audioCatalog()
        #expect(catalog.timeline(audioID) == timeline)
        #expect(catalog.textID(forAudio: audioID) == "u02.check.01.audio")
        #expect(catalog.audioID(forText: "u02.check.01.audio") == audioID)
        for a in catalog.audio.values {
            #expect(FileManager.default.fileExists(atPath: a.fileURL.path), "\(a.file) is missing")
        }
    }

    @Test(.enabled(if: hasMini))
    func itemsAndExercisesNameTheirFiles() async throws {
        let reader = try PackReader(url: Self.mini)
        let cornetto = try await reader.item("w:cornetto")
        let itemAudio = try #require(cornetto.audioId)
        #expect(try await reader.audio(itemAudio) != nil)
        #expect(try await reader.timeline(forAudio: itemAudio).isEmpty)  // item audio has no read-along

        let dictation = try await reader.exercise("u02.l1.ex13")
        guard case .dictation(let body) = dictation.payload.body else {
            Issue.record("u02.l1.ex13 is not a dictation")
            return
        }
        let dictationAudio = try #require(body.audioId)
        #expect(try await reader.audio(dictationAudio) != nil)

        // Not rendered for the mini pack: no audio ID, so the app shows no play button (docs/09).
        let story = try await reader.text("u02.l1.story")
        #expect(story.audioId == nil && story.timeline.isEmpty)
        #expect(try await reader.item("w:caffe").audioId == nil)
    }
}

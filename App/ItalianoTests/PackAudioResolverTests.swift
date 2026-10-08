import Foundation
import LearningCore
import Storage
import Testing

@testable import Italiano

/// The pack's audio catalog serves the exercise views' synchronous `AudioResolving` (docs/09).
@MainActor
@Suite struct PackAudioResolverTests {
    let catalog: PackAudioCatalog = {
        let fileURL = URL(fileURLWithPath: "/Content/Audio/000000000001.m4a")
        return PackAudioCatalog(
            audio: ["a:000000000001": PackAudio(id: "a:000000000001", file: "000000000001.m4a", fileURL: fileURL,
                                                durationMs: 5_000, voice: "it-IT-A", sha256: "s")],
            timelines: ["a:000000000001": [PackTokenTiming(line: 1, index: 0, startMs: 0, endMs: 300)]],
            textAudio: ["u02.l1.story": "a:000000000001"])
    }()

    @Test func clipsAndTimelinesComeFromTheCatalog() {
        let resolver: any AudioResolving = catalog
        let clip = resolver.clip(for: "a:000000000001")
        #expect(clip?.fileURL.lastPathComponent == "000000000001.m4a" && clip?.textID == "u02.l1.story")
        #expect(clip?.startMs == nil && clip?.endMs == nil)
        #expect(resolver.timeline(for: "a:000000000001") == [TokenTiming(line: 1, index: 0, startMs: 0, endMs: 300)])
        #expect(resolver.clip(for: "a:ffffffffffff") == nil && resolver.timeline(for: "a:ffffffffffff").isEmpty)
        #expect(resolver.audioID(forText: "u02.l1.story") == "a:000000000001")
        #expect(resolver.audioID(forText: "u02.l2.phone") == nil)
    }

    @Test func aPlayableCatalogDrivesExerciseAudio() {
        let audio = ExerciseAudio(player: FakeAudioPlayer(), resolver: catalog)
        #expect(audio.canPlay("a:000000000001") && !audio.canPlay(nil) && !audio.canPlay("a:ffffffffffff"))
        #expect(audio.play("a:000000000001") && audio.plays(of: "a:000000000001") == 1)
    }
}

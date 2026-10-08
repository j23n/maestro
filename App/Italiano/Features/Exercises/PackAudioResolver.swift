import Foundation
import LearningCore
import Storage

// The pack's audio as exercises and the read-along use it (docs/09). Pack queries are async, so the synchronous
// `AudioResolving` is served by the catalog the app loads once at launch (`PackReader.audioCatalog()`).

extension PackAudioCatalog: AudioResolving {
    /// The whole file; nil when the pack has no row for the ID (no speaker button).
    func clip(for id: AudioID) -> AudioClip? {
        audio(id).map { AudioClip(audioID: id.rawValue, fileURL: $0.fileURL, textID: textID(forAudio: id)?.rawValue) }
    }

    /// The read-along timeline of a text's audio; empty for item and exercise audio.
    func timeline(for id: AudioID) -> [TokenTiming] {
        timeline(id).map { TokenTiming(line: $0.line, index: $0.index, startMs: $0.startMs, endMs: $0.endMs) }
    }

    // `audioID(forText:)` is the catalog's own (`texts.audio_id`).
}

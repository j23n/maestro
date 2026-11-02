import Foundation
import Testing
@testable import PackKit

@Suite struct VoiceCastingTests {
    let federica = VoiceCasting.Voice(id: "federica", gender: .female, quality: 3)
    let alice = VoiceCasting.Voice(id: "alice", gender: .female, quality: 1)
    let luca = VoiceCasting.Voice(id: "luca", gender: .male, quality: 1)

    func speaker(_ name: String, _ gender: SpeakerGender?) -> VoiceCasting.Speaker {
        VoiceCasting.Speaker(name: name, gender: gender)
    }

    @Test func narratorIsTheBestVoice() {
        #expect(VoiceCasting.narrator([alice, luca, federica])?.id == "federica")
        #expect(VoiceCasting.narrator([]) == nil)
    }

    @Test func speakersGetAVoiceOfTheirGender() {
        let parts = VoiceCasting.cast([speaker("Barista", .male), speaker("Marta", .female)],
                                      voices: [alice, luca, federica])
        #expect(parts["Barista"]?.voiceID == "luca")
        #expect(parts["Marta"]?.voiceID == "federica")
        #expect(parts.values.allSatisfy { $0.pitch == 1 })
    }

    @Test func twoWomenGetTwoFemaleVoices() {
        let parts = VoiceCasting.cast([speaker("Chiara", .female), speaker("Sara", .female)],
                                      voices: [alice, luca, federica])
        #expect(parts["Chiara"]?.voiceID == "federica")
        #expect(parts["Sara"]?.voiceID == "alice")
    }

    @Test func speakersSharingTheOnlyVoiceOfTheirGenderDifferInPitch() {
        let parts = VoiceCasting.cast([speaker("Chiara", .female), speaker("Sara", .female)], voices: [alice, luca])
        #expect(parts["Chiara"] == VoiceCasting.Part(voiceID: "alice", pitch: 1))
        #expect(parts["Sara"]?.voiceID == "alice")
        #expect(parts["Sara"]?.pitch != 1)
    }

    @Test func aGenderWithNoVoiceFallsBackToTheLeastUsedVoice() {
        let parts = VoiceCasting.cast([speaker("Marta", .female), speaker("Paolo", .male)], voices: [federica, alice])
        #expect(parts["Marta"]?.voiceID == "federica")
        #expect(parts["Paolo"]?.voiceID == "alice")
    }

    @Test func speakersWithoutAGenderAlternateVoices() {
        let parts = VoiceCasting.cast([speaker("A", nil), speaker("B", nil), speaker("C", nil)],
                                      voices: [alice, federica])
        #expect(parts["A"]?.voiceID == "federica")
        #expect(parts["B"]?.voiceID == "alice")
        #expect(parts["C"] == VoiceCasting.Part(voiceID: "federica", pitch: 1.12))
    }

    @Test func noVoicesMeansNoParts() {
        #expect(VoiceCasting.cast([speaker("Marta", .female)], voices: []).isEmpty)
    }

    @Test func dialogueBlocksDecodeTheirGender() throws {
        let json = #"[{"type":"dialogue","speaker":"Marta","gender":"f","text":"","sentences":[]},"#
            + #"{"type":"dialogue","speaker":"Io","text":"","sentences":[]}]"#
        let blocks = try JSONDecoder().decode([Block].self, from: Data(json.utf8))
        #expect(blocks.map(\.speakerGender) == [.female, nil])
    }
}

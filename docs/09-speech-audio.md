# 09 · Audio playback and speech recognition

## Playback (`AudioPlaying`, App `Platform/Audio/`)

- All course audio is pre-rendered `.m4a` in the bundle under `Content/Audio/`. Always use the `audio.file` column (`3f9c0e1a2b4d.m4a`, the audio ID without `a:`); nothing is synthesised at runtime.
- Use `AVPlayer` with `audioTimePitchAlgorithm = .timeDomain` (good for speech) and rates 0.75 / 0.8 / 1.0 / 1.15 / 1.25.
- **Read-along:** a periodic time observer every 30 ms maps media time to a token by binary search over `tokens.start_ms`, and publishes `currentToken` (line, index). Media time is independent of rate, so timings need no scaling.
- **Segments:** play a line (`text_lines.start_ms…end_ms`) or a single word (the token slice, padded 40 ms each side). For item audio, prefer the item's own file.
- **Audio session (iOS and iPadOS):**
  - Playback: category `.playback`, mode `.spokenAudio`. Play even with the ring switch on silent.
  - Recording: switch to `.playAndRecord` with `.defaultToSpeaker` and `.allowBluetoothHFP` (a Bluetooth headset microphone needs HFP; `.allowBluetoothA2DP` is output only — verify the option name in the iOS 26 SDK), and switch back afterwards.
  - Respect interruptions (calls) by pausing.
  - macOS has no `AVAudioSession`; abstract it.
- **`audioPlayed` events** are written when playback stops: `playedMs` is wall time spent playing (fluency replay uses it).
- **Never block the UI on audio:** dev packs may have `audio_id` NULL (audio not rendered yet). Then hide the play button and, in debug builds, show a small "audio not rendered yet" label. Release builds guarantee every file exists (`docs/04`).
- **Encoder delay:** files are encoded once per text (`docs/04` § Audio), so the MP4 edit list must be honoured; a test (M5.2) checks that a token's highlight starts within 50 ms of its `start_ms`.

## Speech recognition (`SpeechRecognizing`, App `Platform/Speech/`)

Apple ships on-device recognition through **SpeechAnalyzer + SpeechTranscriber** (Speech framework, iOS, iPadOS and macOS 26+; also native on the Mac).

### Availability (check at runtime, never assume)

```swift
guard SpeechTranscriber.isAvailable else { return .unsupported }            // false in the Simulator
guard let locale = await SpeechTranscriber.supportedLocale(equivalentTo: Locale(identifier: "it-IT"))
else { return .unsupported }
let installed = await SpeechTranscriber.installedLocales
// not installed → .needsDownload
```

- **Reserve the locale** with `AssetInventory.reserve(locale:)` every time, even when it is already installed: reservations are automatic only through installation requests, and unreserved locales log "Cannot use modules with unallocated locales" (an error in a future release). Check state with `AssetInventory.status(forModules:)`.
- **Download** assets with `AssetInventory.assetInstallationRequest(supporting: [transcriber])` and `downloadAndInstall()`, showing `progress`. A `nil` request means nothing to download. Models are system-managed and shared.
- Verify these API names against the iOS 26 SDK in M5.3 and record any differences in PROGRESS.md.
- **Fallback:** if `SpeechTranscriber` is unsupported but `DictationTranscriber` supports it-IT, use it. You may pass `AnalysisContext.contextualStrings` (≤ 100 phrases) with the expected answers; this is documented for DictationTranscriber only.
- **If neither works:** speaking UI is hidden in practice. Repeat-after-me becomes listen-and-repeat, and check speaking sections are excluded (`docs/05`). Settings shows "Speaking isn't available on this device".
- Apple publishes no static locale list; Italian is in the launch set and `it_IT` appears in `supportedLocales` reports, but trust only the runtime answer.

### Transcription

- Create **one** `SpeechTranscriber` per recording that gives both the live transcript and the graded alternatives: volatile (progressive) results for the live view, plus alternative transcriptions and confidence on the final result. Build it from options rather than two presets (in the iOS 26 SDK: `reportingOptions` with volatile results and alternative transcriptions, `attributeOptions` with transcription confidence; verify the names). Running two transcribers on one stream doubles the cost and can disagree.
- Feed microphone audio through `AVAudioEngine`, converting buffers to `SpeechAnalyzer.bestAvailableAudioFormat(compatibleWith:)`. The iOS 27 input providers are 27-only, so don't use them while the target is 26.
- Results arrive as an `AttributedString`; use its characters and the alternatives array.
- Stop when there is 1.2 s of silence after speech (energy threshold on the input tap), on the 10 s limit, or when the learner taps stop.
- Return `SpeechResult { transcript, alternatives, confidence? }` to the grader (`TranscriptMatcher`, `docs/05`).
- **Recordings:** practice recordings live in a temp file only for "hear yourself" (P1) and are deleted when the session ends. **Final-check speaking items always record** to `Application Support/Italiano/recordings/<exerciseId>-<attemptId>.m4a` on the recording device (they are not synced), for the examiner export (`docs/12`); they are deleted 30 days after the check or after a successful export, whichever comes first.

### Permissions

- Info.plist: `NSMicrophoneUsageDescription` ("Italiano listens when you practise speaking. Recognition happens on your device.") and `NSSpeechRecognitionUsageDescription` (keep it; verify on device in M5.3 whether SpeechAnalyzer requires speech authorisation, and record the finding in PROGRESS.md).
- Ask for the microphone the first time the learner taps a mic button, never at launch.

### Testing

- The Simulator can't run SpeechTranscriber. Use `FakeSpeechRecognizer` (scripted transcripts) in tests and previews, and the Debug menu "Type to simulate speech" in debug builds.
- On-device test matrix (M5.3 and M9, owner): iPhone, iPad and Mac, with a quiet room and with background noise. Record transcripts for 30 fixed learner sentences (`fixtures/speech/sentences.txt`, written in M5.3) and tune the 80% threshold only from that data.

### What speech grading may and may not claim

- It may say "I heard: …" and mark which expected words were found.
- It never says "your pronunciation is wrong". It never judges double consonants, vowel openness or stress (ASR guesses from context). These are trained by sound pairs and listening.
- A failed speaking attempt never becomes an FSRS lapse (ADR-08).

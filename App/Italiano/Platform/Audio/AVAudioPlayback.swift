import AVFoundation
import Foundation
import LearningCore
import Observation
import os

// The real `AudioPlaying` (docs/09 § Playback): AVPlayer with time-domain pitch correction, a 30 ms periodic time
// observer for read-along, segment playback (a line or a padded word), the iOS audio session for playback and
// recording, and pausing on interruptions. macOS has no AVAudioSession, so the session code is iOS-only.
// The MP4 edit list (encoder delay) is honoured by AVPlayer; M5.2's device check confirms it within 50 ms.

private let audioLogger = Logger(subsystem: "com.j23n.italian", category: "audio")

@MainActor
@Observable
final class AVAudioPlayback: AudioPlaying {
    private(set) var isPlaying = false
    private(set) var positionMs = 0
    private(set) var durationMs = 0
    private(set) var rate = 1.0
    private(set) var currentToken: TokenPosition?
    var onStop: (@MainActor (PlaybackReport) -> Void)?

    @ObservationIgnored private let player = AVPlayer()
    @ObservationIgnored private var timeObserver: Any?
    @ObservationIgnored private var endObserver: NSObjectProtocol?
    @ObservationIgnored private var interruptionObserver: NSObjectProtocol?
    @ObservationIgnored private var clip: AudioClip?
    @ObservationIgnored private var timeline: [TokenTiming] = []
    @ObservationIgnored private var context: AudioContext = .item
    @ObservationIgnored private var playStartedAt: ContinuousClock.Instant?
    @ObservationIgnored private var playedMs = 0

    init() {
        player.automaticallyWaitsToMinimizeStalling = false
        let interval = CMTime(value: 30, timescale: 1000)  // 30 ms (docs/09 § Read-along)
        timeObserver = player.addPeriodicTimeObserver(forInterval: interval, queue: .main) { [weak self] time in
            MainActor.assumeIsolated { self?.tick(time) }
        }
        #if os(iOS)
            interruptionObserver = NotificationCenter.default.addObserver(
                forName: AVAudioSession.interruptionNotification, object: nil, queue: .main
            ) { [weak self] note in
                let began =
                    (note.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt)
                    .flatMap(AVAudioSession.InterruptionType.init(rawValue:)) == .began
                MainActor.assumeIsolated { if began { self?.pause() } }
            }
        #endif
    }

    func play(_ clip: AudioClip, timeline: [TokenTiming], rate: Double, context: AudioContext) {
        if isPlaying || self.clip != nil { stop() }
        AudioSessionConfigurator.activateForPlayback()
        self.clip = clip
        self.timeline = timeline.sorted { $0.startMs < $1.startMs }
        self.context = context
        self.rate = rate
        playedMs = 0
        let item = AVPlayerItem(url: clip.fileURL)
        item.audioTimePitchAlgorithm = .timeDomain  // good for speech at 0.75–1.25×
        if let end = clip.endMs {
            item.forwardPlaybackEndTime = CMTime(value: CMTimeValue(end), timescale: 1000)
        }
        player.replaceCurrentItem(with: item)
        if let observer = endObserver { NotificationCenter.default.removeObserver(observer) }
        endObserver = NotificationCenter.default.addObserver(
            forName: AVPlayerItem.didPlayToEndTimeNotification, object: item, queue: .main
        ) { [weak self] _ in
            MainActor.assumeIsolated { self?.stop() }
        }
        durationMs = clip.endMs ?? Int((item.asset.duration.seconds * 1000).rounded())
        let start = CMTime(value: CMTimeValue(clip.startMs ?? 0), timescale: 1000)
        player.seek(to: start, toleranceBefore: .zero, toleranceAfter: .zero) { [weak self] _ in
            Task { @MainActor in self?.startPlaying() }
        }
    }

    private func startPlaying() {
        guard clip != nil else { return }
        player.playImmediately(atRate: Float(rate))
        isPlaying = true
        playStartedAt = .now
    }

    func pause() {
        guard isPlaying else { return }
        player.pause()
        accumulateWallTime()
        isPlaying = false
    }

    func resume() {
        guard clip != nil, !isPlaying else { return }
        player.playImmediately(atRate: Float(rate))
        isPlaying = true
        playStartedAt = .now
    }

    func seek(toMs ms: Int) {
        player.seek(to: CMTime(value: CMTimeValue(ms), timescale: 1000), toleranceBefore: .zero, toleranceAfter: .zero)
        positionMs = ms
        currentToken = ReadAlong.token(atMs: ms, in: timeline)
    }

    func setRate(_ rate: Double) {
        self.rate = rate
        if isPlaying { player.rate = Float(rate) }
    }

    func stop() {
        guard let clip else { return }
        if isPlaying { accumulateWallTime() }
        player.pause()
        isPlaying = false
        currentToken = nil
        self.clip = nil
        onStop?(
            PlaybackReport(
                audioID: clip.audioID, textID: clip.textID, rate: rate, playedMs: playedMs,
                context: context))
    }

    private func accumulateWallTime() {
        if let started = playStartedAt {
            let d = ContinuousClock.now - started
            playedMs += Int(d.components.seconds * 1000 + d.components.attoseconds / 1_000_000_000_000_000)
        }
        playStartedAt = nil
    }

    private func tick(_ time: CMTime) {
        guard clip != nil else { return }
        let ms = Int((time.seconds * 1000).rounded())
        positionMs = ms
        let token = isPlaying ? ReadAlong.token(atMs: ms, in: timeline) : nil
        if token != currentToken { currentToken = token }
    }
}

/// docs/09 § Audio session (iOS and iPadOS only; macOS has none).
enum AudioSessionConfigurator {
    @MainActor
    static func activateForPlayback() {
        #if os(iOS)
            do {
                let session = AVAudioSession.sharedInstance()
                try session.setCategory(.playback, mode: .spokenAudio)  // plays with the ring switch on silent
                try session.setActive(true)
            } catch {
                audioLogger.error("playback session: \(error.localizedDescription, privacy: .public)")
            }
        #endif
    }

    @MainActor
    static func activateForRecording() {
        #if os(iOS)
            do {
                let session = AVAudioSession.sharedInstance()
                // A Bluetooth headset microphone needs HFP; A2DP is output only (verify the option name, M5.3).
                try session.setCategory(
                    .playAndRecord, mode: .spokenAudio,
                    options: [.defaultToSpeaker, .allowBluetoothHFP])
                try session.setActive(true)
            } catch {
                audioLogger.error("recording session: \(error.localizedDescription, privacy: .public)")
            }
        #endif
    }
}

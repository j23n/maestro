import Foundation

// Sharing a file through the system share sheet and learning how it ended (docs/12 § Final check export): the
// examiner export deletes the speaking recordings only after a share that completed. The real adapter is
// `SystemExportSharing` (UIActivityViewController on iOS, NSSharingServicePicker on the Mac); tests and previews use
// `FakeExportSharing`. Everything here is platform-neutral.

/// How a share ended. Only `completed` is a successful export: the system says the file went somewhere (sent,
/// saved, AirDropped). Closing the sheet, cancelling the chosen service, or a service that failed is `cancelled`.
enum ShareOutcome: Sendable, Equatable {
    case completed
    case cancelled
}

@MainActor
protocol ExportSharing: AnyObject {
    /// Shows the share sheet with `file` and returns when the learner finished or dismissed it. The file must stay
    /// in place until then.
    func share(_ file: URL) async -> ShareOutcome
}

/// Answers every share with `outcome`, keeping the name and bytes of each file it was given.
@MainActor
final class FakeExportSharing: ExportSharing {
    struct Shared: Equatable {
        let name: String
        let data: Data?
    }

    var outcome: ShareOutcome
    private(set) var shared: [Shared] = []

    init(outcome: ShareOutcome = .cancelled) { self.outcome = outcome }

    func share(_ file: URL) async -> ShareOutcome {
        shared.append(Shared(name: file.lastPathComponent, data: try? Data(contentsOf: file)))
        return outcome
    }
}

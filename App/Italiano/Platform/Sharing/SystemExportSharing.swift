import Foundation
import Synchronization

#if os(macOS)
    import AppKit
#else
    import UIKit
#endif

/// The system share sheet, reporting how it ended (`ExportSharing`; docs/12 § Final check export).
///
/// - iOS and iPadOS: `UIActivityViewController`; its `completionWithItemsHandler` says whether an activity
///   completed (sent, saved to Files, AirDropped) or the sheet was dismissed. On iPad it is a popover in the middle
///   of the screen.
/// - macOS: `NSSharingServicePicker` from the key window. `sharingServicePicker(_:didChoose:)` without a service is a
///   cancel; a chosen service reports through its delegate (`sharingServicePicker(_:delegateFor:)` returns this
///   object): `sharingService(_:didShareItems:)` is a completed share, `sharingService(_:didFailToShareItems:error:)`
///   (which includes the learner cancelling the service's own window) a cancelled one. A service that never reports
///   back leaves the share open until the next one, which ends it as cancelled.
@MainActor
final class SystemExportSharing: NSObject, ExportSharing {
    private var pending: OneShot?
    #if os(macOS)
        private var picker: NSSharingServicePicker?
    #endif

    func share(_ file: URL) async -> ShareOutcome {
        finish(.cancelled)  // a share that never reported back
        return await withCheckedContinuation { continuation in
            let once = OneShot(continuation)
            pending = once
            if !present(file, once: once) { finish(.cancelled) }
        }
    }

    private func finish(_ outcome: ShareOutcome) {
        pending?.resume(outcome)
        pending = nil
        #if os(macOS)
            picker = nil
        #endif
    }

    #if os(macOS)
        private func present(_ file: URL, once: OneShot) -> Bool {
            guard let view = NSApp.keyWindow?.contentView ?? NSApp.mainWindow?.contentView else { return false }
            let picker = NSSharingServicePicker(items: [file])
            picker.delegate = self
            self.picker = picker
            picker.show(
                relativeTo: NSRect(x: view.bounds.midX, y: view.bounds.midY, width: 1, height: 1), of: view,
                preferredEdge: .minY)
            return true
        }
    #else
        private func present(_ file: URL, once: OneShot) -> Bool {
            guard let presenter = Self.presenter() else { return false }
            let controller = UIActivityViewController(activityItems: [file], applicationActivities: nil)
            controller.completionWithItemsHandler = { _, completed, _, _ in
                once.resume(completed ? .completed : .cancelled)
            }
            if let popover = controller.popoverPresentationController {
                let bounds = presenter.view.bounds
                popover.sourceView = presenter.view
                popover.sourceRect = CGRect(x: bounds.midX, y: bounds.midY, width: 1, height: 1)
                popover.permittedArrowDirections = []
            }
            presenter.present(controller, animated: true)
            return true
        }

        /// The view controller in front: the key window's root, then whatever it presents (the final check's cover).
        private static func presenter() -> UIViewController? {
            let scenes = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
            let window = scenes.flatMap(\.windows).first(where: \.isKeyWindow) ?? scenes.first?.windows.first
            var top = window?.rootViewController
            while let presented = top?.presentedViewController { top = presented }
            return top
        }
    #endif
}

#if os(macOS)
    extension SystemExportSharing: NSSharingServicePickerDelegate, NSSharingServiceDelegate {
        nonisolated func sharingServicePicker(_ picker: NSSharingServicePicker, didChoose service: NSSharingService?) {
            guard service == nil else { return }  // a chosen service reports through its delegate
            MainActor.assumeIsolated { finish(.cancelled) }
        }

        nonisolated func sharingServicePicker(
            _ picker: NSSharingServicePicker, delegateFor sharingService: NSSharingService
        ) -> (any NSSharingServiceDelegate)? {
            MainActor.assumeIsolated { self }
        }

        nonisolated func sharingService(_ sharingService: NSSharingService, didShareItems items: [Any]) {
            MainActor.assumeIsolated { finish(.completed) }
        }

        nonisolated func sharingService(
            _ sharingService: NSSharingService, didFailToShareItems items: [Any], error: any Error
        ) {
            MainActor.assumeIsolated { finish(.cancelled) }
        }
    }
#endif

/// Resumes a share's continuation once, whichever callback comes first.
private final class OneShot: Sendable {
    private let continuation: Mutex<CheckedContinuation<ShareOutcome, Never>?>

    init(_ continuation: CheckedContinuation<ShareOutcome, Never>) { self.continuation = Mutex(continuation) }

    func resume(_ outcome: ShareOutcome) {
        continuation.withLock { $0.take() }?.resume(returning: outcome)
    }
}

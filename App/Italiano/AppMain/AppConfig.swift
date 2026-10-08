import Foundation

/// Build-time switches read from Info.plist keys that the App/Config/*.xcconfig files set (docs/02 § App
/// configuration). Construct it from `Bundle.main.infoDictionary`; tests pass a dictionary.
struct AppConfig: Sendable, Equatable {
    /// Which pack the build bundles: the dev pack (drafts included) or the release pack (approved only).
    enum Pack: String, Sendable { case dev, release }

    var studyBuild: Bool
    var telemetryURL: URL?
    var debugMenu: Bool
    var llmHints: Bool
    var syncEnabled: Bool
    /// The build is signed with `Italiano.entitlements` (iCloud). The owner's Signing.xcconfig sets
    /// `ITA_ICLOUD_ENTITLEMENT = YES` together with `CODE_SIGN_ENTITLEMENTS`; iOS has no public API to read a
    /// running app's entitlements, and `CKContainer` crashes without them (docs/02).
    var iCloudEntitlement: Bool
    var reviewMode: Bool
    var reviewURL: URL?
    var studyToken: String?
    var reviewToken: String?
    var pack: Pack

    init(info: [String: Any]) {
        func flag(_ key: String) -> Bool {
            if let b = info[key] as? Bool { return b }
            return (info[key] as? String)?.uppercased() == "YES"
        }
        func string(_ key: String) -> String? {
            guard let s = (info[key] as? String)?.trimmingCharacters(in: .whitespaces), !s.isEmpty,
                !s.hasPrefix("$(")
            else { return nil }
            return s
        }
        func url(_ key: String) -> URL? {
            guard let s = string(key), let u = URL(string: s), u.scheme == "https" || u.scheme == "http" else {
                return nil
            }
            return u
        }
        studyBuild = flag("ITA_STUDY_BUILD")
        telemetryURL = url("ITA_TELEMETRY_URL")
        debugMenu = flag("ITA_DEBUG_MENU")
        llmHints = flag("ITA_LLM_HINTS") && !flag("ITA_STUDY_BUILD")  // ADR-10: never in study builds
        syncEnabled = flag("ITA_SYNC_ENABLED")
        iCloudEntitlement = flag("ITA_ICLOUD_ENTITLEMENT")
        reviewURL = url("ITA_REVIEW_URL")
        studyToken = string("ITA_STUDY_TOKEN")
        reviewToken = string("ITA_REVIEW_TOKEN")
        pack = Pack(rawValue: (string("ITA_PACK") ?? "dev").lowercased()) ?? .dev
        // Learners never get review mode (M6.10): not in study builds, nor in any build that bundles the release
        // pack (Release and Study), whatever ITA_REVIEW_MODE says.
        reviewMode = flag("ITA_REVIEW_MODE") && !flag("ITA_STUDY_BUILD") && pack != .release
    }

    static func fromMainBundle() -> AppConfig { AppConfig(info: Bundle.main.infoDictionary ?? [:]) }

    /// Uploads happen only in study builds with an endpoint and a token, and only after consent (docs/12).
    var canUploadTelemetry: Bool { studyBuild && telemetryURL != nil && studyToken != nil && !reviewMode }

    /// Review builds send comments only with an endpoint and a token; Export always works (docs/04).
    var canSendReviewComments: Bool { reviewMode && reviewURL != nil && reviewToken != nil }

    /// Sync runs only when the build allows it AND the iCloud entitlement is present (CKContainer crashes without
    /// it; docs/02). The caller passes whether the entitlement is there.
    func syncAllowed(hasICloudEntitlement: Bool) -> Bool { syncEnabled && hasICloudEntitlement && !reviewMode }

    /// Whether this build runs `CloudSync` (otherwise `DisabledSync`: "Sync off in this build").
    var syncAllowed: Bool { syncAllowed(hasICloudEntitlement: iCloudEntitlement) }

    /// Fakes and previews.
    static let preview = AppConfig(info: [
        "ITA_DEBUG_MENU": "YES", "ITA_LLM_HINTS": "NO", "ITA_REVIEW_MODE": "NO", "ITA_PACK": "dev",
    ])
}

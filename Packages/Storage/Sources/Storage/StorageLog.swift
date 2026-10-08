import Foundation

#if canImport(os)
import os
#endif

/// Storage's logging (docs/02 § Logging and errors): `os.Logger`, subsystem `com.j23n.italian`, one category per
/// area. On Linux (tests and CI) there is no `os`, so it logs nothing. Never log learner free text.
enum StorageLog {
    #if canImport(os)
    static let pack = Logger(subsystem: "com.j23n.italian", category: "pack")
    #endif

    /// The pack could not be opened (the App shows the pack error screen).
    static func packFailed(_ error: PackError) {
        #if canImport(os)
        pack.error("content pack refused: \(error.description, privacy: .public)")
        #endif
    }
}

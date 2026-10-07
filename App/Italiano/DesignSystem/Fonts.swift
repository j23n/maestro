import CoreText
import Foundation
import os

private let fontLogger = Logger(subsystem: "com.j23n.italian", category: "fonts")

/// Registers Literata and Instrument Sans (OFL, ADR-12) at launch with `CTFontManagerRegisterFontURLs` on every
/// platform (docs/07: no Info.plist keys; `ATSApplicationFontsPath` is easy to get wrong on macOS).
@MainActor
enum FontRegistry {
    private static var registered = false

    static func registerBundledFonts(bundle: Bundle = .main) {
        guard !registered else { return }
        registered = true
        let urls = Tokens.FontFamily.files.compactMap { name -> URL? in
            let base = (name as NSString).deletingPathExtension
            return bundle.url(forResource: base, withExtension: "ttf")
                ?? bundle.url(forResource: base, withExtension: "ttf", subdirectory: "Fonts")
        }
        if urls.count != Tokens.FontFamily.files.count {
            fontLogger.error("missing bundled fonts: found \(urls.count) of \(Tokens.FontFamily.files.count)")
        }
        CTFontManagerRegisterFontURLs(urls as CFArray, .process, true) { errors, _ in
            // "Already registered" is harmless (previews, tests); anything else is worth knowing.
            for error in errors as NSArray {
                fontLogger.error("font registration: \(String(describing: error), privacy: .public)")
            }
            return true
        }
    }
}

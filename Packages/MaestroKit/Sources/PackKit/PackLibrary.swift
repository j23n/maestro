import Foundation
import ItalianCore

public enum PackError: Error, CustomStringConvertible {
    case unsupportedFormat(String, Int)
    case missingText(String)

    public var description: String {
        switch self {
        case .unsupportedFormat(let id, let v): "Pack \(id) has format version \(v), which this app can't read"
        case .missingText(let id): "Text \(id) isn't in any downloaded pack"
        }
    }
}

/// A pack folder on disk: manifest.json plus texts/<id>.json.
public struct LoadedPack: Sendable, Hashable, Identifiable {
    public let manifest: PackManifest
    public let directory: URL
    public var id: String { manifest.id }
}

/// Every pack found under the given folders (bundled starters, then downloaded packs).
public struct PackLibrary: Sendable {
    public static let supportedFormatVersion = 1

    public let packs: [LoadedPack]

    public init(packs: [LoadedPack]) {
        self.packs = packs
    }

    public init(directories: [URL]) {
        var found: [LoadedPack] = []
        let fm = FileManager.default
        for dir in directories {
            guard let children = try? fm.contentsOfDirectory(at: dir, includingPropertiesForKeys: nil) else { continue }
            for child in children.sorted(by: { $0.lastPathComponent < $1.lastPathComponent }) {
                let manifestURL = child.appendingPathComponent("manifest.json")
                guard let data = try? Data(contentsOf: manifestURL),
                      let manifest = try? JSONDecoder().decode(PackManifest.self, from: data),
                      manifest.formatVersion <= Self.supportedFormatVersion,
                      !found.contains(where: { $0.id == manifest.id }) else { continue }
                found.append(LoadedPack(manifest: manifest, directory: child))
            }
        }
        packs = found
    }

    /// All texts, ordered by level, then pack, then order.
    public var entries: [(pack: LoadedPack, text: PackManifest.TextEntry)] {
        packs.flatMap { pack in pack.manifest.texts.map { (pack, $0) } }
            .sorted { a, b in
                let la = Level(rawValue: a.text.level ?? a.pack.manifest.level) ?? .b2
                let lb = Level(rawValue: b.text.level ?? b.pack.manifest.level) ?? .b2
                if la != lb { return la < lb }
                if a.pack.id != b.pack.id { return a.pack.id < b.pack.id }
                return a.text.order < b.text.order
            }
    }

    /// Texts whose feature window holds the date, such as the winter texts in December.
    public func featured(on date: Date, calendar: Calendar = .current)
        -> [(pack: LoadedPack, text: PackManifest.TextEntry)] {
        entries.filter { $0.text.featureWindow?.contains(date, calendar: calendar) ?? false }
    }

    public func entry(for textID: String) -> (pack: LoadedPack, text: PackManifest.TextEntry)? {
        entries.first { $0.text.id == textID }
    }

    public func load(_ textID: String) throws -> ReadingText {
        guard let found = entry(for: textID) else { throw PackError.missingText(textID) }
        let url = found.pack.directory.appendingPathComponent(found.text.file)
        return try JSONDecoder().decode(ReadingText.self, from: Data(contentsOf: url))
    }
}

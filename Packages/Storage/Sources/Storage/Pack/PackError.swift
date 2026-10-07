import Foundation
import GRDB

/// Everything that can go wrong reading the content pack (docs/02 § Logging and errors). The App maps
/// `schemaMismatch` to the blocking "Please update the app" screen (`error.packMismatch`, task M3.9), and
/// `fileMissing` / `notAContentPack` to the pack error screen that names the fix (`make pack`).
public enum PackError: Error, Sendable, Equatable, CustomStringConvertible {
    /// No file at the path: the pack wasn't built or bundled.
    case fileMissing(path: String)
    /// SQLite can't read the file, or it isn't a content pack this reader understands: no `meta`, a required meta
    /// key missing or malformed, a missing table, or a query that doesn't fit the tables.
    case notAContentPack(path: String, reason: String)
    /// The pack's `meta.schema_version` isn't the one this app reads (docs/03 § The compiled content pack).
    case schemaMismatch(pack: Int, app: Int)
    /// No row with this ID in `table`.
    case notFound(table: String, id: String)
    /// A row whose columns or JSON don't decode, or whose payload contradicts its columns: a pack-builder bug,
    /// caught by the pack tests (every payload in `fixtures/packs/mini.sqlite` decodes).
    case malformedRow(table: String, id: String, reason: String)
    /// Any other SQLite error while querying.
    case database(String)

    public var description: String {
        switch self {
        case .fileMissing(let path): "no content pack at \(path)"
        case .notAContentPack(let path, let reason): "\(path) is not a readable content pack: \(reason)"
        case .schemaMismatch(let pack, let app): "the content pack has schema version \(pack); this app reads \(app)"
        case .notFound(let table, let id): "\(table): no row \(id)"
        case .malformedRow(let table, let id, let reason): "\(table) \(id): \(reason)"
        case .database(let message): "content pack query failed: \(message)"
        }
    }

    /// Any error thrown inside a pack read, as a `PackError`.
    static func wrap(_ error: any Error) -> PackError {
        switch error {
        case let e as PackError: e
        case let e as DatabaseError: .database(e.description)
        default: .database(String(describing: error))
        }
    }
}

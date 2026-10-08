import Foundation

/// A value guarded by a lock, for the little state `LearnerStore` keeps in memory between writes.
///
/// `@unchecked Sendable`: every access to `value` goes through `lock`, and `Value` itself is `Sendable`, so sharing
/// the box across threads is safe. (Storage imports only Foundation, GRDB and os, so no `Synchronization.Mutex`.)
final class Locked<Value: Sendable>: @unchecked Sendable {
    private let lock = NSLock()
    private var value: Value

    init(_ value: Value) { self.value = value }

    func withLock<T>(_ body: (inout Value) throws -> T) rethrows -> T {
        lock.lock()
        defer { lock.unlock() }
        return try body(&value)
    }

    var current: Value { withLock { $0 } }
}

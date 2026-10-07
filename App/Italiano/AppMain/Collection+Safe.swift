import Foundation

extension Array {
    /// The element at `index`, or nil when it is out of range (content counts can disagree with a stale pack).
    subscript(safe index: Int) -> Element? { indices.contains(index) ? self[index] : nil }
}

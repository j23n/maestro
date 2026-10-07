import Foundation
import Testing

@testable import Storage

@Suite struct StorageSmokeTests {
    @Test func grdbOpensAnInMemoryDatabase() throws {
        let version = try StorageInfo.sqliteVersion()
        #expect(version.hasPrefix("3."))
    }
}

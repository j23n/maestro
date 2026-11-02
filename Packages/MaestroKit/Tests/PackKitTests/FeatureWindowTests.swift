import Foundation
import Testing
@testable import PackKit

@Suite struct FeatureWindowTests {
    let calendar: Calendar = {
        var c = Calendar(identifier: .gregorian)
        c.timeZone = TimeZone(identifier: "Europe/Rome") ?? .current
        return c
    }()

    func date(_ y: Int, _ m: Int, _ d: Int) throws -> Date {
        try #require(calendar.date(from: DateComponents(year: y, month: m, day: d, hour: 12)))
    }

    @Test func parsesBothKindsOfDay() throws {
        let winter = try #require(FeatureWindow("12-01..01-06"))
        #expect(winter.start == .fixed(month: 12, day: 1))
        #expect(winter.end == .fixed(month: 1, day: 6))
        let carnevale = try #require(FeatureWindow("easter-60..easter-47"))
        #expect(carnevale.start == .easter(offset: -60))
        #expect(carnevale.description == "easter-60..easter-47")
        #expect(FeatureWindow("easter+1..easter+1")?.end == .easter(offset: 1))
        #expect(FeatureWindow("December") == nil)
        #expect(FeatureWindow("13-01..01-06") == nil)
        #expect(FeatureWindow("12-01.01-06") == nil)
        #expect(FeatureWindow("12-01...01-06") == nil)
        #expect(FeatureWindow("02-30..03-05") == nil)
        #expect(FeatureWindow("02-29..03-01") != nil)
    }

    @Test(arguments: [(2025, 4, 20), (2026, 4, 5), (2027, 3, 28), (2038, 4, 25)])
    func easterSunday(year: Int, month: Int, day: Int) {
        let easter = FeatureWindow.easter(year: year)
        #expect(easter.month == month)
        #expect(easter.day == day)
    }

    @Test func windowRunsOverTheNewYear() throws {
        let winter = try #require(FeatureWindow("12-01..01-06"))
        let inside = try [date(2026, 12, 1), date(2026, 12, 25), date(2027, 1, 6)]
        let outside = try [date(2027, 1, 7), date(2026, 11, 30)]
        for day in inside { #expect(winter.contains(day, calendar: calendar)) }
        for day in outside { #expect(!winter.contains(day, calendar: calendar)) }
    }

    @Test func windowFollowsEaster() throws {
        // Carnevale ends on Shrove Tuesday, 47 days before Easter: 9 February 2027.
        let carnevale = try #require(FeatureWindow("easter-60..easter-47"))
        let inside = try [date(2027, 2, 9), date(2026, 2, 17)]  // 2026: Easter is 5 April
        let outside = try [date(2027, 2, 10), date(2026, 1, 10)]
        for day in inside { #expect(carnevale.contains(day, calendar: calendar)) }
        for day in outside { #expect(!carnevale.contains(day, calendar: calendar)) }
    }

    @Test func windowIsGregorianWhateverTheDeviceCalendar() throws {
        // A Buddhist-calendar device calls 2026 the year 2569; an Islamic one has another month 12.
        let winter = try #require(FeatureWindow("12-01..01-06"))
        let carnevale = try #require(FeatureWindow("easter-60..easter-47"))
        let december = try date(2026, 12, 20), june = try date(2026, 6, 20)
        let shroveTuesday = try date(2027, 2, 9), ashWednesday = try date(2027, 2, 10)
        for identifier in [Calendar.Identifier.buddhist, .islamicUmmAlQura, .hebrew] {
            var device = Calendar(identifier: identifier)
            device.timeZone = calendar.timeZone
            #expect(winter.contains(december, calendar: device))
            #expect(!winter.contains(june, calendar: device))
            #expect(carnevale.contains(shroveTuesday, calendar: device))
            #expect(!carnevale.contains(ashWednesday, calendar: device))
        }
    }

    @Test func manifestCarriesWindowAndStatus() throws {
        let json = """
        {"id": "inverno", "title": "Inverno", "level": "A1-B2", "formatVersion": 1, "version": 1,
         "minContentDB": "1", "language": "it", "translationLanguage": "en", "texts": [
          {"id": "inverno-01", "order": 1, "title": "La Befana", "level": "A2", "file": "texts/inverno-01.json",
           "words": 90, "window": "12-01..01-06", "status": "draft"},
          {"id": "inverno-02", "order": 2, "title": "Il presepe", "level": "B1", "file": "texts/inverno-02.json",
           "words": 120}]}
        """
        let manifest = try JSONDecoder().decode(PackManifest.self, from: Data(json.utf8))
        let first = try #require(manifest.texts.first)
        #expect(first.isDraft)
        #expect(first.featureWindow == FeatureWindow("12-01..01-06"))
        #expect(!manifest.texts[1].isDraft && manifest.texts[1].featureWindow == nil)

        let library = PackLibrary(packs: [LoadedPack(manifest: manifest, directory: URL(fileURLWithPath: "/tmp"))])
        let december = try date(2026, 12, 20), june = try date(2026, 6, 20)
        #expect(library.featured(on: december, calendar: calendar).map(\.text.id) == ["inverno-01"])
        #expect(library.featured(on: june, calendar: calendar).isEmpty)
    }
}

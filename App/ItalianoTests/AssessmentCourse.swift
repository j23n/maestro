import Foundation
import LearningCore
import Testing

@testable import Italiano

/// A synthetic course for the placement and final-check tests. The committed mini pack has Units 0–2 and no
/// assessments, and the course's `placement.yaml` and `final-check.yaml` are still skeletons, so no pack can place
/// a learner at Unit 3 yet; these tests drive the app's models with this course and payloads built from the
/// contract's examples instead.
///
/// Units 0–9, six words each (`w:tKxJ`, recall scheduled); placement blocks for Units 1–8 of five choice items
/// (`pl.u0K.N`); a final review unit `u99` and a final check of five sections: listening and reading (choice, two
/// points each), structures (choice), writing (a form) and speaking (talk).
enum AssessmentCourse {
    static func unit(_ k: Int) -> UnitID { UnitID(String(format: "u%02d", k)) }
    static func word(_ k: Int, _ j: Int) -> ItemID { ItemID("w:t\(k)x\(j)") }
    static func placementItem(_ k: Int, _ n: Int) -> ExerciseID { ExerciseID("pl.\(unit(k).rawValue).\(n)") }

    static let finalSections: [(id: String, title: String, ids: [ExerciseID])] = [
        ("listening", "Listening", ["fin.listening.01", "fin.listening.02"]),
        ("reading", "Reading", ["fin.reading.01"]),
        ("structures", "Structures", ["fin.structures.01"]),
        ("writing", "Writing", ["fin.writing.01"]),
        ("speaking", "Speaking", ["fin.speaking.01"]),
    ]

    static let content: ContentIndex = {
        let p: [Skill: ContentIndex.SkillInfo] = [
            .read: .init(status: .P, scheduled: false), .listen: .init(status: .P, scheduled: false),
            .recall: .init(status: .P, scheduled: true), .speak: .init(status: .P, scheduled: false),
        ]
        var units: [ContentIndex.Unit] = []
        var items: [ContentIndex.Item] = []
        var exercises: [ContentIndex.Exercise] = []
        var blocks: [ContentIndex.PlacementAssessment.Block] = []
        for k in 0...9 {
            units.append(.init(id: unit(k), ord: k))
            for j in 1...6 {
                items.append(
                    .init(
                        id: word(k, j), it: "parola\(k)x\(j)", gloss: "word \(k)-\(j)", pos: "noun", gender: .f,
                        displayDef: "la parola\(k)x\(j)", displayIndef: "una parola\(k)x\(j)", unitId: unit(k),
                        skills: p))
            }
            guard (1...8).contains(k) else { continue }
            let ids = (1...5).map { placementItem(k, $0) }
            for (n, id) in ids.enumerated() {
                exercises.append(
                    .init(
                        id: id, format: .choice, unitId: unit(k), role: .placement,
                        targets: [ItemSkillPair(word(k, n + 1), .read)]))
            }
            blocks.append(.init(unitId: unit(k), exerciseIds: ids))
        }
        units.append(.init(id: "u99", ord: 99, kind: .final))
        for section in finalSections {
            for id in section.ids {
                let format: ExerciseFormat =
                    section.id == "writing" ? .writing : section.id == "speaking" ? .talk : .choice
                exercises.append(
                    .init(
                        id: id, format: format, unitId: "u99", role: .final,
                        score: section.id == "listening" || section.id == "reading" ? 2 : 1))
            }
        }
        return ContentIndex(
            packVersion: "0.9.0", contentHash: "assessment-course", units: units, items: items, exercises: exercises,
            placement: .init(advanceThreshold: 4, blocks: blocks),
            finalCheck: .init(
                sections: finalSections.map { .init(id: $0.id, exerciseIds: $0.ids, max: 12) }))
    }()

    /// An example payload of the contract under another ID (and unit and role).
    static func payload(_ exampleID: String, as id: ExerciseID, unit: UnitID, role: String) throws -> ExercisePayload {
        let data = try Data(
            contentsOf: PayloadFixtures.repoRoot.appendingPathComponent("fixtures/packs/payload-examples.json"))
        let doc = try #require(try JSONSerialization.jsonObject(with: data) as? [String: Any])
        let list = try #require(doc["exercises"] as? [[String: Any]])
        var raw = try #require(list.first { $0["id"] as? String == exampleID })
        raw["id"] = id.rawValue
        raw["unitId"] = unit.rawValue
        raw["role"] = role
        raw["stepId"] = NSNull()
        return try JSONDecoder().decode(ExercisePayload.self, from: JSONSerialization.data(withJSONObject: raw))
    }

    /// Every placement item as a choice question.
    static func placementPayloads() throws -> [ExerciseID: ExercisePayload] {
        var out: [ExerciseID: ExercisePayload] = [:]
        for block in content.placement?.blocks ?? [] {
            for id in block.exerciseIds {
                out[id] = try payload("u02.l1.ex17", as: id, unit: block.unitId, role: "placement")
            }
        }
        return out
    }

    /// The final check's items: choice questions, the registration form and the talk task of the examples.
    static func finalPayloads() throws -> [ExerciseID: ExercisePayload] {
        var out: [ExerciseID: ExercisePayload] = [:]
        for section in finalSections {
            for id in section.ids {
                let example =
                    section.id == "writing"
                    ? "u01.task.write" : section.id == "speaking" ? "u02.task.talk" : "u02.l1.ex17"
                out[id] = try payload(example, as: id, unit: "u99", role: "final")
            }
        }
        return out
    }

    static func bundle(_ exercises: [ExerciseID: ExercisePayload]) -> LessonBundle {
        LessonBundle(lessonID: "assessment", unitID: "u00", title: "Assessment", steps: [], exercises: exercises)
    }

    /// Titles for the result screen.
    static let outline = CourseOutline(
        units: (0...9).map { k in
            CourseOutline.Unit(
                id: unit(k), number: k, titleIt: "Unità \(k)", titleEn: "Unit \(k) in English", lessons: [],
                unitSteps: [])
        })
}

/// Reads back a stored ZIP the way an unzip tool does: the end record, the central directory, each local header.
enum ZipReader {
    struct File: Equatable {
        let path: String
        let data: Data
        let crcMatches: Bool
    }

    static func read(_ zip: Data) throws -> [File] {
        let bytes = [UInt8](zip)
        func u16(_ at: Int) -> Int { Int(bytes[at]) | Int(bytes[at + 1]) << 8 }
        func u32(_ at: Int) -> Int { u16(at) | u16(at + 2) << 16 }
        let end = bytes.count - 22
        try #require(end >= 0 && u32(end) == 0x0605_4B50)
        let count = u16(end + 10)
        var at = u32(end + 16)
        var files: [File] = []
        for _ in 0..<count {
            try #require(u32(at) == 0x0201_4B50)
            try #require(u16(at + 10) == 0)  // stored
            let crc = u32(at + 16)
            let size = u32(at + 24)
            let nameLength = u16(at + 28)
            let local = u32(at + 42)
            let name = String(decoding: bytes[(at + 46)..<(at + 46 + nameLength)], as: UTF8.self)
            try #require(u32(local) == 0x0403_4B50)
            let start = local + 30 + u16(local + 26) + u16(local + 28)
            let data = Data(bytes[start..<(start + size)])
            files.append(File(path: name, data: data, crcMatches: Int(CRC32.checksum(data)) == crc))
            at += 46 + nameLength + u16(at + 30) + u16(at + 32)
        }
        return files
    }
}

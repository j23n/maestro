import Foundation
import LearningCore
import Observation

// First launch (docs/07 § Navigation, `Welcome.png`, `Reason.png`): Welcome → Why Italian? → your name → forms that
// fit you → where you live → weekly goal → studied before? → [study builds: research consent] → Today. The answers
// become synced settings and one `onboardingCompleted` event (docs/05). Platform-neutral and tested.

@MainActor
@Observable
final class OnboardingModel {
    enum Page: Sendable, Equatable { case welcome, reason, name, forms, country, goal, experience, consent }

    struct Reason: Sendable, Equatable, Identifiable {
        let id: String
        let title: String
    }

    struct CountryChoice: Sendable, Equatable, Identifiable {
        let id: String
        let nameIt: String
        let nameEn: String
    }

    static let reasons: [Reason] = [
        .init(id: "travel", title: "A trip to Italy"), .init(id: "family", title: "Family and friends"),
        .init(id: "roots", title: "My Italian roots"), .init(id: "work", title: "Work or study"),
        .init(id: "self", title: "Just for me"),
    ]

    let pages: [Page]
    let countries: [CountryChoice]
    private(set) var index = 0
    var reason: String?
    var name = ""
    var forms: LearnerForms = .both
    var country: String?
    var goal = 5
    var beginner: Bool?
    var consent: Bool?

    init(studyBuild: Bool, countries: [CountryChoice]) {
        var pages: [Page] = [.welcome, .reason, .name, .forms, .country, .goal, .experience]
        if studyBuild { pages.append(.consent) }
        self.pages = pages
        self.countries = countries
    }

    var page: Page { pages[index] }
    var isLast: Bool { index == pages.count - 1 }
    /// "1 of 6": the question pages, after Welcome.
    var counter: String { "\(index) of \(pages.count - 1)" }
    var progress: Double { Double(index) / Double(max(pages.count - 1, 1)) }

    /// Optional pages (name, country) can always go on; the others need an answer.
    var canContinue: Bool {
        switch page {
        case .welcome, .name, .country, .forms, .goal: true
        case .reason: reason != nil
        case .experience: beginner != nil
        case .consent: consent != nil
        }
    }

    func next() { if canContinue, !isLast { index += 1 } }
    func back() { if index > 0 { index -= 1 } }

    var answers: AppModel.OnboardingAnswers {
        AppModel.OnboardingAnswers(
            reason: reason, name: name.trimmingCharacters(in: .whitespacesAndNewlines), forms: forms,
            country: country, goal: min(max(goal, 3), 7), beginner: beginner ?? true, consent: consent)
    }
}

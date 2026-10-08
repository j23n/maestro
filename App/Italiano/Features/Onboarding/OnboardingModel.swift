import Foundation
import LearningCore
import Observation

// First launch (docs/07 § Navigation, `Welcome.png`, `Reason.png`): Welcome → Why Italian? → your name → forms that
// fit you → where you live → weekly goal → studied before? → [study builds: research consent] → Today. The answers
// become synced settings and one `onboardingCompleted` event (docs/05). Platform-neutral and tested.

@MainActor
@Observable
final class OnboardingModel {
    enum Page: String, Sendable, Equatable { case welcome, reason, name, forms, country, goal, experience, consent }

    struct Reason: Sendable, Equatable, Identifiable {
        let id: String
        let title: String
    }

    struct CountryChoice: Sendable, Equatable, Identifiable {
        let id: String
        let nameIt: String
        let nameEn: String
    }

    /// A nationality in both forms, from the pack (`americano` / `americana`).
    struct FormsExample: Sendable, Equatable {
        let masculine: String
        let feminine: String
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

    var countryQuery = ""

    /// The country list narrowed by the search field: English or Italian name, ignoring case and accents.
    var filteredCountries: [CountryChoice] {
        let q = countryQuery.trimmingCharacters(in: .whitespaces)
        guard !q.isEmpty else { return countries }
        return countries.filter {
            $0.nameEn.range(of: q, options: [.caseInsensitive, .diacriticInsensitive]) != nil
                || $0.nameIt.range(of: q, options: [.caseInsensitive, .diacriticInsensitive]) != nil
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

/// The onboarding screens' words (`Welcome.png`, `Reason.png`).
enum OnboardingCopy {
    static let welcomeBody =
        "Short stories you can actually read, reviews timed so words stick, and real conversations. "
        + "On your iPhone, iPad and Mac."
    static let syncFooter = "Your progress syncs through iCloud. No account needed."
    static let localFooter = "Your progress stays on this device. No account needed."

    struct Part: Sendable, Equatable {
        let title: String
        let body: String
    }

    static let howItWorks: [Part] = [
        .init(
            title: "Read and listen",
            body: "Each lesson starts with a short story set in Bologna. Tap any word for its meaning."),
        .init(
            title: "Practise",
            body: "Short exercises built from the story. A wrong answer gets a hint before the solution."),
        .init(
            title: "Review",
            body: "A few minutes a day, timed so each word comes back just before you'd forget it."),
        .init(
            title: "Talk",
            body: "Every unit ends with a conversation and a short check of what you can now do."),
    ]

    static func title(_ page: OnboardingModel.Page) -> String {
        switch page {
        case .welcome: ""
        case .reason: "What brings you to Italian?"
        case .name: "What should we call you?"
        case .forms: "Which forms fit you?"
        case .country: "Where do you live?"
        case .goal: "How many days a week?"
        case .experience: "Have you studied Italian before?"
        case .consent: "Help us improve Italiano"
        }
    }

    /// Moka's line above the question.
    static func hint(_ page: OnboardingModel.Page) -> String {
        switch page {
        case .welcome: ""
        case .reason: "I'll choose stories and phrases that fit what you need."
        case .name: "People in the stories will use it when you talk with them. You can skip this."
        case .forms: "Italian words change with who's speaking. I'll show you the ones that fit you."
        case .country: "So you can say where you live and where you're from."
        case .goal: "A few minutes on most days beats an hour once a week."
        case .experience: "If you're new, we'll start with the sounds and the first words."
        case .consent: "This build is part of a study. You decide what's shared."
        }
    }

    static func goal(_ days: Int) -> String { days == 7 ? "Every day" : "\(days) days a week" }

    // The draft consent text from docs/12 § What is uploaded; the owner replaces it (TODO(owner)).
    static let consentPoints = [
        "Your answers in exercises, the lessons you finish and how long you practise.",
        "Not your name, your country, your recordings or anything you write or say in conversations.",
        "Sent with a random install ID, never your Apple Account. Only the research team sees it.",
    ]
    static let consentFooter = "You can stop sharing at any time in Settings → Research."
}

import Foundation

/// The learner's onboarding answers and answer settings, as the graders need them (docs/03 § Personal slots,
/// docs/05 § Typed answers 4, docs/08 settings `profile.*` and `answers.strictForms`).
public struct LearnerProfile: Sendable, Hashable {
    /// A row of the pack's `countries` table.
    public struct Country: Sendable, Hashable {
        public var id: String
        public var nameIt: String
        public var homePhrase: String
        public var altHomePhrases: [String]
        public var nationalityM: String
        public var nationalityF: String

        public init(
            id: String, nameIt: String, homePhrase: String, altHomePhrases: [String] = [], nationalityM: String,
            nationalityF: String
        ) {
            self.id = id
            self.nameIt = nameIt
            self.homePhrase = homePhrase
            self.altHomePhrases = altHomePhrases
            self.nationalityM = nationalityM
            self.nationalityF = nationalityF
        }
    }

    /// What model answers show when the learner gave no name or chose "Another country": the story's examples,
    /// labelled "for example" (docs/03 § Personal slots). They come from the pack (the Italian stays in content).
    public struct Examples: Sendable, Hashable {
        /// The example name when masculine (or both) forms were chosen (*Marco*).
        public var nameM: String
        /// The example name when feminine forms were chosen (*Sara*).
        public var nameF: String
        /// The example country (Marco's: *in Canada*, *canadese*).
        public var country: Country

        public init(nameM: String, nameF: String, country: Country) {
            self.nameM = nameM
            self.nameF = nameF
            self.country = country
        }
    }

    /// `profile.forms`: m, f, or both (also when the learner didn't say).
    public var forms: LearnerForms
    /// `answers.strictForms`: accept only the learner's gendered form. No effect with `both`.
    public var strictForms: Bool
    /// `profile.name`; nil or empty when not given.
    public var name: String?
    /// The learner's country; nil for "Another country" (or not answered).
    public var country: Country?

    public init(forms: LearnerForms = .both, strictForms: Bool = false, name: String? = nil, country: Country? = nil) {
        self.forms = forms
        self.strictForms = strictForms
        self.name = name
        self.country = country
    }

    /// Both forms, nothing personal: the defaults before onboarding.
    public static let unspecified = LearnerProfile()

    /// Whether an expansion with this gender tag is accepted from this learner (docs/05 § Typed answers 4):
    /// both forms are accepted unless strict forms are on and the learner chose m or f.
    public func accepts(_ gender: PatternExpansion.Gender?) -> Bool {
        guard let gender, strictForms else { return true }
        switch forms {
        case .both: return true
        case .m: return gender == .m
        case .f: return gender == .f
        }
    }

    /// The gender whose forms model answers use: the learner's, masculine for `both` (docs/03).
    public var modelGender: PatternExpansion.Gender { forms == .f ? .f : .m }

    var givenName: String? {
        guard let name = name?.trimmingCharacters(in: .whitespacesAndNewlines), !name.isEmpty else { return nil }
        return name
    }
}

/// A model answer prepared for display (docs/03 § Expansion order, § Personal slots).
public struct ModelAnswer: Sendable, Hashable {
    /// The text in the author's case and punctuation, slots filled.
    public let text: String
    /// True when a slot was filled with an example (no name given, "Another country"): label it "for example".
    public let isExample: Bool
}

extension AnswerPattern {
    /// How gendered alternatives are rendered for a learner with `both` forms.
    public enum ModelAnswerStyle: Sendable {
        /// The model answer itself (audio, the production gate): the masculine form (docs/03 § Personal slots).
        case canonical
        /// The answer shown in feedback: both forms joined, *nato/nata* (docs/05 § Typed answers 4).
        case display
    }

    /// Placeholder shown for `{NUMBER}` in a model answer; the learner supplies the number.
    public static let numberPlaceholder = "…"

    /// The first expansion rendered for the learner: gendered groups in the learner's form, personal slots
    /// filled from the profile (or from `examples`, flagged `isExample`), `{NAME}` filled with the learner's
    /// name. Slots with nothing to fill them keep their placeholder (`{NUMBER}` shows `…`).
    public func modelAnswer(
        profile: LearnerProfile = .unspecified, examples: LearnerProfile.Examples? = nil,
        style: ModelAnswerStyle = .display
    ) -> ModelAnswer {
        var renderer = ModelRenderer(profile: profile, examples: examples, style: style)
        let text = renderer.render(root)
        return ModelAnswer(text: AnswerPattern.collapseSpaces(text), isExample: renderer.usedExample)
    }
}

struct ModelRenderer {
    let profile: LearnerProfile
    let examples: LearnerProfile.Examples?
    let style: AnswerPattern.ModelAnswerStyle
    var usedExample = false

    init(profile: LearnerProfile, examples: LearnerProfile.Examples?, style: AnswerPattern.ModelAnswerStyle) {
        self.profile = profile
        self.examples = examples
        self.style = style
    }

    private var joinsForms: Bool { profile.forms == .both && style == .display }

    mutating func render(_ node: AnswerPattern.Node) -> String {
        switch node {
        case .text(let s): return s
        case .sequence(let nodes): return nodes.map { render($0) }.joined()
        case .choice(let nodes): return nodes.first.map { render($0) } ?? ""
        case .optional(let node), .focus(let node): return render(node)
        case .gendered(let options):
            let m = options.first { $0.gender == .m }
            let f = options.first { $0.gender == .f }
            if joinsForms, let m, let f {
                let a = render(m.node)
                let b = render(f.node)
                return a == b ? a : join(a, b)
            }
            let preferred = profile.modelGender == .f ? (f ?? m) : (m ?? f)
            return preferred.map { render($0.node) } ?? ""
        case .slot(let slot): return render(slot)
        }
    }

    /// `nato` + `nata` → `nato/nata`, keeping the surrounding spaces of the pieces outside the slash.
    private func join(_ a: String, _ b: String) -> String {
        let lead = a.prefix { $0.isWhitespace }
        let trail = b.reversed().prefix { $0.isWhitespace }
        return String(lead) + a.trimmingCharacters(in: .whitespaces) + "/" + b.trimmingCharacters(in: .whitespaces)
            + String(trail.reversed())
    }

    private mutating func render(_ slot: PatternSlot) -> String {
        switch slot {
        case .name:
            if let name = profile.givenName { return name }
            if let examples {
                usedExample = true
                return profile.forms == .f ? examples.nameF : examples.nameM
            }
            return slot.placeholder
        case .number:
            return AnswerPattern.numberPlaceholder
        case .home, .country, .nationality:
            let country: LearnerProfile.Country
            if let own = profile.country {
                country = own
            } else if let example = examples?.country {
                usedExample = true
                country = example
            } else {
                return slot.placeholder
            }
            switch slot {
            case .home: return country.homePhrase
            case .country: return country.nameIt
            default:
                if country.nationalityM == country.nationalityF { return country.nationalityM }
                if joinsForms { return country.nationalityM + "/" + country.nationalityF }
                return profile.modelGender == .f ? country.nationalityF : country.nationalityM
            }
        }
    }
}

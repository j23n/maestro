import LearningCore
import SwiftUI

/// First launch (`Welcome.png`, `Reason.png`, docs/07 § Navigation). The questions follow `Reason.png`: back,
/// progress and counter on top, Moka's line, a serif question, choices, Continue at the bottom.
struct OnboardingView: View {
    let app: AppModel
    let syncAllowed: Bool
    @State private var model: OnboardingModel
    @State private var showHowItWorks = false

    init(app: AppModel, studyBuild: Bool, syncAllowed: Bool) {
        self.app = app
        self.syncAllowed = syncAllowed
        _model = State(initialValue: OnboardingModel(studyBuild: studyBuild, countries: app.countryChoices))
    }

    var body: some View {
        Group {
            if model.page == .welcome {
                welcome
            } else {
                question
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.ds.background)
        .sheet(isPresented: $showHowItWorks) { HowItWorksSheet() }
    }

    // MARK: Welcome

    private var welcome: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Tokens.Space.xxl) {
                Mascot(pose: .hello, size: 200, decorative: true)
                    .frame(maxWidth: .infinity)
                    .padding(.top, Tokens.Space.xxxl)
                VStack(alignment: .leading, spacing: Tokens.Space.m) {
                    // A fixed UI line like the greetings (docs/07 § Copy; String Catalog, English comment).
                    ItalianText("Impara l'italiano, una storia alla volta.", style: Tokens.TypeScale.display)
                        .accessibilityAddTraits(.isHeader)
                    Text("Learn Italian, one story at a time.")
                        .dsFont(Tokens.TypeScale.translation).foregroundStyle(Color.ds.secondary)
                }
                Text(OnboardingCopy.welcomeBody)
                    .dsFont(Tokens.TypeScale.uiBody).foregroundStyle(Color.ds.ink)
                VStack(spacing: Tokens.Space.l) {
                    Button("Start learning") { model.next() }
                        .buttonStyle(.dsPrimary)
                        .keyboardShortcut(.return, modifiers: [])
                        .accessibilityIdentifier("onboarding.start")
                    Button("How it works") { showHowItWorks = true }
                        .buttonStyle(.dsTextLink)
                        .accessibilityIdentifier("onboarding.howItWorks")
                    Text(syncAllowed ? OnboardingCopy.syncFooter : OnboardingCopy.localFooter)
                        .dsFont(Tokens.TypeScale.uiCaption).foregroundStyle(Color.ds.secondary)
                        .multilineTextAlignment(.center)
                }
                .frame(maxWidth: .infinity)
                .padding(.top, Tokens.Space.xxl)
            }
            .readableColumn()
            .padding(.bottom, Tokens.Space.xxl)
        }
        .accessibilityIdentifier("onboarding.welcome")
    }

    // MARK: Questions

    private var question: some View {
        VStack(spacing: 0) {
            topBar
            ScrollView {
                VStack(alignment: .leading, spacing: Tokens.Space.xxl) {
                    HStack(alignment: .top, spacing: Tokens.Space.l) {
                        Mascot(pose: .think, size: 72, decorative: true, isHint: true)
                        Text(OnboardingCopy.hint(model.page))
                            .dsFont(Tokens.TypeScale.translation).foregroundStyle(Color.ds.secondary)
                    }
                    Text(OnboardingCopy.title(model.page))
                        .dsFont(Tokens.TypeScale.screenTitle).foregroundStyle(Color.ds.ink)
                        .accessibilityAddTraits(.isHeader)
                    answers
                }
                .readableColumn()
                .padding(.vertical, Tokens.Space.xl)
            }
            bottomBar
        }
        .accessibilityIdentifier("onboarding.\(model.page.rawValue)")
    }

    private var topBar: some View {
        HStack(spacing: Tokens.Space.l) {
            Button {
                model.back()
            } label: {
                Image(systemName: "chevron.left").frame(width: Tokens.Size.minTouch, height: Tokens.Size.minTouch)
            }
            .buttonStyle(.plain)
            .foregroundStyle(Color.ds.ink)
            .keyboardShortcut("[", modifiers: .command)
            .accessibilityLabel("Back")
            .accessibilityIdentifier("onboarding.back")
            DSProgressBar(value: model.progress)
            Text(model.counter).dsFont(Tokens.TypeScale.uiCallout).foregroundStyle(Color.ds.secondary)
                .monospacedDigit()
        }
        .readableColumn()
        .padding(.top, Tokens.Space.m)
    }

    @ViewBuilder private var bottomBar: some View {
        Group {
            if model.page == .consent {
                VStack(spacing: Tokens.Space.m) {
                    Button("Share learning data") {
                        model.consent = true
                        finish()
                    }
                    .buttonStyle(.dsPrimary)
                    .accessibilityIdentifier("onboarding.consent.share")
                    Button("Not now") {
                        model.consent = false
                        finish()
                    }
                    .buttonStyle(.dsSecondary)
                    .accessibilityIdentifier("onboarding.consent.notNow")
                }
            } else {
                Button(model.page == .name && model.name.isEmpty ? "Skip" : "Continue") {
                    if model.isLast { finish() } else { model.next() }
                }
                .buttonStyle(.dsPrimary)
                .disabled(!model.canContinue)
                .keyboardShortcut(.return, modifiers: [])
                .accessibilityIdentifier("onboarding.continue")
            }
        }
        .readableColumn()
        .padding(.vertical, Tokens.Space.l)
    }

    @ViewBuilder private var answers: some View {
        switch model.page {
        case .welcome:
            EmptyView()
        case .reason:
            VStack(spacing: Tokens.Space.m) {
                ForEach(OnboardingModel.reasons) { reason in
                    ChoiceRow(title: reason.title, isSelected: model.reason == reason.id) { model.reason = reason.id }
                        .accessibilityIdentifier("onboarding.reason.\(reason.id)")
                }
            }
        case .name:
            TextField("Your first name", text: $model.name)
                .dsFont(Tokens.TypeScale.uiTitle)
                .textFieldStyle(.plain)
                .padding(Tokens.Space.l)
                .overlay(
                    RoundedRectangle(cornerRadius: Tokens.Radius.input)
                        .strokeBorder(Color.ds.inputBorder, lineWidth: Tokens.Border.control)
                )
                .autocorrectionDisabled()
                .onSubmit { model.next() }
                .accessibilityLabel("Your first name")
                .accessibilityIdentifier("onboarding.name")
        case .forms:
            VStack(spacing: Tokens.Space.m) {
                ChoiceRow(
                    title: "Masculine", italian: app.formsExample?.masculine, isSelected: model.forms == .m
                ) { model.forms = .m }
                .accessibilityIdentifier("onboarding.forms.m")
                ChoiceRow(
                    title: "Feminine", italian: app.formsExample?.feminine, isSelected: model.forms == .f
                ) { model.forms = .f }
                .accessibilityIdentifier("onboarding.forms.f")
                ChoiceRow(title: "Show me both", isSelected: model.forms == .both) { model.forms = .both }
                    .accessibilityIdentifier("onboarding.forms.both")
            }
        case .country:
            VStack(spacing: Tokens.Space.m) {
                TextField("Search", text: $model.countryQuery)
                    .dsFont(Tokens.TypeScale.uiBody)
                    .textFieldStyle(.plain)
                    .padding(Tokens.Space.m)
                    .background(RoundedRectangle(cornerRadius: Tokens.Radius.input).fill(Color.ds.subtle))
                    .autocorrectionDisabled()
                    .accessibilityLabel("Search countries")
                    .accessibilityIdentifier("onboarding.country.search")
                LazyVStack(spacing: Tokens.Space.s) {
                    ForEach(model.filteredCountries) { c in
                        ChoiceRow(title: c.nameEn, italian: c.nameIt, isSelected: model.country == c.id) {
                            model.country = model.country == c.id ? nil : c.id
                        }
                        .accessibilityIdentifier("onboarding.country.\(c.id)")
                    }
                }
            }
        case .goal:
            VStack(spacing: Tokens.Space.m) {
                ForEach(3...7, id: \.self) { days in
                    ChoiceRow(
                        title: OnboardingCopy.goal(days), subtitle: days == 5 ? "Recommended" : nil,
                        isSelected: model.goal == days
                    ) { model.goal = days }
                    .accessibilityIdentifier("onboarding.goal.\(days)")
                }
            }
        case .experience:
            VStack(spacing: Tokens.Space.m) {
                ChoiceRow(title: "No, I'm starting from zero", isSelected: model.beginner == true) {
                    model.beginner = true
                }
                .accessibilityIdentifier("onboarding.experience.no")
                ChoiceRow(title: "Yes, I know a little", isSelected: model.beginner == false) {
                    model.beginner = false
                }
                .accessibilityIdentifier("onboarding.experience.yes")
            }
        case .consent:
            VStack(alignment: .leading, spacing: Tokens.Space.m) {
                // TODO(owner): the participant information and consent text need the owner's sign-off (docs/12);
                // bump `AppModel.consentTextVersion` with every change to it.
                ForEach(OnboardingCopy.consentPoints, id: \.self) { point in
                    Label(point, systemImage: "checkmark.circle")
                        .dsFont(Tokens.TypeScale.uiBody).foregroundStyle(Color.ds.ink)
                }
                Text(OnboardingCopy.consentFooter)
                    .dsFont(Tokens.TypeScale.uiCaption).foregroundStyle(Color.ds.secondary)
            }
        }
    }

    private func finish() {
        app.completeOnboarding(model.answers)
    }
}

/// A full-width choice (`Reason.png`): left-aligned title, optional Italian example or subtitle, check when selected.
private struct ChoiceRow: View {
    let title: String
    var italian: String?
    var subtitle: String?
    let isSelected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: Tokens.Space.m) {
                VStack(alignment: .leading, spacing: Tokens.Space.xxs) {
                    Text(title).dsFont(Tokens.TypeScale.uiTitle).foregroundStyle(Color.ds.ink)
                    if let italian {
                        ItalianText(italian, style: Tokens.TypeScale.translation)
                    }
                    if let subtitle {
                        Text(subtitle).dsFont(Tokens.TypeScale.uiCaption).foregroundStyle(Color.ds.secondary)
                    }
                }
                Spacer(minLength: 0)
                if isSelected {
                    Image(systemName: "checkmark").foregroundStyle(Color.ds.accent).accessibilityHidden(true)
                }
            }
            .padding(.horizontal, Tokens.Space.xl)
            .padding(.vertical, Tokens.Space.l)
            .frame(maxWidth: .infinity, minHeight: Tokens.Size.minTouch, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: Tokens.Radius.optionCard)
                    .fill(isSelected ? Color.ds.accentTint : Color.ds.background)
            )
            .overlay(
                RoundedRectangle(cornerRadius: Tokens.Radius.optionCard)
                    .strokeBorder(
                        isSelected ? Color.ds.accent : Color.ds.divider,
                        lineWidth: isSelected ? Tokens.Border.inputError : Tokens.Border.control)
            )
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(isSelected ? [.isButton, .isSelected] : .isButton)
    }
}

/// "How it works" from Welcome: the four parts of a unit in plain words.
private struct HowItWorksSheet: View {
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(alignment: .leading, spacing: Tokens.Space.xl) {
            Text("How it works").dsFont(Tokens.TypeScale.sectionTitle).foregroundStyle(Color.ds.ink)
                .accessibilityAddTraits(.isHeader)
            ForEach(OnboardingCopy.howItWorks, id: \.title) { part in
                VStack(alignment: .leading, spacing: Tokens.Space.xs) {
                    Text(part.title).dsFont(Tokens.TypeScale.uiTitle).foregroundStyle(Color.ds.ink)
                    Text(part.body).dsFont(Tokens.TypeScale.uiBody).foregroundStyle(Color.ds.secondary)
                }
            }
            Spacer(minLength: 0)
            Button("Got it") { dismiss() }
                .buttonStyle(.dsPrimary)
                .keyboardShortcut(.return, modifiers: [])
                .accessibilityIdentifier("onboarding.howItWorks.done")
        }
        .padding(Tokens.Space.xxl)
        .frame(minWidth: 360, minHeight: 440)
        .background(Color.ds.background)
        .accessibilityIdentifier("onboarding.howItWorks.sheet")
    }
}

import SwiftUI

// docs/07 § Components: AnswerField, AccentKeys, OptionCard, Tile. Identifiers follow docs/06.

/// Height 56, radius 12, 1.5 pt `inputBorder`, Literata 20; error state 2 pt `warning` on `warningInputBackground`.
struct AnswerField: View {
    @Binding var text: String
    var placeholder = "Type in Italian"
    var isError = false
    var onSubmit: () -> Void = {}
    var focus: FocusState<Bool>.Binding

    var body: some View {
        TextField(placeholder, text: $text)
            .dsFont(Tokens.TypeScale.answerInput)
            .foregroundStyle(Color.ds.ink)
            .autocorrectionDisabled()
            #if os(iOS)
                .textInputAutocapitalization(.never)
                .keyboardType(.default)
            #endif
            .textFieldStyle(.plain)
            .submitLabel(.done)
            .onSubmit(onSubmit)
            .focused(focus)
            .padding(.horizontal, Tokens.Space.l)
            .frame(minHeight: Tokens.Size.inputHeight)
            .background(
                RoundedRectangle(cornerRadius: Tokens.Radius.input)
                    .fill(isError ? Color.ds.warningInputBackground : Color.ds.background)
            )
            .overlay(
                RoundedRectangle(cornerRadius: Tokens.Radius.input)
                    .strokeBorder(
                        isError ? Color.ds.warning : Color.ds.inputBorder,
                        lineWidth: isError ? Tokens.Border.inputError : Tokens.Border.control)
            )
            .environment(\.locale, Locale(identifier: "it_IT"))
            .accessibilityLabel(Text("Your answer"))
            .accessibilityIdentifier("answer.field")
    }
}

/// The six accent keys (à è é ì ò ù): height 44, radius 10, 1 pt `divider`, Literata 18; they insert at the caret
/// through the `insert` closure (the field owner keeps the caret position).
struct AccentKeys: View {
    static let letters = ["à", "è", "é", "ì", "ò", "ù"]
    let insert: (String) -> Void

    var body: some View {
        HStack(spacing: Tokens.Space.s) {
            ForEach(Self.letters, id: \.self) { letter in
                Button {
                    insert(letter)
                } label: {
                    Text(letter)
                        .dsFont(TypeStyle(family: .italian, size: 18, weight: 400, lineHeight: nil, italic: false,
                                          relativeTo: .body))
                        .foregroundStyle(Color.ds.ink)
                        .frame(maxWidth: .infinity, minHeight: Tokens.Size.accentKeyHeight)
                        .background(RoundedRectangle(cornerRadius: Tokens.Radius.key).fill(Color.ds.background))
                        .overlay(
                            RoundedRectangle(cornerRadius: Tokens.Radius.key)
                                .strokeBorder(Color.ds.divider, lineWidth: Tokens.Border.hairline))
                }
                .buttonStyle(.plain)
                .accessibilityLabel(Text(letter))
                .accessibilityHint(Text("Inserts \(letter)"))
                .accessibilityIdentifier("answer.accent.\(letter)")
            }
        }
    }
}

/// Height 120, radius 18, 1.5 pt `inputBorder`; Italian word Literata 30/600 and gloss 15 `secondary`; selected:
/// accent border and `accentTint`. At accessibility sizes it grows vertically (no fixed height).
struct OptionCard: View {
    let title: String
    var subtitle: String?
    var titleIsItalian = true
    var isSelected = false
    var mark: Mark = .idle
    let action: () -> Void

    /// After answering: the right option turns success, a wrong pick warning.
    enum Mark { case idle, correct, wrong }

    var body: some View {
        Button(action: action) {
            VStack(spacing: Tokens.Space.xs) {
                if titleIsItalian {
                    ItalianText(title, style: TypeStyle(family: .italian, size: 30, weight: 600, lineHeight: nil,
                                                         italic: false, relativeTo: .title))
                } else {
                    Text(title).dsFont(Tokens.TypeScale.uiTitle).foregroundStyle(Color.ds.ink)
                        .multilineTextAlignment(.center)
                }
                if let subtitle {
                    Text(subtitle).dsFont(Tokens.TypeScale.uiCallout).foregroundStyle(Color.ds.secondary)
                }
            }
            .padding(Tokens.Space.l)
            .frame(maxWidth: .infinity, minHeight: Tokens.Size.optionCardHeight)
            .background(RoundedRectangle(cornerRadius: Tokens.Radius.optionCard).fill(fill))
            .overlay(
                RoundedRectangle(cornerRadius: Tokens.Radius.optionCard)
                    .strokeBorder(border, lineWidth: Tokens.Border.control))
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(isSelected ? .isSelected : [])
    }

    private var fill: Color {
        switch mark {
        case .correct: Color.ds.accentTint
        case .wrong: Color.ds.warningInputBackground
        case .idle: isSelected ? Color.ds.accentTint : Color.ds.background
        }
    }

    private var border: Color {
        switch mark {
        case .correct: Color.ds.success
        case .wrong: Color.ds.warning
        case .idle: isSelected ? Color.ds.accent : Color.ds.inputBorder
        }
    }
}

/// Sentence-building tile: pill, height 48, 1.5 pt `inputBorder`, Literata 20.
struct WordTile: View {
    let word: String
    var isPlaced = false
    var isMarked = false

    var body: some View {
        ItalianText(word, style: Tokens.TypeScale.answerInput)
            .padding(.horizontal, Tokens.Space.l)
            .frame(minHeight: 48)
            .background(Capsule().fill(isMarked ? Color.ds.warningInputBackground : Color.ds.background))
            .overlay(
                Capsule().strokeBorder(isMarked ? Color.ds.warning : Color.ds.inputBorder,
                                       lineWidth: Tokens.Border.control))
            .opacity(isPlaced ? 0.35 : 1)
    }
}

/// A switch in the design colours (52 × 32, knob 26; on = accent, off = `switchOff`). docs/07: use the system
/// Toggle with a tint where it matches; this style is the fallback for the exact look.
struct DSToggleStyle: ToggleStyle {
    func makeBody(configuration: Configuration) -> some View {
        Button {
            configuration.isOn.toggle()
        } label: {
            HStack {
                configuration.label
                Spacer(minLength: Tokens.Space.m)
                ZStack(alignment: configuration.isOn ? .trailing : .leading) {
                    Capsule().fill(configuration.isOn ? Color.ds.accent : Color.ds.switchOff)
                        .frame(width: Tokens.Size.toggleWidth, height: Tokens.Size.toggleHeight)
                    Circle().fill(Color.white).frame(width: Tokens.Size.toggleKnob, height: Tokens.Size.toggleKnob)
                        .padding(3)
                }
            }
        }
        .buttonStyle(.plain)
        .accessibilityRepresentation { Toggle(isOn: configuration.$isOn) { configuration.label } }
    }
}

import LearningCore
import SwiftUI

/// Today (`Home.png`, docs/05 § The Today planner): date and greeting with Moka, the Review card, Continue, this
/// week and two stats. Two cards side by side when the width allows (docs/07). Lessons are never blocked. With more
/// than 40 due (`reviewIsPrimary`) the Review card comes first in every layout and Continue moves below the week.
struct TodayView: View {
    let content: TodayContent
    let onStartReview: () -> Void
    let onContinue: (TodayContent.ContinueCard) -> Void

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Tokens.Space.xxl) {
                header
                if content.reviewIsPrimary {
                    reviewCard
                    week
                    continueCard
                } else {
                    ViewThatFits(in: .horizontal) {
                        HStack(alignment: .top, spacing: Tokens.Space.l) {
                            reviewCard.frame(minWidth: 340)
                            continueCard.frame(minWidth: 340)
                        }
                        Card {
                            reviewSection
                            if content.continueCard != nil {
                                CardDivider()
                                continueSection
                            }
                        }
                    }
                    week
                }
                HStack(spacing: Tokens.Space.l) {
                    StatTile(value: "\(content.wordsKnown)", label: "words you know")
                        .accessibilityIdentifier("today.words")
                    StatTile(value: content.unitsLine, label: "units finished")
                        .accessibilityIdentifier("today.units")
                }
            }
            .readableColumn()
            .padding(.vertical, Tokens.Space.xxl)
        }
        .background(Color.ds.background)
    }

    private var header: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: Tokens.Space.xs) {
                Text(content.dateLine).dsFont(Tokens.TypeScale.uiCallout).foregroundStyle(Color.ds.secondary)
                ItalianText(content.greeting, style: Tokens.TypeScale.display)
                    .accessibilityAddTraits(.isHeader)
            }
            Spacer()
            Mascot(pose: .hello, size: 96, decorative: true)
        }
    }

    private var reviewCard: some View { Card { reviewSection } }

    @ViewBuilder private var continueCard: some View {
        if content.continueCard != nil { Card { continueSection } }
    }

    private var reviewSection: some View {
        VStack(alignment: .leading, spacing: Tokens.Space.l) {
            HStack {
                Text("Review").dsFont(Tokens.TypeScale.uiTitle).foregroundStyle(Color.ds.ink)
                Spacer()
                if let d = content.review.duration {
                    Text(d).dsFont(Tokens.TypeScale.uiCallout).foregroundStyle(Color.ds.secondary)
                }
            }
            MixedText(text: content.review.body, style: Tokens.TypeScale.italianBody)
            if let c = content.review.catchUp {
                Text(c).dsFont(Tokens.TypeScale.uiCallout).foregroundStyle(Color.ds.secondary)
            }
            if content.review.canStart {
                Button("Start review", action: onStartReview)
                    .buttonStyle(.dsPrimaryCompact)
                    .accessibilityIdentifier("today.review")
            }
        }
    }

    @ViewBuilder private var continueSection: some View {
        if let c = content.continueCard {
            VStack(alignment: .leading, spacing: Tokens.Space.m) {
                HStack {
                    Text("Continue").dsFont(Tokens.TypeScale.uiTitle).foregroundStyle(Color.ds.ink)
                    Spacer()
                    Text(c.context).dsFont(Tokens.TypeScale.uiCallout).foregroundStyle(Color.ds.secondary)
                }
                HStack(alignment: .center) {
                    VStack(alignment: .leading, spacing: Tokens.Space.xxs) {
                        ItalianText(c.titleIt, style: Tokens.TypeScale.rowTitle)
                        Text(c.titleEn).dsFont(Tokens.TypeScale.uiCallout).foregroundStyle(Color.ds.secondary)
                    }
                    Spacer()
                    // With reviews ready, Start review is the filled button (`Home.png`); with none, Continue is.
                    if content.review.canStart {
                        Button(c.action) { onContinue(c) }
                            .buttonStyle(.dsSecondary)
                            .fixedSize()
                            .accessibilityIdentifier("today.continue")
                    } else {
                        Button(c.action) { onContinue(c) }
                            .buttonStyle(.dsPrimaryCompact)
                            .fixedSize()
                            .accessibilityIdentifier("today.continue")
                    }
                }
            }
        }
    }

    private var week: some View {
        VStack(alignment: .leading, spacing: Tokens.Space.l) {
            HStack {
                Text("This week").dsFont(Tokens.TypeScale.uiTitle).foregroundStyle(Color.ds.ink)
                Spacer()
                Text(content.weekLine).dsFont(Tokens.TypeScale.uiCallout).foregroundStyle(Color.ds.secondary)
            }
            WeekDots(active: content.week.days, letters: ["M", "T", "W", "T", "F", "S", "S"])
                .accessibilityIdentifier("today.week")
        }
    }
}

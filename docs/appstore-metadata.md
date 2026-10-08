# App Store metadata (draft for the owner, task M9.3)

A starting point for App Store Connect. The owner checks every line, fills the `TODO(owner)` fields and decides the open points at the end. Character limits are Apple's; the counts are for the text as written. The wording is our own: no exam names, no syllabus or exam-paper wording, no promise of a certificate (hard rule 2; the final check is "a practice check, not an official certificate", docs/12).

## Identity

| Field | Draft | Notes |
|---|---|---|
| Name (≤ 30) | **Italiano: Italian Stories** (25) | "Italiano" alone is likely taken; alternatives: *Italiano – Learn A1 Italian* (27), *Italiano: Beginner Italian* (26) |
| Subtitle (≤ 30) | **Learn Italian through a story** (29) | alternative: *Read, listen, speak Italian* (27) |
| Bundle ID | `com.j23n.italian` | ADR-18; never changes |
| SKU | `TODO(owner)` | |
| Primary category | Education | |
| Secondary category | Reference (optional) | or none |
| Price | `TODO(owner)` | the MVP has no in-app purchases, payments or paywalls (docs/01 non-goals) |
| Copyright | `TODO(owner)` (e.g. "2026 <name>") | |
| Support URL | `TODO(owner)` | required |
| Marketing URL | `TODO(owner)` | optional |
| Privacy policy URL | `TODO(owner)` | required; it should say what docs/12 says: no account, data on the device and the user's iCloud, study uploads only in study builds and only after consent |
| Platforms | iPhone, iPad, Mac (native, not Catalyst) | iOS, iPadOS and macOS 26 |

## Promotional text (≤ 170)

> Learn beginner Italian one short story at a time. Read and listen, tap any word for English, practise with gentle feedback, and review at the right moment. (155)

## Description (≤ 4,000)

> Italiano teaches beginner (A1) Italian to English speakers through one continuing story set in Bologna.
>
> Each unit is an episode. You meet the words first, read and listen to a short story, then see how the language works in a note built from what you just read. Practice follows: fill a gap, say it in Italian, build a sentence, write what you hear, tell similar sounds apart, and repeat after the audio. Units end with a conversation with the people of the story and a short check, so you know what you can now do.
>
> LEARN FROM STORIES
> • Short graded stories with audio for every line and read-along highlighting
> • Tap any word for its meaning; nothing you haven't met yet is ever thrown at you
> • Grammar notes that grow out of the story, with clear tables and examples
>
> PRACTISE WITH FEEDBACK THAT HELPS
> • A first miss gets a pointer and a hint, not just a red cross
> • Accent keys for à è é ì ò ù on every device
> • Speak your answers if you like: speech recognition runs on your device
>
> REVIEW AT THE RIGHT TIME
> • A modern spaced-repetition scheduler brings words back just before you'd forget them
> • Reviews mix earlier units, so what you learn stays learned
> • Weekly goals instead of streaks: missing a day costs you nothing
>
> REAL-WORLD ITALIAN
> • Menus, signs, timetables, receipts and messages to read
> • Conversations with the people of the story: order a coffee, introduce yourself, ask the way
> • Tasks that ask you to pass information on to a friend in English
>
> PRIVATE BY DESIGN
> • No account and no sign-in
> • Works offline; your progress is kept on your devices and syncs through your own iCloud
> • No ads, no tracking, no third-party analytics
>
> FOR IPHONE, IPAD AND MAC
> • Layouts made for each screen, keyboard shortcuts on Mac, VoiceOver labels, and text size you control
>
> Already know a little? A short placement starts you at the right unit. At the end of the course, a final check scores what you can do in reading, listening, writing and speaking against an indicative pass mark. It is a practice check, not an official certificate.

(about 2,000 characters)

## Keywords (≤ 100, comma-separated, no spaces after commas)

`italian,learn italian,beginner,language,stories,vocabulary,grammar,listening,speaking,italy,offline` (99)

Don't repeat words already in the name or subtitle if space runs short; Apple indexes those already.

## What's New (first release)

> The first release: Unit 0 to Unit `TODO(owner: last approved unit)`, with stories, practice, reviews and unit checks on iPhone, iPad and Mac.

## Screenshots

Apple needs at least the largest iPhone and iPad sizes and, for the Mac app, one of the Mac sizes. `make screenshots` produces the reference screens (`artifacts/screens/`); App Store images must show real content from an approved pack (never the design references' placeholder text).

| Device | Size (portrait) | Suggested screens |
|---|---|---|
| iPhone 6.9" | 1320 × 2868 | Story, word panel, cloze with feedback, conversation, session complete |
| iPad 13" | 2064 × 2752 | Story in two panes, grammar note, course map |
| Mac | 2880 × 1800 | Story in two panes, course map, Words table |

## App Privacy (the questionnaire)

From `App/Italiano/Resources/PrivacyInfo.xcprivacy` (docs/12 § Privacy and App Store, docs/13 § Release prep).

- **Tracking:** No. No tracking domains, no advertising identifiers, no third-party SDKs.
- **If the build on the App Store carries the study** (consented uploads to the study endpoint), declare *Data Linked to You*, purpose **Analytics** only, none used for tracking:
  - Usage Data → **Product Interaction** (learning events: answers' outcomes, steps, glosses tapped, audio played, sessions, checks)
  - Usage Data → **Other Usage Data** (app, pack and OS version, platform, device class; the onboarding reason and beginner flag)
  - User Content → **Other User Content** (short typed answers to closed exercises, at most 200 characters)
  - Identifiers → **User ID** (the pseudonymous study install ID, a random UUID)
- **If it doesn't** (a Release build: it never uploads), the honest answer is **Data Not Collected**, and the manifest should then lose its collected data types first (Proposed changes in docs/13, owner decision).
- Not collected, whatever the build: name, email, contacts, location, health, financial data, purchases, browsing or search history, contacts, photos, audio recordings (speech is recognised on the device; the final check's recordings stay on the device until the learner shares them), crash data (no SDK; Xcode Organizer's crash logs come from Apple), iCloud data (the user's private database, which we can't read).

## Age rating

Answer **None** to every content question (violence, sexual content, profanity, horror, gambling, medical, contests), **No** to unrestricted web access, user-generated content shared with others, messaging and chat, advertising, and parental controls. That gives the lowest rating.

- Re-check the stories before each submission for alcohol references: Italian café culture (*aperitivo*, wine at dinner) may appear in later units; "infrequent/mild alcohol references" raises the rating.
- Not in the Kids category: the course is written for adults, and the study recruits adults (docs/12).

## Export compliance

`ITSAppUsesNonExemptEncryption = NO` is in `App/Config/Italiano-Info.plist`: the app uses only the encryption built into Apple's operating systems (HTTPS to the study endpoint, CloudKit), so App Store Connect won't ask on every upload.

## Notes for App Review

> No account or sign-in is needed: the app opens on a short onboarding and then the course. Everything works offline.
>
> To see the main features quickly: complete onboarding (answer "No, I'm starting from zero"), then on Today tap Continue. Any lesson in Unit `TODO(owner)` shows the story reader, word glosses and practice with feedback; the unit's conversation follows its lessons.
>
> Microphone and speech recognition are requested only when the learner taps a microphone button; recognition runs on the device. If they are declined, every speaking exercise offers typing or listen-and-repeat instead.
>
> iCloud is used only to sync the learner's own progress through their private iCloud database; there is no server account. The app has no in-app purchases, ads or tracking.
>
> The final "practice check" at the end of the course is scored automatically against an indicative pass mark and says it is not an official certificate.

## Open points for the owner

1. App name availability; pick from the alternatives above.
2. Whether the App Store build is the plain Release configuration (no study, "Data Not Collected") while study builds stay on TestFlight; then remove the collected types from the manifest before that release (docs/13 Proposed changes). If the App Store build carries the study, add to the description that learning data is shared only with consent.
6. Claims to re-check before submission: the accessibility line after the M9.2 audit, and "Units end with a conversation" against the units that ship (the final review unit has none).
3. Privacy policy and support pages (URLs required by App Store Connect).
4. Price and availability; Education category confirmed.
5. Which units the first App Store build carries (only approved units ship, docs/04), for What's New and the review notes.

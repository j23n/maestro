---
name: ios-ui
description: Build or change SwiftUI screens and components for iPhone, iPad and Mac in the Libro design system, and verify them with snapshots and simulator or Mac screenshots. Use for any work under App/Italiano/DesignSystem or App/Italiano/Features.
---

# Building UI in Italiano

## Sources of truth

- `docs/07-ui.md`: screen map, navigation, components, layout and accessibility rules.
- `design/tokens.json`, mirrored in `DesignSystem/Tokens.swift`. Never hard-code a colour, font size or radius in a feature view.
- `design/screens/*.png`: reference renders at 2×. Their text is placeholder; match layout, not words.
- `design/source/*.dc.html`: exact paddings and sizes when a PNG isn't enough.
- `docs/06-lesson-types.md`: behaviour, accessibility identifiers and acceptance criteria per lesson type.

## Building a screen

1. **Compose from `DesignSystem` components.** If you need a new component, add it there with a snapshot test first.
2. **View model:** `@MainActor @Observable`, initialised with protocols from `AppDependencies`. Previews use fakes and `fixtures/packs/mini.sqlite`.
3. **Italian text:** always through `ItalianText` (Literata, `it-IT` speech language). Never put `lineLimit` on Italian.
4. **Layout:** branch on `horizontalSizeClass` (compact vs regular); content column max 720 pt on regular width. On macOS, add keyboard shortcuts (`.keyboardShortcut`) and menu commands per `docs/07`.
5. **Accessibility:**
   - an identifier (`screen.element[.n]`) and a label on every interactive element;
   - group related text;
   - announce feedback (`AccessibilityNotification.Announcement`);
   - respect Reduce Motion.
6. **Mascot:** `Mascot(pose:size:)`, with the pose by meaning (hello, think, cheer, sleep). Hide hint mascots when the "Show Moka's hints" setting is off.

## Verifying

### Snapshot tests (always)

- `swift-snapshot-testing` with Swift Testing.
- Configurations (the matrix in `docs/07` § Visual verification): iPhone compact light, iPhone compact dark, iPad regular light, iPad regular dark, and iPhone at `.accessibilityExtraExtraExtraLarge` (light).
- Use `perceptualPrecision: 0.98` and the simulator runtime pinned in `PROGRESS.md`, so CI doesn't fail on anti-aliasing.
- Record with `record: .missing` once, review the images, commit them.

### iOS Simulator screenshots (MobileBuildMCP)

1. Run `make project` first (the project is generated from `App/project.yml` by XcodeGen and gitignored; ADR-19). Set session defaults once with `session_set_defaults`: project `App/Italiano.xcodeproj`, scheme `Italiano`, simulator `iPhone 17` (or what `list_sims` shows). Builds stay unsigned (`docs/02` § Project, signing and entitlements).
   - To open a screen deep in the course, launch with `-ITAJumpToUnit u02` (debug builds).
   - Debug builds have review mode on (review bar, every unit open). For the learner's screens, launch with `-ITANoReviewMode` too (`docs/02` § App configuration); leave it off only when the screenshot is of review mode.
2. `build_run_sim`, then `snapshot_ui` to get element references, then `tap` / `swipe` to navigate, then `screenshot`.
3. Save images to `artifacts/screens/<task-id>/<screen>-<device>-<mode>.png`.
4. Variants:
   - Dark mode: `xcrun simctl ui booted appearance dark`.
   - Large text: `xcrun simctl ui booted content_size accessibility-extra-extra-extra-large`.
   - iPad: boot an iPad simulator and repeat.
5. `type_text` sends **ASCII only**. For accented input, tap the accent keys in the app, or use an XCUITest.

### Mac screenshots

MobileBuildMCP's UI automation is iOS-only. Run `make screenshots`: the `ItalianoUITests/MacScreens` XCUITests drive the Mac app and attach screenshots.

### Review

Run the **ui-reviewer** subagent with your screenshots and the reference names. Fix blocking findings.

## Checklist before you finish

- [ ] Uses tokens and components only.
- [ ] Compact and regular layouts; no clipped text at AX5; dark mode readable.
- [ ] Identifiers and labels; VoiceOver order checked on the main path.
- [ ] Mac: keyboard path works (Return, Esc, shortcuts in `docs/06`; ⇧⌘H for hints).
- [ ] `python3 scripts/check-contrast.py` passes if you touched colours.
- [ ] Snapshots committed; screenshots saved; ui-reviewer verdict recorded in `PROGRESS.md`.

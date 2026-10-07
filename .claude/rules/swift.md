---
paths:
  - "App/**"
  - "Packages/**"
---

# Swift conventions

- Swift 6 language mode with complete strict concurrency. Fix warnings; don't silence them with `@unchecked Sendable` unless you explain why in a comment.
- `Packages/LearningCore` imports Foundation only, and never calls `Date()`, `UUID()` or `random` directly: inject `Clock`, `UUIDSource` and a seeded RNG.
- Tests use Swift Testing (`import Testing`, `@Test`, `#expect`). UI tests use XCUITest.
- View models are `@MainActor @Observable`; long work (replay, pack queries) runs off the main actor in `Storage`.
- No force unwraps or `try!` outside tests. Errors that reach the user follow `docs/02` § Logging and errors.
- Every interactive view gets `.accessibilityIdentifier("screen.element")` and a label. Italian goes through `ItalianText`.
- Platform differences live in adapters (`Platform/`) with `#if os(macOS)`, not scattered through views.

# Deferred — written, out of the MVP target

These compile-untested files are deliberately excluded from
`ios/project.yml`. They are not dead: each is one wiring step from being
live, and the core APIs they need already exist.

| File | Why it's out | What it needs |
| --- | --- | --- |
| `PackManager.swift` | The MVP bundles the pack as a build resource, so there is nothing to download. | A hosted `release.json` (`maestro-pack release` output) and a settings entry point. |
| `LLMBackend.swift` | The MVP is fully offline; the optional tutor is eval-gated and needs the scorecard bundled first. | `build/gates_resolved.json` as a resource, a Keychain-backed API key, and the privacy-ledger screen. |

To bring one back, add it to the `sources` list in `ios/project.yml` and
re-run `xcodegen`.

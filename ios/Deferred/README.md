# Deferred — written, out of the MVP target

`LLMBackend.swift` has moved into the target — see the tutor section of
`../README.md`. What's left here is deliberately excluded from
`ios/project.yml`. They are not dead: each is one wiring step from being
live, and the core APIs they need already exist.

| File | Why it's out | What it needs |
| --- | --- | --- |
| `PackManager.swift` | The MVP bundles the pack as a build resource, so there is nothing to download. | A hosted `release.json` (`maestro-pack release` output) and a settings entry point. |

To bring one back, add it to the `sources` list in `ios/project.yml` and
re-run `xcodegen`.

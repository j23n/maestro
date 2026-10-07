---
paths:
  - "content/**"
---

# Working in content/

- Load the `italian-content` skill before drafting or fixing anything here.
- Files with `review.status: approved` are read-only (a hook enforces it). Never change `review:` blocks yourself.
- IDs are permanent once released (`ids.lock`): then they can only be retired in `content/retired.yaml`, with the owner's approval. Never reuse an ID, even a dropped draft one.
- After every change, run `make annotate`, then `make check-content`, and fix errors before moving on. Never edit `.annotations/` lock files by hand.
- Prices, times and facts must agree across a unit's files (the task's menu is the price list) and with `story-bible.yaml`; new real-world facts go into its `facts_to_check`.
- Write everything fresh: no wording, tasks or examples from exam papers, syllabi or textbooks.

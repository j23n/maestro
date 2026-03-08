# Profile: show A0 scenarios after graduation

**Severity:** Low
**Area:** `templates/profilo.html`, profile page

## Problem

After graduating from A0 to A1, the profile's "Percorso" (learning path) grid only shows the 24 A1 scenarios. The 10 A0 scenarios that the student completed disappear entirely.

The profile does show `A0 gramm 15/15 · funz 12/12` in a summary line, confirming completion. But the individual A0 scenario cards (Benvenuto, Saluti, I numeri, etc.) are no longer visible.

## Why this matters

- Students may want to revisit A0 material for reference
- Seeing completed A0 scenarios provides a sense of accomplishment
- The A0→A1 transition feels like a reset rather than a continuation

## Suggestion

Show A0 scenarios in a collapsed/muted section above the A1 grid, e.g.:

```
A0 — Completato ✓  [expand/collapse]
  ● Benvenuto  ● Saluti  ● I numeri  ...

A1 — Percorso
  ○ Presentarsi  ○ Al bar  ○ Al ristorante  ...
```

Alternatively, keep them visible but styled differently (greyed out, checkmark overlay) so they don't dominate the page but remain accessible.

# A1 scenario selection: weight against abstract topics for fresh graduates

**Severity:** Low
**Area:** `lezione/selection.py`, `data/it/scenarios_a1.yaml`, scenario picker

## Problem

The A1 scenario picker (`pick_scenario`) uses weighted scoring with factors like unvisited bonus, weak GP overlap, cooldown, and jitter. However, it doesn't account for how recently the student graduated from A0.

Some A1 scenarios are quite concrete and well-suited for early A1:
- "Al bar" — ordering coffee
- "Presentarsi" — introducing yourself
- "Fare la spesa" — grocery shopping

Others are abstract and can frustrate students who just finished A0:
- "Capire e farsi capire" — communication meta-strategies
- "Opinioni e accordo" — expressing opinions, agreeing/disagreeing
- "Emozioni e stati d'animo" — describing complex emotions

In the test run, the very first A1 lesson picked "Capire e farsi capire" (communication strategies) — a meta-topic about how to ask for clarification. This is useful but jarring as a first "real Italian" experience after the structured A0 hand-holding.

## Suggestion

Add an optional `recommended_order` or `difficulty` field to A1 scenarios, or add a scoring factor in `pick_scenario` that boosts concrete, daily-life scenarios when the student has completed fewer than ~5 A1 lessons. This could be as simple as:

```python
# In pick_scenario scoring
if profile.completed_a1_lessons < 5:
    # Prefer concrete scenarios
    if scenario.slug in EARLY_A1_PREFERRED:
        score += 0.3
```

### Suggested early-A1 preferred scenarios
1. Presentarsi
2. Al bar
3. Al ristorante
4. Fare la spesa
5. La famiglia
6. La giornata

### Suggested later-A1 scenarios
- Capire e farsi capire
- Opinioni e accordo
- Permessi e regole
- Scrivere un messaggio

"""Generate FSRS-6 reference vectors from py-fsrs (pinned tag) for the Swift port.

Config mirrors the app: no learning/relearning steps, no fuzz, desired retention 0.9,
maximum interval 36500 days, default FSRS-6 parameters.
"""
import sys, json, random, math, subprocess
pyfsrs_path, out_path = sys.argv[1], sys.argv[2]
sys.path.insert(0, pyfsrs_path)
from datetime import datetime, timedelta, timezone
from fsrs import Scheduler, Card, Rating, State
from fsrs.scheduler import DEFAULT_PARAMETERS

tag = subprocess.run(["git", "-C", pyfsrs_path, "describe", "--tags"], capture_output=True, text=True).stdout.strip()
sha = subprocess.run(["git", "-C", pyfsrs_path, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()

sched = Scheduler(parameters=DEFAULT_PARAMETERS, desired_retention=0.9,
                  learning_steps=(), relearning_steps=(), maximum_interval=36500,
                  enable_fuzzing=False)
T0 = datetime(2026, 1, 5, 9, 0, 0, tzinfo=timezone.utc)

def iso(t):
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def raw_interval(stability):
    return (stability / sched._FACTOR) * ((sched.desired_retention ** (1 / sched._DECAY)) - 1)

def run(name, plan, note):
    """plan: list of (when, rating). when is ('abs', seconds_from_T0) | ('due', factor) |
    ('after', seconds_after_previous_review)."""
    card = Card(card_id=1, due=T0)
    steps = []
    prev_t = None
    for when, rating in plan:
        kind, val = when
        if kind == 'abs':
            t = T0 + timedelta(seconds=val)
        elif kind == 'after':
            t = prev_t + timedelta(seconds=val)
        elif kind == 'due':
            # review at prev + factor * (due - prev); factor 1 = exactly on the due date
            span = (card.due - prev_t).total_seconds()
            t = prev_t + timedelta(seconds=round(span * val))
        else:
            raise ValueError(kind)
        r_before = sched.get_card_retrievability(card, current_datetime=t) if card.last_review else None
        elapsed = (t - card.last_review).days if card.last_review else None
        card, _ = sched.review_card(card, Rating(rating), review_datetime=t)
        ri = raw_interval(card.stability)
        frac = ri - math.floor(ri)
        steps.append({
            "at": iso(t),
            "rating": rating,
            "elapsedDaysBefore": elapsed,
            "retrievabilityBefore": r_before,
            "stability": card.stability,
            "difficulty": card.difficulty,
            "intervalRaw": ri,
            "due": iso(card.due),
            "state": card.state.name,
            "nearHalf": abs(frac - 0.5) < 1e-6,
        })
        prev_t = t
    return {"name": name, "note": note, "start": iso(T0), "reviews": steps}

D = 86400
scenarios = []
for r, label in [(1, "again"), (2, "hard"), (3, "good"), (4, "easy")]:
    scenarios.append(run(f"first-review-{label}", [(('abs', 0), r)], "A new card's first review."))
scenarios.append(run("good-on-due-x8", [(('abs', 0), 3)] + [(('due', 1.0), 3)] * 7,
                     "Good on every due date."))
scenarios.append(run("again-then-recover", [(('abs', 0), 3), (('due', 1.0), 3), (('due', 1.0), 1),
                                            (('due', 1.0), 3), (('due', 1.0), 3), (('due', 1.0), 3)],
                     "A lapse in Review state with no relearning steps."))
scenarios.append(run("same-day-in-lesson", [(('abs', 0), 3), (('after', 600), 3), (('after', 1200), 1),
                                            (('after', 1800), 3), (('after', 3600), 3), (('due', 1.0), 3),
                                            (('due', 1.0), 3)],
                     "Several retrievals on the introduction day (short-term stability), then daily reviews."))
scenarios.append(run("early-reviews", [(('abs', 0), 3), (('due', 0.5), 3), (('due', 0.5), 3), (('due', 0.5), 3)],
                     "Reviews at half the scheduled interval."))
scenarios.append(run("late-reviews", [(('abs', 0), 3), (('due', 3.0), 3), (('due', 3.0), 1), (('due', 3.0), 3)],
                     "Reviews at three times the scheduled interval."))
scenarios.append(run("hard-easy-mix", [(('abs', 0), 2), (('due', 1.0), 4), (('due', 1.0), 2), (('due', 1.0), 4),
                                       (('due', 1.0), 3), (('due', 1.0), 2)],
                     "Hard and Easy ratings."))
scenarios.append(run("lapse-streak", [(('abs', 0), 1), (('after', 300), 1), (('after', D), 1), (('due', 1.0), 2),
                                      (('due', 1.0), 3), (('due', 1.0), 1), (('due', 1.0), 3)],
                     "Repeated Again ratings drive difficulty towards 10."))

rng = random.Random(20261007)
for i in range(24):
    plan = [(('abs', 0), rng.choice([1, 2, 3, 3, 3, 4]))]
    for _ in range(rng.randint(6, 14)):
        mode = rng.random()
        if mode < 0.25:
            when = ('after', rng.randint(60, 6 * 3600))          # same day
        elif mode < 0.45:
            when = ('after', rng.randint(D, 40 * D))             # arbitrary gap
        else:
            when = ('due', rng.choice([0.6, 0.9, 1.0, 1.0, 1.0, 1.3, 2.0]))
        plan.append((when, rng.choice([1, 2, 3, 3, 3, 3, 4])))
    scenarios.append(run(f"random-{i:02d}", plan, "Seeded random schedule (seed 20261007)."))

near_half = [s["name"] for s in scenarios if any(st["nearHalf"] for st in s["reviews"])]

doc = {
    "generator": "tools/fixtures/gen_fsrs_fixtures.py <path to a py-fsrs checkout at the tag below> fixtures/fsrs/fsrs6-reference.json",
    "reference": {"package": "py-fsrs (PyPI: fsrs)", "tag": tag, "commit": sha, "licence": "MIT"},
    "config": {
        "parameters": list(DEFAULT_PARAMETERS),
        "desiredRetention": 0.9,
        "learningSteps": [],
        "relearningSteps": [],
        "maximumInterval": 36500,
        "enableFuzzing": False,
    },
    "semantics": {
        "elapsedDays": "floor((reviewTime - lastReview) / 86400 s), i.e. Python timedelta.days; not calendar days",
        "sameDay": "elapsedDays < 1 uses the short-term stability formula (w17, w18, w19)",
        "intervalRounding": "Python round(): round half to even. Use .toNearestOrEven in Swift. Then clamp to [1, maximumInterval] days.",
        "due": "reviewTime + intervalDays * 86400 s",
        "firstReview": "initial stability w[rating-1]; initial difficulty clamped to [1, 10]; state becomes Review at once because learningSteps is empty",
        "tolerance": "compare stability, difficulty and retrievability with relative tolerance 1e-9; due dates must match exactly",
    },
    "scenariosWithNearHalfIntervals": near_half,
    "scenarios": scenarios,
}
json.dump(doc, open(out_path, "w"), indent=1)
print(len(scenarios), "scenarios;", sum(len(s["reviews"]) for s in scenarios), "reviews; near-half:", near_half)

#!/usr/bin/env python3
"""Automated curriculum walkthrough for A0 + half of A1.

Creates a student, goes through all 10 A0 lessons and 12 A1 lessons,
logs findings to stdout as structured JSON.
"""

import json
import sys
import time
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

BASE_URL = "http://100.64.0.4:8000"
COOKIE_FILE = Path("/tmp/maestro_test_cookie.txt")
TIMEOUT = 120.0

# Findings log
findings = []


def log(category: str, severity: str, message: str, context: dict | None = None):
    entry = {
        "category": category,
        "severity": severity,
        "message": message,
        "context": context or {},
    }
    findings.append(entry)
    print(f"  [{severity}] {category}: {message}", file=sys.stderr)


def _load_cookie() -> dict:
    if COOKIE_FILE.exists():
        return json.loads(COOKIE_FILE.read_text())
    return {}


def _save_cookie(data: dict):
    COOKIE_FILE.write_text(json.dumps(data))


def _cookies() -> dict:
    cookie = _load_cookie()
    return {"session": cookie["session"]} if "session" in cookie else {}


def _client() -> httpx.Client:
    return httpx.Client(
        base_url=BASE_URL, follow_redirects=True, timeout=TIMEOUT, cookies=_cookies()
    )


def _client_no_redirect() -> httpx.Client:
    return httpx.Client(
        base_url=BASE_URL, follow_redirects=False, timeout=TIMEOUT, cookies=_cookies()
    )


def soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


# ── Core actions ─────────────────────────────────────────────────────────


def create_student(name: str) -> str:
    email = f"testbot-{int(time.time())}@example.com"
    with httpx.Client(base_url=BASE_URL, timeout=TIMEOUT, follow_redirects=False) as c:
        resp = c.post(
            "/auth/signup",
            data={
                "email": email,
                "password": "testpass123",
                "password_confirm": "testpass123",
            },
        )
        session = resp.cookies.get("session")
        if session:
            _save_cookie({"session": session})
        return email


def start_lesson(duration: int = 15) -> dict:
    with _client() as c:
        resp = c.post("/lezione/", data={"duration": str(duration)})
    url = str(resp.url)
    parts = url.rstrip("/").split("/")
    lesson_id = None
    for i, p in enumerate(parts):
        if p == "lezione" and i + 1 < len(parts):
            candidate = parts[i + 1]
            if candidate not in ("", "generating") and len(candidate) > 10:
                lesson_id = candidate
            break
    return {"lesson_id": lesson_id, "url": url, "status": resp.status_code}


def poll_generating(lesson_id: str, max_wait: int = 180) -> dict:
    t0 = time.monotonic()
    polls = 0
    while True:
        polls += 1
        with _client() as c:
            resp = c.get(f"/lezione/{lesson_id}/generating")
        url = str(resp.url)
        if "generating" not in url:
            return {
                "ready": True,
                "url": url,
                "polls": polls,
                "elapsed_s": round(time.monotonic() - t0, 1),
            }
        s = soup(resp.text)
        err = s.find(class_="generating-sub")
        if err and s.find("form", action=lambda a: a and "retry" in a):
            return {"ready": False, "error": err.get_text(strip=True), "polls": polls}
        if time.monotonic() - t0 > max_wait:
            return {"ready": False, "error": "timeout", "polls": polls}
        time.sleep(3)


def get_activity(lesson_id: str, idx: int) -> dict:
    with _client() as c:
        resp = c.get(f"/lezione/{lesson_id}/activity/{idx}")
    url = str(resp.url)
    html = resp.text
    s = soup(html)

    # Detect type
    activity_type = "unknown"
    for form in s.find_all("form"):
        action = form.get("hx-post", "") or form.get("action", "")
        if "onboarding-submit" in action:
            activity_type = "onboarding"
            break
        if "drill-submit" in action:
            activity_type = "drill"
            break
        if "reading-submit" in action:
            activity_type = "reading"
            break
        if "writing-submit" in action:
            activity_type = "writing"
            break
        if "vocab-rate" in action:
            activity_type = "vocab_review"
            break
    if activity_type == "unknown":
        if s.find(attrs={"hx-get": lambda v: v and "vocab-reveal" in v}):
            activity_type = "vocab_review"
        elif s.find(class_="stub-icon"):
            activity_type = "speaking"
        else:
            for btn in s.find_all("button"):
                if "/complete" in btn.get("hx-post", ""):
                    activity_type = "grammar"
                    break

    title_el = s.find("h2") or s.find(class_="card-meta")
    title = title_el.get_text(strip=True) if title_el else ""

    # Content
    content = ""
    for cls in (
        "card-prompt",
        "prompt-text",
        "onboarding-prompt",
        "reading-text",
        "stub-desc",
        "grammar-content",
        "card-body",
    ):
        el = s.find(class_=cls)
        if el:
            content = el.get_text(separator=" ", strip=True)[:800]
            break
    if not content:
        card = s.find(class_="card")
        if card:
            content = card.get_text(separator=" ", strip=True)[:800]

    # Drill items
    drill_items = []
    for item_div in s.find_all(class_="drill-item"):
        prompt_el = item_div.find(class_="item-sentence")
        prompt = prompt_el.get_text(strip=True) if prompt_el else ""
        drill_items.append(prompt)
    textarea = s.find("textarea", {"name": "answers"})
    if textarea and not drill_items:
        drill_items.append("__free_form__")

    # Vocab info
    queue_el = s.find(class_="card-queue")
    vocab_total = 0
    if queue_el:
        txt = queue_el.get_text(strip=True)
        if "/" in txt:
            try:
                vocab_total = int(txt.split("/")[1].strip())
            except ValueError:
                pass

    # Check if lesson complete page
    if "/complete" in url:
        activity_type = "lesson_complete"

    return {
        "type": activity_type,
        "title": title,
        "content": content,
        "drill_items": drill_items,
        "vocab_total": vocab_total,
        "url": url,
        "html": html,
    }


def complete_activity(lesson_id: str, idx: int) -> str:
    """Mark a grammar/info activity as complete."""
    with _client_no_redirect() as c:
        resp = c.post(f"/lezione/{lesson_id}/activity/{idx}/complete")
    return resp.headers.get("HX-Redirect", resp.headers.get("location", ""))


def submit_onboarding(lesson_id: str, idx: int, answer: str) -> dict:
    with _client() as c:
        resp = c.post(
            f"/lezione/{lesson_id}/activity/{idx}/onboarding-submit",
            data={"answer": answer},
        )
    s = soup(resp.text)
    response_el = s.find(class_="onboarding-response-text")
    response_text = response_el.get_text(strip=True) if response_el else ""

    next_url = complete_activity(lesson_id, idx)
    return {"response": response_text, "next_url": next_url}


def submit_drill(lesson_id: str, idx: int, answers: list[str]) -> dict:
    from urllib.parse import urlencode

    body = urlencode([("answers", a) for a in answers])
    with _client() as c:
        resp = c.post(
            f"/lezione/{lesson_id}/activity/{idx}/drill-submit",
            content=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    s = soup(resp.text)
    result_ok = s.find(class_="result-ok")
    correct = result_ok is not None

    feedback_items = []
    for row in s.find_all(class_="item-row"):
        item = {}
        prompt_el = row.find(class_="item-prompt-text")
        item["prompt"] = prompt_el.get_text(strip=True) if prompt_el else ""
        ok_mark = row.find(class_="item-ok-mark")
        if ok_mark:
            item["correct"] = True
        else:
            item["correct"] = False
            wrong_el = row.find(class_="item-student-wrong")
            item["student_answer"] = wrong_el.get_text(strip=True) if wrong_el else ""
            correct_el = row.find(class_="item-correct-answer")
            item["correct_answer"] = (
                correct_el.get_text(strip=True) if correct_el else ""
            )
            expl_el = row.find(class_="item-explanation")
            item["explanation"] = expl_el.get_text(strip=True) if expl_el else ""
        feedback_items.append(item)

    continue_btn = s.find("a", class_="continue-btn")
    next_url = continue_btn["href"] if continue_btn and continue_btn.get("href") else ""

    return {"correct": correct, "feedback": feedback_items, "next_url": next_url}


def submit_reading(lesson_id: str, idx: int, answers: list[str]) -> dict:
    from urllib.parse import urlencode

    body = urlencode([("answers", a) for a in answers])
    with _client() as c:
        resp = c.post(
            f"/lezione/{lesson_id}/activity/{idx}/reading-submit",
            content=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    s = soup(resp.text)
    result_ok = s.find(class_="result-ok")
    correct = result_ok is not None
    continue_btn = s.find("a", class_="continue-btn")
    next_url = continue_btn["href"] if continue_btn and continue_btn.get("href") else ""
    return {"correct": correct, "next_url": next_url, "html": resp.text[:3000]}


def submit_writing(lesson_id: str, idx: int, answer: str) -> dict:
    with _client() as c:
        resp = c.post(
            f"/lezione/{lesson_id}/activity/{idx}/writing-submit",
            data={"answer": answer},
        )
    s = soup(resp.text)
    feedback_el = s.find(class_="item-secondary") or s.find(class_="result-ok")
    feedback = feedback_el.get_text(strip=True) if feedback_el else ""
    continue_btn = s.find("a", class_="continue-btn")
    next_url = continue_btn["href"] if continue_btn and continue_btn.get("href") else ""
    return {"feedback": feedback, "next_url": next_url, "html": resp.text[:3000]}


def reveal_and_rate_vocab(lesson_id: str, idx: int, total: int) -> dict:
    results = []
    for card_idx in range(total):
        # Reveal
        with _client() as c:
            resp = c.get(
                f"/lezione/{lesson_id}/activity/{idx}/vocab-reveal",
                params={"card_idx": str(card_idx)},
            )
        s = soup(resp.text)
        word_el = s.find(class_="word")
        trans_el = s.find(class_="translation")
        word = word_el.get_text(strip=True) if word_el else ""
        trans = trans_el.get_text(strip=True) if trans_el else ""
        results.append({"word": word, "translation": trans})

        # Rate as "good" (3)
        with _client_no_redirect() as c:
            c.post(
                f"/lezione/{lesson_id}/activity/{idx}/vocab-rate",
                data={"rating": "3", "card_idx": str(card_idx)},
            )
    return {"cards": results}


def skip_activity(lesson_id: str, idx: int) -> str:
    with _client_no_redirect() as c:
        resp = c.post(f"/lezione/{lesson_id}/activity/{idx}/skip")
    return resp.headers.get("HX-Redirect", resp.headers.get("location", ""))


def get_lesson_complete(lesson_id: str) -> dict:
    with _client() as c:
        resp = c.get(f"/lezione/{lesson_id}/complete")
    s = soup(resp.text)
    stats = {}
    for card in s.find_all(class_="stat-card"):
        label_el = card.find(class_="stat-label")
        value_el = card.find(class_="stat-value")
        if label_el and value_el:
            stats[label_el.get_text(strip=True)] = value_el.get_text(strip=True)
    feedback_el = s.find(class_="feedback-text")
    feedback = feedback_el.get_text(strip=True) if feedback_el else ""
    body = s.get_text(separator=" ", strip=True)[:2000]
    return {"stats": stats, "feedback": feedback, "body": body}


def get_profile() -> dict:
    with _client() as c:
        resp = c.get("/profilo")
    s = soup(resp.text)
    return {"body": s.get_text(separator=" ", strip=True)[:3000], "html": resp.text}


# ── Drill answer helpers ─────────────────────────────────────────────────

# For A0 static drills, we know the correct answers from the YAML.
# For A1 LLM-generated drills, we'll try reasonable answers and note failures.

A0_DRILL_ANSWERS = {
    # Lesson 1 - First words (5 items)
    "a0-01": [["Ciao", "Buongiorno", "Grazie", "favore", "Sì"]],
    # Lesson 2 - Saluti (7 items)
    "a0-02": [
        [
            "Buongiorno",
            "Buonasera",
            "Ciao",
            "Arrivederci",
            "presto",
            "domani",
            "Buonanotte",
        ]
    ],
    # Lesson 3 - Numeri: two drills (7 items each)
    "a0-03": [
        ["uno", "tre", "cinque", "sette", "dieci", "zero", "otto"],
        [
            "undici",
            "dodici",
            "quindici",
            "diciassette",
            "venti",
            "quattordici",
            "diciotto",
        ],
    ],
    # Lesson 4 - Sì e no (5 items)
    "a0-04": [["Non", "Parlo", "Sì", "No", "so"]],
    # Lesson 5 - Per favore (7 items)
    "a0-05": [["Grazie", "favore", "Prego", "Scusi", "dispiace", "Vorrei", "favore"]],
    # Lesson 6 - Il o la (7 items)
    "a0-06": [["il", "la", "il", "la", "la", "il", "questo"]],
    # Lesson 7 - Essere (6 items)
    "a0-07": [["sono", "sei", "è", "Sono", "Sei", "è"]],
    # Lesson 8 - Mi piace (5 items)
    "a0-08": [["piace", "Non", "viaggiare", "piacciono", "ragni"]],
    # Lesson 9 - Dove (6 items)
    "a0-09": [["Dov", "in", "di", "a", "Dove", "casa"]],
    # Lesson 10 - Ripasso (10 items)
    "a0-10": [
        [
            "Ciao",
            "chiamo",
            "cinque",
            "capisco",
            "Vorrei",
            "la",
            "Sono",
            "piace",
            "stazione",
            "Arrivederci",
        ]
    ],
}

ONBOARDING_ANSWERS = {
    "name": "Giulia",
    "persona_tags": "student, loves cooking, living abroad",
    "interests": "cooking, travel, wine, history, music",
    "goal": "travel to Italy and connect with Italian culture",
}


# ── Main walkthrough ─────────────────────────────────────────────────────


def walk_lesson(lesson_num: int, level: str) -> dict:
    """Start and complete one lesson. Returns summary."""
    tag = f"{level} Lesson {lesson_num}"
    print(f"\n{'=' * 60}", file=sys.stderr)
    print(f"  STARTING: {tag}", file=sys.stderr)
    print(f"{'=' * 60}", file=sys.stderr)

    t0 = time.monotonic()
    lesson_info = start_lesson(15)
    lesson_id = lesson_info["lesson_id"]

    if not lesson_id:
        log("bug", "CRITICAL", f"{tag}: Could not get lesson_id", lesson_info)
        return {"error": "no lesson_id"}

    # Poll for generation
    gen = poll_generating(lesson_id)
    gen_time = gen.get("elapsed_s", 0)
    if not gen.get("ready"):
        log("bug", "CRITICAL", f"{tag}: Lesson generation failed", gen)
        return {"error": "generation_failed", "detail": gen}

    if gen_time > 30:
        log("performance", "WARN", f"{tag}: Generation took {gen_time}s", gen)

    # Walk activities
    activities_done = []
    drill_idx_within_lesson = 0
    a0_slug = f"a0-{lesson_num:02d}" if level == "A0" else None
    idx = 0
    max_activities = 20  # safety

    while idx < max_activities:
        act = get_activity(lesson_id, idx)

        # If we landed on the complete page, we're done
        if act["type"] == "lesson_complete" or "/complete" in act["url"]:
            break

        act_summary = {"idx": idx, "type": act["type"], "title": act["title"]}
        print(f"  Activity {idx}: {act['type']} — {act['title']}", file=sys.stderr)

        if act["type"] == "grammar":
            # Check content quality
            if len(act["content"]) < 50:
                log(
                    "content",
                    "WARN",
                    f"{tag} act {idx}: Grammar content very short ({len(act['content'])} chars)",
                    {"title": act["title"]},
                )
            complete_activity(lesson_id, idx)
            act_summary["action"] = "completed"

        elif act["type"] == "onboarding":
            # Determine which field
            answer = "test answer"
            content_lower = act["content"].lower()
            if "name" in content_lower or "chiami" in act["title"].lower():
                answer = ONBOARDING_ANSWERS["name"]
            elif "interests" in content_lower or "piace" in content_lower:
                answer = ONBOARDING_ANSWERS["interests"]
            elif "describes" in content_lower or "chi sei" in act["title"].lower():
                answer = ONBOARDING_ANSWERS["persona_tags"]
            elif "why" in content_lower or "perché" in act["title"].lower():
                answer = ONBOARDING_ANSWERS["goal"]
            result = submit_onboarding(lesson_id, idx, answer)
            act_summary["action"] = "submitted"
            act_summary["response"] = result["response"]
            if not result["response"]:
                log("bug", "WARN", f"{tag} act {idx}: No onboarding response text", act)

        elif act["type"] == "drill":
            # Try correct answers for A0, reasonable guesses for A1
            n_items = len(act["drill_items"])
            if (
                a0_slug
                and a0_slug in A0_DRILL_ANSWERS
                and drill_idx_within_lesson < len(A0_DRILL_ANSWERS[a0_slug])
            ):
                answers = A0_DRILL_ANSWERS[a0_slug][drill_idx_within_lesson]
                # Adjust to match actual item count
                if len(answers) != n_items:
                    log(
                        "content",
                        "INFO",
                        f"{tag} act {idx}: Expected {len(answers)} items, got {n_items}",
                        {"items": act["drill_items"]},
                    )
                    answers = answers[:n_items] + ["???"] * max(
                        0, n_items - len(answers)
                    )
            else:
                # For A1 drills, try deliberate mix of correct/wrong to test feedback
                answers = ["???"] * n_items

            result = submit_drill(lesson_id, idx, answers)
            drill_idx_within_lesson += 1
            act_summary["action"] = "submitted"
            act_summary["n_items"] = n_items
            act_summary["correct"] = result["correct"]
            act_summary["feedback_count"] = len(result["feedback"])

            # Check feedback quality
            if not result["correct"]:
                for fb in result["feedback"]:
                    if (
                        not fb.get("correct")
                        and not fb.get("explanation")
                        and not fb.get("correct_answer")
                    ):
                        log(
                            "content",
                            "WARN",
                            f"{tag} act {idx}: Wrong answer but no explanation/correct_answer shown",
                            fb,
                        )

            if n_items == 0:
                log("bug", "ERROR", f"{tag} act {idx}: Drill has 0 items", act)

        elif act["type"] == "vocab_review":
            total = act["vocab_total"]
            if total == 0:
                # Try to detect from HTML
                log(
                    "content",
                    "INFO",
                    f"{tag} act {idx}: vocab_total=0, trying to proceed",
                    act,
                )
                total = 5  # guess
            try:
                result = reveal_and_rate_vocab(lesson_id, idx, total)
                act_summary["action"] = "reviewed"
                act_summary["cards"] = result["cards"]
                # Check for empty cards
                for c in result["cards"]:
                    if not c["word"]:
                        log("bug", "ERROR", f"{tag} act {idx}: Empty vocab card", c)
            except Exception as e:
                log("bug", "ERROR", f"{tag} act {idx}: Vocab review failed: {e}", {})
                skip_activity(lesson_id, idx)
                act_summary["action"] = "skipped (error)"

        elif act["type"] == "reading":
            # For reading, we need to find the questions and provide answers
            s = soup(act["html"])
            questions = s.find_all(class_="question-label")
            n_questions = len(questions)
            if n_questions == 0:
                # Try other selectors
                options = s.find_all("input", {"type": "radio"})
                if options:
                    # Multiple choice — pick first option for each question
                    answers = []
                    seen = set()
                    for opt in options:
                        name = opt.get("name", "")
                        if name not in seen:
                            seen.add(name)
                            answers.append(opt.get("value", "a"))
                    result = submit_reading(lesson_id, idx, answers)
                else:
                    result = submit_reading(lesson_id, idx, ["a"])
            else:
                # Try "a" for each question
                result = submit_reading(lesson_id, idx, ["a"] * n_questions)
            act_summary["action"] = "submitted"
            act_summary["correct"] = result.get("correct")

        elif act["type"] == "writing":
            # Submit a plausible answer
            answer = (
                "Mi chiamo Giulia. Sono una studentessa. Mi piace cucinare e viaggiare."
            )
            result = submit_writing(lesson_id, idx, answer)
            act_summary["action"] = "submitted"
            act_summary["feedback"] = result.get("feedback", "")

        elif act["type"] == "speaking":
            # Skip speaking activities
            skip_activity(lesson_id, idx)
            act_summary["action"] = "skipped (speaking stub)"

        else:
            log(
                "bug",
                "WARN",
                f"{tag} act {idx}: Unknown activity type '{act['type']}'",
                {"content": act["content"][:200]},
            )
            # Try to skip
            try:
                skip_activity(lesson_id, idx)
                act_summary["action"] = "skipped (unknown)"
            except Exception:
                complete_activity(lesson_id, idx)
                act_summary["action"] = "completed (unknown)"

        activities_done.append(act_summary)
        idx += 1

    # Get lesson completion
    try:
        complete_info = get_lesson_complete(lesson_id)
    except Exception as e:
        complete_info = {"error": str(e)}

    total_time = round(time.monotonic() - t0, 1)
    summary = {
        "tag": tag,
        "lesson_id": lesson_id,
        "generation_time_s": gen_time,
        "total_time_s": total_time,
        "activities": activities_done,
        "completion": complete_info,
    }

    print(
        f"  Completed {tag} in {total_time}s ({len(activities_done)} activities)",
        file=sys.stderr,
    )
    return summary


def main():
    print("=" * 60, file=sys.stderr)
    print("  MAESTRO CURRICULUM TEST", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    # Create account via signup
    account_email = create_student("TestBot Giulia")
    print(f"  Created account: {account_email}", file=sys.stderr)

    all_summaries = []

    # A0 lessons (10)
    for i in range(1, 11):
        try:
            summary = walk_lesson(i, "A0")
            all_summaries.append(summary)
        except Exception as e:
            log("bug", "CRITICAL", f"A0 Lesson {i} crashed: {e}", {})
            all_summaries.append({"tag": f"A0 Lesson {i}", "error": str(e)})

    # Check profile after A0
    print("\n  Checking profile after A0...", file=sys.stderr)
    profile = get_profile()
    if "A1" in profile["body"]:
        log("milestone", "INFO", "Profile shows A1 after completing A0", {})
    elif "A0" in profile["body"]:
        log(
            "milestone",
            "WARN",
            "Profile still shows A0 after completing all A0 lessons",
            {},
        )

    # A1 lessons (12 — half of 24)
    for i in range(1, 13):
        try:
            summary = walk_lesson(i, "A1")
            all_summaries.append(summary)
        except Exception as e:
            log("bug", "CRITICAL", f"A1 Lesson {i} crashed: {e}", {})
            all_summaries.append({"tag": f"A1 Lesson {i}", "error": str(e)})

    # Final profile check
    print("\n  Checking final profile...", file=sys.stderr)
    final_profile = get_profile()

    # Output results
    output = {
        "account_email": account_email,
        "summaries": all_summaries,
        "findings": findings,
        "final_profile_text": final_profile["body"],
    }

    print(json.dumps(output, indent=2, default=str))


if __name__ == "__main__":
    main()

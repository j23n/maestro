#!/usr/bin/env python3
"""Thin CLI helper for automated user testing of the Maestro app.

Usage:
    uv run python scripts/user_test_client.py <command> [args]

All commands print a single JSON object to stdout. Errors go to stderr.
Cookie is persisted to /tmp/maestro_test_cookie.txt.
"""

import json
import sys
import time
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

BASE_URL = "http://localhost:8000"
COOKIE_FILE = Path("/tmp/maestro_test_cookie.txt")
TIMEOUT = 120.0


def _load_cookie() -> dict:
    if COOKIE_FILE.exists():
        return json.loads(COOKIE_FILE.read_text())
    return {}


def _save_cookie(data: dict):
    existing = _load_cookie()
    existing.update(data)
    COOKIE_FILE.write_text(json.dumps(existing))


def _client(*, follow_redirects: bool = True) -> httpx.Client:
    cookie = _load_cookie()
    cookies = {}
    if "session" in cookie:
        cookies["session"] = cookie["session"]
    if "csrftoken" in cookie:
        cookies["csrftoken"] = cookie["csrftoken"]

    csrf_token = cookie.get("csrftoken", "")

    def _inject_csrf(request: httpx.Request) -> None:
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            request.headers["x-csrftoken"] = csrf_token

    return httpx.Client(
        base_url=BASE_URL,
        follow_redirects=follow_redirects,
        timeout=TIMEOUT,
        cookies=cookies,
        event_hooks={"request": [_inject_csrf]},
    )


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def _out(obj: dict):
    print(json.dumps(obj, default=str))


def _detect_activity_type(soup: BeautifulSoup) -> str:
    # Check form action URLs
    for form in soup.find_all("form"):
        action = form.get("hx-post", "") or form.get("action", "")
        if "onboarding-submit" in action:
            return "onboarding"
        if "drill-submit" in action:
            return "drill"
        if "reading-submit" in action:
            return "reading"
        if "writing-submit" in action:
            return "writing"
        if "vocab-rate" in action:
            return "vocab_review"
    # Check for vocab reveal button
    if soup.find(attrs={"hx-get": lambda v: v and "vocab-reveal" in v}):
        return "vocab_review"
    # Check for speaking stub
    if soup.find(class_="stub-icon"):
        return "speaking"
    # Check for grammar complete button
    for btn in soup.find_all("button"):
        hx_post = btn.get("hx-post", "")
        if "/complete" in hx_post:
            return "grammar"
    # Fallback
    return "unknown"


def _extract_drill_items(soup: BeautifulSoup) -> list[dict]:
    items = []
    for item_div in soup.find_all(class_="drill-item"):
        prompt_el = item_div.find(class_="item-sentence")
        prompt = prompt_el.get_text(strip=True) if prompt_el else ""
        items.append({"prompt": prompt, "input_name": "answers"})
    # Free-form textarea
    textarea = soup.find("textarea", {"name": "answers"})
    if textarea and not items:
        items.append({"prompt": "free_form", "input_name": "answers"})
    return items


def _extract_questions(soup: BeautifulSoup) -> list[str]:
    questions = []
    for q in soup.find_all(class_="question-label"):
        questions.append(q.get_text(strip=True))
    return questions


# ── Commands ────────────────────────────────────────────────────────────


def create_student(name: str):
    t0 = time.monotonic()
    email = f"testbot-{int(time.time())}@example.com"
    with httpx.Client(base_url=BASE_URL, timeout=TIMEOUT, follow_redirects=False) as c:
        # Fetch signup page to obtain CSRF cookie
        c.get("/auth/signup")
        csrf = c.cookies.get("csrftoken", "")
        resp = c.post(
            "/auth/signup",
            data={
                "email": email,
                "password": "testpass123",
                "password_confirm": "testpass123",
                "csrftoken": csrf,
            },
        )
        session = resp.cookies.get("session")
        if session:
            _save_cookie({"session": session, "csrftoken": csrf})
    elapsed = int((time.monotonic() - t0) * 1000)
    _out(
        {
            "email": email,
            "redirected_to": resp.headers.get("location", ""),
            "elapsed_ms": elapsed,
        }
    )


def get_page(path: str):
    t0 = time.monotonic()
    with _client() as c:
        resp = c.get(path)
    elapsed = int((time.monotonic() - t0) * 1000)
    soup = _soup(resp.text)
    title_tag = soup.find("title")
    _out(
        {
            "status": resp.status_code,
            "final_url": str(resp.url),
            "title": title_tag.get_text(strip=True) if title_tag else "",
            "body_text": soup.get_text(separator=" ", strip=True)[:2000],
            "body_html": resp.text[:5000],
            "elapsed_ms": elapsed,
        }
    )


def start_lesson(duration: int = 20):
    t0 = time.monotonic()
    with _client() as c:
        resp = c.post("/lezione/", data={"duration": str(duration)})
    elapsed = int((time.monotonic() - t0) * 1000)
    final_url = str(resp.url)
    # Parse lesson_id from URL
    parts = final_url.rstrip("/").split("/")
    lesson_id = None
    state = "unknown"
    activity_idx = 0
    for i, p in enumerate(parts):
        if p == "lezione" and i + 1 < len(parts):
            candidate = parts[i + 1]
            if candidate not in ("", "generating") and len(candidate) > 10:
                lesson_id = candidate
            break
    if "generating" in final_url:
        state = "generating"
    elif "activity" in final_url:
        state = "activity"
        try:
            activity_idx = int(parts[-1])
        except (ValueError, IndexError):
            pass
    _out(
        {
            "lesson_id": lesson_id,
            "state": state,
            "activity_idx": activity_idx,
            "elapsed_ms": elapsed,
            "final_url": final_url,
        }
    )


def poll_generating(lesson_id: str):
    t0 = time.monotonic()
    max_wait = 180
    polls = 0
    while True:
        polls += 1
        with _client() as c:
            resp = c.get(f"/lezione/{lesson_id}/generating")
        final_url = str(resp.url)
        elapsed = int((time.monotonic() - t0) * 1000)
        if "generating" not in final_url:
            _out(
                {
                    "ready": True,
                    "next_url": final_url.replace(BASE_URL, ""),
                    "elapsed_ms": elapsed,
                    "polls": polls,
                    "error": None,
                }
            )
            return
        # Check for generation error
        soup = _soup(resp.text)
        error_el = soup.find(class_="generating-sub")
        if error_el and soup.find("form", action=lambda a: a and "retry" in a):
            _out(
                {
                    "ready": False,
                    "next_url": None,
                    "elapsed_ms": elapsed,
                    "polls": polls,
                    "error": error_el.get_text(strip=True),
                }
            )
            return
        if (time.monotonic() - t0) > max_wait:
            _out(
                {
                    "ready": False,
                    "next_url": None,
                    "elapsed_ms": elapsed,
                    "polls": polls,
                    "error": "timeout",
                }
            )
            return
        time.sleep(3)


def get_activity(lesson_id: str, idx: str):
    t0 = time.monotonic()
    with _client() as c:
        resp = c.get(f"/lezione/{lesson_id}/activity/{idx}")
    elapsed = int((time.monotonic() - t0) * 1000)
    final_url = str(resp.url)
    soup = _soup(resp.text)
    activity_type = _detect_activity_type(soup)
    title_el = soup.find("h2") or soup.find(class_="card-meta")
    title = title_el.get_text(strip=True) if title_el else ""
    # Content snippet
    content = ""
    for cls in (
        "card-prompt",
        "prompt-text",
        "onboarding-prompt",
        "reading-text",
        "stub-desc",
    ):
        el = soup.find(class_=cls)
        if el:
            content = el.get_text(strip=True)[:500]
            break
    if not content:
        card = soup.find(class_="card")
        if card:
            content = card.get_text(separator=" ", strip=True)[:500]
    drill_items = _extract_drill_items(soup)
    questions = _extract_questions(soup)
    # Vocab card count
    queue_el = soup.find(class_="card-queue")
    vocab_total = 0
    if queue_el:
        txt = queue_el.get_text(strip=True)
        if "/" in txt:
            try:
                vocab_total = int(txt.split("/")[1].strip())
            except ValueError:
                pass
    _out(
        {
            "type": activity_type,
            "title": title,
            "content_snippet": content,
            "drill_items": drill_items,
            "vocab_total": vocab_total,
            "questions": questions,
            "elapsed_ms": elapsed,
            "final_url": final_url,
            "body_html": resp.text[:8000],
        }
    )


def submit_grammar(lesson_id: str, idx: str):
    t0 = time.monotonic()
    with _client(follow_redirects=False) as c:
        resp = c.post(f"/lezione/{lesson_id}/activity/{idx}/complete")
    elapsed = int((time.monotonic() - t0) * 1000)
    next_url = resp.headers.get("HX-Redirect", resp.headers.get("location", ""))
    _out({"next_url": next_url, "status": resp.status_code, "elapsed_ms": elapsed})


def submit_onboarding(lesson_id: str, idx: str, answer: str):
    t0 = time.monotonic()
    with _client() as c:
        # First submit the answer
        resp = c.post(
            f"/lezione/{lesson_id}/activity/{idx}/onboarding-submit",
            data={"answer": answer},
        )
    soup = _soup(resp.text)
    response_el = soup.find(class_="onboarding-response-text")
    response_text = response_el.get_text(strip=True) if response_el else ""

    # Then complete the activity
    with _client(follow_redirects=False) as c:
        resp2 = c.post(f"/lezione/{lesson_id}/activity/{idx}/complete")
    elapsed = int((time.monotonic() - t0) * 1000)
    next_url = resp2.headers.get("HX-Redirect", resp2.headers.get("location", ""))
    _out({"response_text": response_text, "next_url": next_url, "elapsed_ms": elapsed})


def submit_drill(lesson_id: str, idx: str, answers_json: str):
    t0 = time.monotonic()
    answers = json.loads(answers_json)
    # Build form data with repeated "answers" fields
    from urllib.parse import urlencode

    body = urlencode([("answers", a) for a in answers])
    with _client() as c:
        resp = c.post(
            f"/lezione/{lesson_id}/activity/{idx}/drill-submit",
            content=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    elapsed = int((time.monotonic() - t0) * 1000)
    soup = _soup(resp.text)
    # Parse result
    result_ok = soup.find(class_="result-ok")
    result_wrong = soup.find(class_="result-wrong")
    correct = result_ok is not None
    result_text = ""
    if result_ok:
        result_text = result_ok.get_text(strip=True)
    elif result_wrong:
        result_text = result_wrong.get_text(strip=True)
    # Feedback items
    feedback_items = []
    for row in soup.find_all(class_="item-row"):
        item = {}
        prompt_el = row.find(class_="item-prompt-text")
        item["prompt"] = prompt_el.get_text(strip=True) if prompt_el else ""
        ok_mark = row.find(class_="item-ok-mark")
        if ok_mark:
            item["correct"] = True
            item["student_answer"] = ok_mark.get_text(strip=True).lstrip("✓ ")
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
    # Next URL
    continue_btn = soup.find("a", class_="continue-btn")
    next_url = continue_btn["href"] if continue_btn and continue_btn.get("href") else ""
    _out(
        {
            "correct": correct,
            "result_text": result_text,
            "feedback_items": feedback_items,
            "next_url": next_url,
            "elapsed_ms": elapsed,
            "body_html": resp.text[:5000],
        }
    )


def submit_vocab_card(lesson_id: str, idx: str, card_idx: str, rating: str):
    t0 = time.monotonic()
    with _client(follow_redirects=False) as c:
        resp = c.post(
            f"/lezione/{lesson_id}/activity/{idx}/vocab-rate",
            data={"rating": rating, "card_idx": card_idx},
        )
    elapsed = int((time.monotonic() - t0) * 1000)
    next_url = resp.headers.get("HX-Redirect", resp.headers.get("location", ""))
    _out({"next_url": next_url, "status": resp.status_code, "elapsed_ms": elapsed})


def reveal_vocab(lesson_id: str, idx: str, card_idx: str):
    t0 = time.monotonic()
    with _client() as c:
        resp = c.get(
            f"/lezione/{lesson_id}/activity/{idx}/vocab-reveal",
            params={"card_idx": card_idx},
        )
    elapsed = int((time.monotonic() - t0) * 1000)
    soup = _soup(resp.text)
    word_el = soup.find(class_="word")
    translation_el = soup.find(class_="translation")
    pos_el = soup.find(class_="pos")
    _out(
        {
            "word": word_el.get_text(strip=True) if word_el else "",
            "translation": translation_el.get_text(strip=True)
            if translation_el
            else "",
            "pos": pos_el.get_text(strip=True) if pos_el else "",
            "elapsed_ms": elapsed,
        }
    )


def submit_reading(lesson_id: str, idx: str, answers_json: str):
    t0 = time.monotonic()
    answers = json.loads(answers_json)
    from urllib.parse import urlencode

    body = urlencode([("answers", a) for a in answers])
    with _client() as c:
        resp = c.post(
            f"/lezione/{lesson_id}/activity/{idx}/reading-submit",
            content=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    elapsed = int((time.monotonic() - t0) * 1000)
    soup = _soup(resp.text)
    result_ok = soup.find(class_="result-ok")
    result_wrong = soup.find(class_="result-wrong")
    correct = result_ok is not None
    result_text = (result_ok or result_wrong or soup).get_text(strip=True)[:200]
    continue_btn = soup.find("a", class_="continue-btn")
    next_url = continue_btn["href"] if continue_btn and continue_btn.get("href") else ""
    _out(
        {
            "correct": correct,
            "result_text": result_text,
            "next_url": next_url,
            "elapsed_ms": elapsed,
            "body_html": resp.text[:5000],
        }
    )


def submit_writing(lesson_id: str, idx: str, answer: str):
    t0 = time.monotonic()
    with _client() as c:
        resp = c.post(
            f"/lezione/{lesson_id}/activity/{idx}/writing-submit",
            data={"answer": answer},
        )
    elapsed = int((time.monotonic() - t0) * 1000)
    soup = _soup(resp.text)
    continue_btn = soup.find("a", class_="continue-btn")
    next_url = continue_btn["href"] if continue_btn and continue_btn.get("href") else ""
    # Extract feedback
    feedback_text = ""
    for cls in ("item-secondary", "result-ok", "result-wrong"):
        el = soup.find(class_=cls)
        if el:
            feedback_text += el.get_text(strip=True) + " "
    _out(
        {
            "feedback": feedback_text.strip(),
            "next_url": next_url,
            "elapsed_ms": elapsed,
            "body_html": resp.text[:5000],
        }
    )


def submit_skip(lesson_id: str, idx: str):
    t0 = time.monotonic()
    with _client(follow_redirects=False) as c:
        resp = c.post(f"/lezione/{lesson_id}/activity/{idx}/skip")
    elapsed = int((time.monotonic() - t0) * 1000)
    next_url = resp.headers.get("HX-Redirect", resp.headers.get("location", ""))
    _out({"next_url": next_url, "status": resp.status_code, "elapsed_ms": elapsed})


def get_complete(lesson_id: str):
    t0 = time.monotonic()
    with _client() as c:
        resp = c.get(f"/lezione/{lesson_id}/complete")
    elapsed = int((time.monotonic() - t0) * 1000)
    soup = _soup(resp.text)
    # Parse stats
    stats = {}
    for card in soup.find_all(class_="stat-card"):
        label_el = card.find(class_="stat-label")
        value_el = card.find(class_="stat-value")
        if label_el and value_el:
            stats[label_el.get_text(strip=True)] = value_el.get_text(strip=True)
    # Feedback
    feedback_el = soup.find(class_="feedback-text")
    feedback_summary = feedback_el.get_text(strip=True) if feedback_el else ""
    # Weak grammar
    weak = []
    for link in soup.find_all(class_="review-link"):
        weak.append(link.get_text(strip=True))
    # Activity summary
    activities = []
    for item in soup.find_all(class_="summary-item"):
        status_el = item.find(class_="summary-status")
        title_el = item.find(class_="summary-title")
        activities.append(
            {
                "status": status_el.get_text(strip=True) if status_el else "",
                "title": title_el.get_text(strip=True) if title_el else "",
            }
        )
    _out(
        {
            "status": resp.status_code,
            "stats": stats,
            "feedback_summary": feedback_summary,
            "weak_grammar": weak,
            "activities": activities,
            "elapsed_ms": elapsed,
            "body_text": soup.get_text(separator=" ", strip=True)[:3000],
        }
    )


def get_profile():
    t0 = time.monotonic()
    with _client() as c:
        resp = c.get("/profilo")
    elapsed = int((time.monotonic() - t0) * 1000)
    soup = _soup(resp.text)
    body_text = soup.get_text(separator=" ", strip=True)[:3000]
    _out(
        {
            "status": resp.status_code,
            "body_text": body_text,
            "body_html": resp.text[:8000],
            "elapsed_ms": elapsed,
        }
    )


# ── Main dispatch ───────────────────────────────────────────────────────

COMMANDS = {
    "create_student": lambda args: create_student(args[0]),
    "get_page": lambda args: get_page(args[0]),
    "start_lesson": lambda args: start_lesson(int(args[0]) if args else 20),
    "poll_generating": lambda args: poll_generating(args[0]),
    "get_activity": lambda args: get_activity(args[0], args[1]),
    "submit_grammar": lambda args: submit_grammar(args[0], args[1]),
    "submit_onboarding": lambda args: submit_onboarding(args[0], args[1], args[2]),
    "submit_drill": lambda args: submit_drill(args[0], args[1], args[2]),
    "submit_vocab_card": lambda args: submit_vocab_card(
        args[0], args[1], args[2], args[3]
    ),
    "reveal_vocab": lambda args: reveal_vocab(args[0], args[1], args[2]),
    "submit_reading": lambda args: submit_reading(args[0], args[1], args[2]),
    "submit_writing": lambda args: submit_writing(args[0], args[1], args[2]),
    "submit_skip": lambda args: submit_skip(args[0], args[1]),
    "get_complete": lambda args: get_complete(args[0]),
    "get_profile": lambda args: get_profile(),
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(f"Usage: {sys.argv[0]} <command> [args]", file=sys.stderr)
        print(f"Commands: {', '.join(sorted(COMMANDS.keys()))}", file=sys.stderr)
        sys.exit(1)
    cmd = sys.argv[1]
    args = sys.argv[2:]
    try:
        COMMANDS[cmd](args)
    except Exception as e:
        print(json.dumps({"error": str(e), "type": type(e).__name__}))
        sys.exit(1)


if __name__ == "__main__":
    main()

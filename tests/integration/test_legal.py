import pytest

from maestro.models import (
    DrillAttempt,
    GeneratedDrill,
    LanguageProgress,
    LearningEvent,
    LearningProfile,
    Lesson,
    LLMUsageRecord,
    Student,
    Account,
    UserVocabularyCard,
    VocabularyWord,
)


class TestLegalPages:
    def test_privacy_page(self, test_app):
        resp = test_app.get("/legal/privacy")
        assert resp.status_code == 200
        assert "Privacy Policy" in resp.text

    def test_terms_page(self, test_app):
        resp = test_app.get("/legal/terms")
        assert resp.status_code == 200
        assert "Terms of Service" in resp.text

    def test_privacy_page_no_auth(self, auth_app):
        resp = auth_app.get("/legal/privacy")
        assert resp.status_code == 200
        assert "Privacy Policy" in resp.text

    def test_terms_page_no_auth(self, auth_app):
        resp = auth_app.get("/legal/terms")
        assert resp.status_code == 200
        assert "Terms of Service" in resp.text


class TestAccountDelete:
    @pytest.fixture
    async def populated_student(self, student, account):
        """Create related records for the student so we can verify they get deleted."""
        profile = await LearningProfile.find_one({"student_id": student.id})
        if profile is None:
            profile = LearningProfile(
                student_id=student.id,
                progress={"it": LanguageProgress(cefr_estimate="A1")},
            )
            await profile.insert()
        else:
            profile.active_progress.cefr_estimate = "A1"
            await profile.save()

        lesson = Lesson(student_id=student.id, duration_minutes=10)
        await lesson.insert()

        event = LearningEvent(student_id=student.id, lesson_id=lesson.id)
        await event.insert()

        word = VocabularyWord(word="ciao", part_of_speech="interj.")
        await word.insert()
        card = UserVocabularyCard(student_id=student.id, word=word.id)
        await card.insert()

        drill = GeneratedDrill(
            student_id=student.id,
            grammar_point_code="pres_ind",
            cefr_level="A1",
            exercise_type="fill_blank",
            prompt="test",
        )
        await drill.insert()

        attempt = DrillAttempt(
            student_id=student.id,
            generated_drill=drill.id,
            student_answer="test",
        )
        await attempt.insert()

        usage = LLMUsageRecord(
            student_id=student.id,
            entity_id=lesson.id,
            call_type="lesson_plan",
            model="test",
            input_tokens=10,
            output_tokens=10,
            cost_usd=0.01,
        )
        await usage.insert()

        return student

    def test_delete_account_requires_auth(self, auth_app):
        resp = auth_app.delete("/account", follow_redirects=False)
        # RedirectToLogin exception handler returns 307
        assert resp.status_code == 307
        assert resp.headers["location"].endswith("/auth/login")

    def test_delete_account(self, test_app, populated_student, account):
        resp = test_app.delete("/account", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/"

    @pytest.mark.anyio
    async def test_delete_account_removes_all_data(
        self, test_app, populated_student, account
    ):
        sid = populated_student.id

        test_app.delete("/account", follow_redirects=False)

        assert await Student.get(sid) is None
        assert await Account.get(account.id) is None
        assert await LearningProfile.find_one(LearningProfile.student_id == sid) is None
        assert await Lesson.find(Lesson.student_id == sid).count() == 0
        assert await LearningEvent.find(LearningEvent.student_id == sid).count() == 0
        assert (
            await UserVocabularyCard.find(UserVocabularyCard.student_id == sid).count()
            == 0
        )
        assert await GeneratedDrill.find(GeneratedDrill.student_id == sid).count() == 0
        assert await DrillAttempt.find(DrillAttempt.student_id == sid).count() == 0
        assert await LLMUsageRecord.find(LLMUsageRecord.student_id == sid).count() == 0


class TestAccountExport:
    def test_export_requires_auth(self, auth_app):
        resp = auth_app.get("/account/export", follow_redirects=False)
        assert resp.status_code == 307
        assert resp.headers["location"].endswith("/auth/login")

    def test_export_returns_json(self, test_app):
        resp = test_app.get("/account/export")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/json"
        assert "attachment" in resp.headers.get("content-disposition", "")

        data = resp.json()
        assert "account" in data
        assert "student" in data
        assert "learning_profile" in data
        assert "lessons" in data
        assert "learning_events" in data
        assert "vocabulary_cards" in data

    def test_export_excludes_password_hash(self, test_app):
        resp = test_app.get("/account/export")
        data = resp.json()
        assert "password_hash" not in data["account"]

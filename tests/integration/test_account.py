import pytest
from pymongo.errors import DuplicateKeyError
from maestro.models import (
    Account,
    DrillAttempt,
    ExerciseType,
    GeneratedDrill,
    LearningEvent,
    LearningProfile,
    Lesson,
    LessonStatus,
    LLMUsageRecord,
    CallType,
    Student,
    UserVocabularyCard,
    VocabularyWord,
)


@pytest.mark.integration
async def test_account_student_link(db):
    student = Student(name="Maria")
    await student.insert()

    account = Account(
        email="maria@example.com",
        password_hash="$2b$12$fakehash",
        student_id=student.id,
    )
    await account.insert()

    found = await Account.find_one(Account.email == "maria@example.com")
    assert found is not None
    assert found.student_id == student.id

    linked_student = await Student.get(found.student_id)
    assert linked_student is not None
    assert linked_student.name == "Maria"


@pytest.mark.integration
async def test_account_email_unique_constraint(db):
    student1 = Student(name="Alice")
    await student1.insert()
    student2 = Student(name="Bob")
    await student2.insert()

    account1 = Account(
        email="same@example.com",
        password_hash="hash1",
        student_id=student1.id,
    )
    await account1.insert()

    account2 = Account(
        email="same@example.com",
        password_hash="hash2",
        student_id=student2.id,
    )
    with pytest.raises(DuplicateKeyError):
        await account2.insert()


@pytest.mark.integration
async def test_account_created_at_auto_set(db):
    student = Student(name="Test")
    await student.insert()

    account = Account(
        email="auto@example.com",
        password_hash="hash",
        student_id=student.id,
    )
    await account.insert()

    found = await Account.get(account.id)
    assert found.created_at is not None


# ---------------------------------------------------------------------------
# GDPR account deletion completeness
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_gdpr_deletion_removes_all_user_data(test_app, student, account):
    """DELETE /account should remove all data associated with the student."""
    sid = student.id

    # Seed data across every collection that stores student_id
    await LearningProfile(student_id=sid).insert()
    lesson = Lesson(
        student_id=sid,
        status=LessonStatus.COMPLETED,
        duration_minutes=10,
        generating=False,
        activities=[],
        current_index=0,
    )
    await lesson.insert()
    await LearningEvent(
        student_id=sid,
        lesson_id=lesson.id,
        activity_type="drill",
        activity_index=0,
        evidence_type="productive",
    ).insert()
    drill = GeneratedDrill(
        student_id=sid,
        grammar_point_code="GP_001",
        cefr_level="A1",
        exercise_type=ExerciseType.FILL_BLANK,
        prompt="test",
        scenario_slug="test",
    )
    await drill.insert()
    await DrillAttempt(
        student_id=sid,
        generated_drill=drill,
        correct=True,
    ).insert()
    vocab_word = VocabularyWord(word="ciao", part_of_speech="interj.")
    await vocab_word.insert()
    await UserVocabularyCard(student_id=sid, word=vocab_word).insert()
    await LLMUsageRecord(
        student_id=sid,
        entity_id=lesson.id,
        call_type=CallType.SCORER_SINGLE,
        model="test-model",
        input_tokens=10,
        output_tokens=10,
        cost_usd=0.001,
        duration_ms=100,
    ).insert()

    # Verify data exists
    assert await LearningProfile.find_one({"student_id": sid}) is not None
    assert await Lesson.find_one({"student_id": sid}) is not None
    assert await LearningEvent.find_one({"student_id": sid}) is not None
    assert await GeneratedDrill.find_one({"student_id": sid}) is not None
    assert await DrillAttempt.find_one({"student_id": sid}) is not None
    assert await UserVocabularyCard.find_one({"student_id": sid}) is not None
    assert await LLMUsageRecord.find_one({"student_id": sid}) is not None

    # Perform deletion
    response = test_app.delete("/account", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/"

    # Verify ALL data is gone
    assert await Student.get(sid) is None
    assert await Account.get(account.id) is None
    assert await LearningProfile.find_one({"student_id": sid}) is None
    assert await Lesson.find_one({"student_id": sid}) is None
    assert await LearningEvent.find_one({"student_id": sid}) is None
    assert await GeneratedDrill.find_one({"student_id": sid}) is None
    assert await DrillAttempt.find_one({"student_id": sid}) is None
    assert await UserVocabularyCard.find_one({"student_id": sid}) is None
    assert await LLMUsageRecord.find_one({"student_id": sid}) is None

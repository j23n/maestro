import pytest
from pymongo.errors import DuplicateKeyError
from maestro.models import Account, Student


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

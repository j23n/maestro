"""
Migration: create an Account for an existing Student that has none.

Prompts for email and password, then links the Account to the Student.
Idempotent — skips if the Student already has an Account.

Run with:
  python scripts/migrate_create_account.py --student-name johannes
"""

import asyncio
import getpass
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def migrate(student_name: str):
    import bcrypt
    from maestro.db import init_db
    from maestro.models import Account, Student

    await init_db()

    student = await Student.find_one({"name": student_name})
    if not student:
        logger.error(f"No student found with name '{student_name}'")
        return

    existing = await Account.find_one({"student_id": student.id})
    if existing:
        logger.info(f"Student '{student_name}' already has account: {existing.email}")
        return

    email = input("Email: ").strip().lower()
    password = getpass.getpass("Password: ")
    if len(password) < 8:
        logger.error("Password must be at least 8 characters")
        return

    account = Account(
        email=email,
        password_hash=bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(),
        student_id=student.id,
    )
    await account.insert()
    logger.info(
        f"Created account {email} linked to student '{student_name}' ({student.id})"
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--student-name", required=True, help="Name of the existing student"
    )
    args = parser.parse_args()
    asyncio.run(migrate(student_name=args.student_name))

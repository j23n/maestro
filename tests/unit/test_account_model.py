import pytest
from datetime import datetime
from beanie import PydanticObjectId
from maestro.models import Account
from maestro.utils import utcnow


def _make_account(**overrides):
    """Build an Account using model_construct to avoid Beanie init requirement."""
    defaults = dict(
        email="test@example.com",
        password_hash="$2b$12$fakehash",
        student_id=PydanticObjectId(),
        email_verified=False,
        stripe_customer_id=None,
        subscription_tier="free",
        is_admin=False,
        created_at=utcnow(),
    )
    defaults.update(overrides)
    return Account.model_construct(**defaults)


@pytest.mark.unit
def test_account_required_fields_and_defaults():
    account = _make_account()
    assert account.email == "test@example.com"
    assert account.password_hash == "$2b$12$fakehash"
    assert account.email_verified is False
    assert account.subscription_tier == "free"
    assert account.is_admin is False
    assert account.stripe_customer_id is None
    assert isinstance(account.created_at, datetime)


@pytest.mark.unit
def test_account_optional_fields():
    account = _make_account(
        email="pro@example.com",
        password_hash="hash",
        stripe_customer_id="cus_abc123",
        subscription_tier="pro",
        is_admin=True,
        email_verified=True,
    )
    assert account.stripe_customer_id == "cus_abc123"
    assert account.subscription_tier == "pro"
    assert account.is_admin is True
    assert account.email_verified is True


@pytest.mark.unit
def test_account_collection_name():
    assert Account.Settings.name == "accounts"

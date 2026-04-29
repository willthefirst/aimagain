import uuid

import pytest
from pydantic import ValidationError

from src.schemas.post import PostCreate, PostUpdate


def test_post_create_accepts_title_and_body():
    p = PostCreate(title="hello", body="world")
    assert p.title == "hello"
    assert p.body == "world"


def test_post_create_strips_surrounding_whitespace():
    p = PostCreate(title="  hi  ", body="  there  ")
    assert p.title == "hi"
    assert p.body == "there"


@pytest.mark.parametrize("field", ["title", "body"])
def test_post_create_rejects_empty_or_whitespace(field):
    payload = {"title": "t", "body": "b", field: "   "}
    with pytest.raises(ValidationError):
        PostCreate(**payload)


@pytest.mark.parametrize("missing", ["title", "body"])
def test_post_create_requires_both_fields(missing):
    payload = {"title": "t", "body": "b"}
    payload.pop(missing)
    with pytest.raises(ValidationError):
        PostCreate(**payload)


def test_post_create_rejects_owner_id():
    """owner_id is server-managed; clients sending it must be rejected."""
    with pytest.raises(ValidationError):
        PostCreate(title="t", body="b", owner_id=uuid.uuid4())


def test_post_create_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        PostCreate(title="t", body="b", evil=True)


# --- PostUpdate ----------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"title": "new"},
        {"body": "new"},
        {"title": "t", "body": "b"},
    ],
)
def test_post_update_accepts_partial_fields(payload):
    p = PostUpdate(**payload)
    assert p.title == payload.get("title")
    assert p.body == payload.get("body")


def test_post_update_strips_whitespace():
    p = PostUpdate(title="  hi  ")
    assert p.title == "hi"
    assert p.body is None


@pytest.mark.parametrize("payload", [{}, {"title": None, "body": None}])
def test_post_update_requires_at_least_one_field(payload):
    with pytest.raises(ValidationError):
        PostUpdate(**payload)


@pytest.mark.parametrize(
    "payload",
    [
        {"title": "   "},
        {"body": ""},
        {"title": "t", "body": "   "},
    ],
)
def test_post_update_rejects_whitespace_only(payload):
    with pytest.raises(ValidationError):
        PostUpdate(**payload)


def test_post_update_rejects_owner_id():
    with pytest.raises(ValidationError):
        PostUpdate(title="t", owner_id=uuid.uuid4())


def test_post_update_rejects_unknown_field():
    with pytest.raises(ValidationError):
        PostUpdate(title="t", evil=True)

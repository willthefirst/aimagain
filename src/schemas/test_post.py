import uuid

import pytest
from pydantic import ValidationError

from src.schemas.post import PostCreate, PostUpdate

# --- PostCreate ----------------------------------------------------------


def test_post_create_accepts_kind_title_and_body():
    p = PostCreate(kind="note", title="hello", body="world")
    assert p.kind == "note"
    assert p.title == "hello"
    assert p.body == "world"


def test_post_create_strips_surrounding_whitespace():
    p = PostCreate(kind="note", title="  hi  ", body="  there  ")
    assert p.title == "hi"
    assert p.body == "there"


def test_post_create_requires_kind():
    """`kind` is required on the wire — prep step before adding more kinds."""
    with pytest.raises(ValidationError):
        PostCreate(title="t", body="b")


def test_post_create_rejects_other_kinds():
    """Today only `'note'` is accepted; future PRs widen the Literal."""
    with pytest.raises(ValidationError):
        PostCreate(kind="not_a_kind", title="t", body="b")


@pytest.mark.parametrize("field", ["title", "body"])
def test_post_create_rejects_empty_or_whitespace(field):
    payload = {"kind": "note", "title": "t", "body": "b", field: "   "}
    with pytest.raises(ValidationError):
        PostCreate(**payload)


@pytest.mark.parametrize("missing", ["title", "body"])
def test_post_create_requires_both_fields(missing):
    payload = {"kind": "note", "title": "t", "body": "b"}
    payload.pop(missing)
    with pytest.raises(ValidationError):
        PostCreate(**payload)


def test_post_create_rejects_owner_id():
    """owner_id is server-managed; clients sending it must be rejected."""
    with pytest.raises(ValidationError):
        PostCreate(kind="note", title="t", body="b", owner_id=uuid.uuid4())


def test_post_create_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        PostCreate(kind="note", title="t", body="b", evil=True)


# --- PostUpdate ----------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "note", "title": "new"},
        {"kind": "note", "body": "new"},
        {"kind": "note", "title": "t", "body": "b"},
    ],
)
def test_post_update_accepts_partial_fields(payload):
    p = PostUpdate(**payload)
    assert p.kind == "note"
    assert p.title == payload.get("title")
    assert p.body == payload.get("body")


def test_post_update_strips_whitespace():
    p = PostUpdate(kind="note", title="  hi  ")
    assert p.title == "hi"
    assert p.body is None


def test_post_update_requires_kind():
    with pytest.raises(ValidationError):
        PostUpdate(title="hi")


def test_post_update_rejects_other_kinds():
    with pytest.raises(ValidationError):
        PostUpdate(kind="not_a_kind", title="t")


@pytest.mark.parametrize(
    "payload", [{"kind": "note"}, {"kind": "note", "title": None, "body": None}]
)
def test_post_update_requires_at_least_one_field(payload):
    with pytest.raises(ValidationError):
        PostUpdate(**payload)


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "note", "title": "   "},
        {"kind": "note", "body": ""},
        {"kind": "note", "title": "t", "body": "   "},
    ],
)
def test_post_update_rejects_whitespace_only(payload):
    with pytest.raises(ValidationError):
        PostUpdate(**payload)


def test_post_update_rejects_owner_id():
    with pytest.raises(ValidationError):
        PostUpdate(kind="note", title="t", owner_id=uuid.uuid4())


def test_post_update_rejects_unknown_field():
    with pytest.raises(ValidationError):
        PostUpdate(kind="note", title="t", evil=True)

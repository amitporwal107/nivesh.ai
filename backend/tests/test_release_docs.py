"""Unit tests for the Release Management store's pure logic.

DB-backed behaviour (create/update/revisions/uniqueness/admin-gating) is verified
against STAGING via curl — see test_reports/release-management_functionality.md.
These tests cover the deterministic, no-DB pieces so they always run in CI:
semver validation, enum guards, template shape, and the summary projection.
"""
import pytest

from services import release_docs_store as store


@pytest.mark.parametrize("v", ["4.2.0", "0.0.1", "10.20.30", "4.2.0-rc.1", "4.2.0+build.5"])
def test_semver_accepts_valid(v):
    assert store.SEMVER_RE.match(v)


@pytest.mark.parametrize("v", ["4.2", "v4.2.0", "4.2.0.1", "", "abc", "4.2.x"])
def test_semver_rejects_invalid(v):
    assert not store.SEMVER_RE.match(v)


def test_validate_ok():
    store._validate("release_notes", "4.2.0", "structured", "draft")  # must not raise


@pytest.mark.parametrize("args", [
    ("bad_type", "4.2.0", "structured", "draft"),
    ("release_notes", "4.2", "structured", "draft"),
    ("release_notes", "4.2.0", "bad_fmt", "draft"),
    ("release_notes", "4.2.0", "structured", "bad_status"),
])
def test_validate_raises(args):
    with pytest.raises(store.ValidationError):
        store._validate(*args)


def test_templates_shape():
    t = store.get_templates()
    types = {tpl["doc_type"] for tpl in t["templates"]}
    assert types == {"release_notes", "release_process"}
    for tpl in t["templates"]:
        assert tpl["sections"]
        assert all({"key", "title", "body"} <= set(s) for s in tpl["sections"])


def test_summary_excludes_content():
    doc = {
        "_id": "x", "doc_type": "release_notes", "release_version": "4.2.0",
        "title": "t", "status": "draft", "environment": None, "format": "structured",
        "content": {"secret": 1}, "current_revision": 1,
        "created_at": "t0", "created_by": "a", "updated_at": "t0", "updated_by": "a",
    }
    s = store._summary(doc)
    assert "content" not in s
    assert s["id"] == "x"
    assert s["current_revision"] == 1

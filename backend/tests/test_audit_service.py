"""Tests for AuditService pure helpers: secret redaction and result summarizing."""

from backend.services.audit_service import AuditService


def test_sanitize_redacts_sensitive_keys():
    args = {
        "user_id": "u1",
        "password": "hunter2",
        "new_password": "s3cret",
        "secret": "x",
        "token": "y",
        "api_key": "z",
    }

    out = AuditService._sanitize(args)

    assert out["user_id"] == "u1"  # non-sensitive preserved
    for key in ("password", "new_password", "secret", "token", "api_key"):
        assert out[key] == "***REDACTED***"


def test_sanitize_does_not_mutate_input():
    args = {"password": "hunter2"}

    AuditService._sanitize(args)

    assert args["password"] == "hunter2"  # original dict untouched


def test_sanitize_passes_through_when_no_secrets():
    args = {"user_id": "u1", "department": "IT"}

    assert AuditService._sanitize(args) == args


def test_summarize_picks_only_whitelisted_keys():
    result = {
        "id": "abc",
        "user_id": "u1",
        "success": True,
        "deleted": True,
        "temporary_password": "leak-me",  # not whitelisted -> excluded
        "note": "verbose",
    }

    summary = AuditService._summarize_result(result)

    assert summary == {"id": "abc", "user_id": "u1", "success": True, "deleted": True}
    assert "temporary_password" not in summary
    assert "note" not in summary


def test_summarize_empty_result():
    assert AuditService._summarize_result({}) == {}

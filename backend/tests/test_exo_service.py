"""Tests for the Exchange Online PowerShell sidecar client (D-019).

The credential and aiohttp session are injected as fakes, so nothing touches Azure
or the network. Two layers are covered:

- method dispatch — each public op forwards the right (operation, params) to ``_call``;
- ``_call`` transport — bearer header, request body, and the structured-failure paths
  (HTTP error, timeout, transport error, non-JSON, sidecar-reported failure). A failure
  is NEVER rewritten to success.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import aiohttp
import pytest

from backend.services.exo_service import ExoService


class _FakeResponse:
    def __init__(self, status=200, body=None, text="", raise_json=False):
        self.status = status
        self._body = body if body is not None else {"success": True, "result": {"ok": True}}
        self._text = text
        self._raise_json = raise_json

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def text(self):
        return self._text

    async def json(self, content_type=None):
        if self._raise_json:
            raise aiohttp.ContentTypeError(SimpleNamespace(real_url="x"), ())
        return self._body


class _FakeSession:
    """Captures the last post() call and returns a preset response (or raises)."""

    def __init__(self, response=None, raise_exc=None):
        self._response = response or _FakeResponse()
        self._raise_exc = raise_exc
        self.calls = []

    def post(self, url, json=None, headers=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._response


def _fake_credential(token="jwt-token"):
    cred = AsyncMock()
    cred.get_token.return_value = SimpleNamespace(token=token)
    return cred


def _make_service(session, credential=None):
    return ExoService(
        sidecar_url="https://sidecar.example.net/api/ManageExchange",
        audience="api://exo-sidecar",
        credential=credential or _fake_credential(),
        session=session,
    )


# ── _call transport ──────────────────────────────────────────────────


async def test_call_sends_bearer_and_payload_and_parses_success():
    session = _FakeSession(_FakeResponse(status=200, body={"success": True, "result": {"id": "m1"}}))
    svc = _make_service(session)

    result = await svc._call("create_shared_mailbox", {"mailbox_address": "team@contoso.com"})

    call = session.calls[0]
    assert call["url"] == "https://sidecar.example.net/api/ManageExchange"
    assert call["headers"]["Authorization"] == "Bearer jwt-token"
    assert call["json"] == {"operation": "create_shared_mailbox", "params": {"mailbox_address": "team@contoso.com"}}
    assert result["success"] is True
    assert result["result"] == {"id": "m1"}


async def test_call_uses_audience_scope():
    cred = _fake_credential()
    svc = _make_service(_FakeSession(), credential=cred)

    await svc._call("delete_shared_mailbox", {"mailbox_address": "team@contoso.com"})

    cred.get_token.assert_awaited_once_with("api://exo-sidecar/.default")


async def test_call_http_error_is_structured_failure():
    session = _FakeSession(_FakeResponse(status=500, text="boom"))
    svc = _make_service(session)

    result = await svc._call("delete_shared_mailbox", {"mailbox_address": "team@contoso.com"})

    assert result["success"] is False
    assert "HTTP 500" in result["reason"]


async def test_call_timeout_is_structured_failure():
    session = _FakeSession(raise_exc=TimeoutError())
    svc = _make_service(session)

    result = await svc._call("delete_shared_mailbox", {"mailbox_address": "team@contoso.com"})

    assert result["success"] is False
    assert "timed out" in result["reason"]


async def test_call_client_error_is_structured_failure():
    session = _FakeSession(raise_exc=aiohttp.ClientConnectionError("refused"))
    svc = _make_service(session)

    result = await svc._call("delete_shared_mailbox", {"mailbox_address": "team@contoso.com"})

    assert result["success"] is False
    assert "unreachable" in result["reason"]


async def test_call_non_json_is_structured_failure():
    session = _FakeSession(_FakeResponse(status=200, text="<html>", raise_json=True))
    svc = _make_service(session)

    result = await svc._call("delete_shared_mailbox", {"mailbox_address": "team@contoso.com"})

    assert result["success"] is False
    assert "non-JSON" in result["reason"]


async def test_call_sidecar_failure_not_rewritten_to_success():
    # The sidecar's own success flag is authoritative — a 2xx with success:false stays a failure.
    session = _FakeSession(_FakeResponse(status=200, body={"success": False, "error": "mailbox already exists"}))
    svc = _make_service(session)

    result = await svc._call("create_shared_mailbox", {"mailbox_address": "team@contoso.com"})

    assert result["success"] is False
    assert result["reason"] == "mailbox already exists"


async def test_call_token_failure_skips_http():
    cred = AsyncMock()
    cred.get_token.side_effect = RuntimeError("no managed identity")
    session = _FakeSession()
    svc = _make_service(session, credential=cred)

    result = await svc._call("delete_shared_mailbox", {"mailbox_address": "team@contoso.com"})

    assert result["success"] is False
    assert "authenticate" in result["reason"]
    assert session.calls == []  # no HTTP attempt without a token


# ── public method dispatch ────────────────────────────────────────────


@pytest.mark.parametrize(
    ("method", "args", "expected_op", "expected_params"),
    [
        (
            "create_shared_mailbox",
            ("team@x.com", "Team"),
            "create_shared_mailbox",
            {"mailbox_address": "team@x.com", "display_name": "Team"},
        ),
        ("delete_shared_mailbox", ("team@x.com",), "delete_shared_mailbox", {"mailbox_address": "team@x.com"}),
        (
            "add_shared_mailbox_member",
            ("team@x.com", ["a@x.com"]),
            "add_shared_mailbox_member",
            {"mailbox_address": "team@x.com", "members": ["a@x.com"]},
        ),
        (
            "remove_shared_mailbox_member",
            ("team@x.com", ["a@x.com"]),
            "remove_shared_mailbox_member",
            {"mailbox_address": "team@x.com", "members": ["a@x.com"]},
        ),
        (
            "create_distribution_group",
            ("all@x.com", "All"),
            "create_distribution_group",
            {"group_email": "all@x.com", "display_name": "All"},
        ),
        ("delete_distribution_group", ("all@x.com",), "delete_distribution_group", {"group_email": "all@x.com"}),
        (
            "add_distribution_group_member",
            ("all@x.com", ["a@x.com"]),
            "add_distribution_group_member",
            {"group_email": "all@x.com", "members": ["a@x.com"]},
        ),
        (
            "remove_distribution_group_member",
            ("all@x.com", ["a@x.com"]),
            "remove_distribution_group_member",
            {"group_email": "all@x.com", "members": ["a@x.com"]},
        ),
    ],
)
async def test_methods_forward_to_call(method, args, expected_op, expected_params):
    svc = _make_service(_FakeSession())
    svc._call = AsyncMock(return_value={"success": True})

    await getattr(svc, method)(*args)

    svc._call.assert_awaited_once_with(expected_op, expected_params)


async def test_create_omits_blank_display_name():
    svc = _make_service(_FakeSession())
    svc._call = AsyncMock(return_value={"success": True})

    await svc.create_shared_mailbox("team@x.com")

    svc._call.assert_awaited_once_with("create_shared_mailbox", {"mailbox_address": "team@x.com"})


# ── close() ───────────────────────────────────────────────────────────


async def test_close_releases_owned_resources():
    cred = _fake_credential()
    svc = ExoService("https://s/api", "api://exo", credential=cred)
    # An injected credential is not owned, so close() must not touch it.
    await svc.close()
    cred.close.assert_not_awaited()


async def test_close_closes_owned_session_and_credential():
    cred = _fake_credential()
    svc = ExoService("https://s/api", "api://exo", credential=cred)
    owned_session = AsyncMock()
    svc._session = owned_session
    svc._owns_session = True

    await svc.close()

    owned_session.close.assert_awaited_once()

"""Tests for SessionService (durable conversation state).

These exercise the in-memory fallback path (no Cosmos configured), which shares the
exact API used against Cosmos, plus the owner-isolation guarantee and the
renderable-history projection used by the web UI.
"""

from backend.services.session_service import SessionService


async def test_get_unknown_returns_none():
    svc = SessionService()
    assert await svc.get("nope", owner_id="owner-a") is None


async def test_get_or_create_then_get_roundtrips():
    svc = SessionService()
    created = await svc.get_or_create("s1", owner_id="owner-a", user_name="Ann", user_email="ann@x")
    assert created["id"] == "s1"
    assert created["owner_id"] == "owner-a"
    assert created["session_id"] == "s1"
    assert created["history"] == []

    # A second call returns the SAME session, not a fresh empty one.
    again = await svc.get_or_create("s1", owner_id="owner-a")
    assert again["user_name"] == "Ann"

    fetched = await svc.get("s1", owner_id="owner-a")
    assert fetched is not None
    assert fetched["session_id"] == "s1"


async def test_save_persists_history():
    svc = SessionService()
    await svc.get_or_create("s1", owner_id="owner-a")
    history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    await svc.save("s1", owner_id="owner-a", history=history)

    fetched = await svc.get("s1", owner_id="owner-a")
    assert fetched is not None
    assert fetched["history"] == history
    assert fetched["updated_at"] >= fetched["created_at"]


async def test_save_creates_session_when_absent():
    svc = SessionService()
    await svc.save("s2", owner_id="owner-a", history=[{"role": "user", "content": "x"}])
    fetched = await svc.get("s2", owner_id="owner-a")
    assert fetched is not None
    assert len(fetched["history"]) == 1


async def test_owner_isolation():
    svc = SessionService()
    await svc.save("shared-id", owner_id="owner-a", history=[{"role": "user", "content": "secret"}])

    # Same id, different owner → different partition → not visible.
    assert await svc.get("shared-id", owner_id="owner-b") is None

    # get_or_create for owner-b yields a fresh empty session (no cross-user leak).
    other = await svc.get_or_create("shared-id", owner_id="owner-b")
    assert other["history"] == []


def test_renderable_messages_projection():
    history = [
        {"role": "system", "content": "you are..."},
        {"role": "user", "content": "create a user"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]},  # tool-call only
        {"role": "tool", "content": "{...}"},
        {"role": "assistant", "content": "Done — created the user."},
        {"role": "user", "content": "   "},  # whitespace only → skipped
    ]
    assert SessionService.renderable_messages(history) == [
        {"role": "user", "text": "create a user"},
        {"role": "bot", "text": "Done — created the user."},
    ]

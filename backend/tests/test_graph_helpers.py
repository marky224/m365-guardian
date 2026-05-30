"""Tests for GraphService pure helpers (no live Graph)."""

import string

from azure.identity import DefaultAzureCredential

from backend.services.graph_service import GraphService

SPECIALS = set("!@#$%^&*")
ALLOWED = set(string.ascii_letters + string.digits) | SPECIALS


def test_graph_service_uses_managed_identity_credential():
    # App-only Graph auth goes through DefaultAzureCredential (managed identity in
    # Azure, env client secret / az login locally) — no static ClientSecretCredential.
    svc = GraphService()
    assert isinstance(svc._credential, DefaultAzureCredential)


def test_password_default_length():
    pw = GraphService._generate_secure_password()
    assert len(pw) == 16


def test_password_custom_length():
    pw = GraphService._generate_secure_password(24)
    assert len(pw) == 24


def test_password_meets_complexity():
    # Run many times — generation is random, so assert the guarantee holds every time.
    for _ in range(200):
        pw = GraphService._generate_secure_password()
        assert any(c.islower() for c in pw), pw
        assert any(c.isupper() for c in pw), pw
        assert any(c.isdigit() for c in pw), pw
        assert any(c in SPECIALS for c in pw), pw


def test_password_uses_only_allowed_characters():
    for _ in range(50):
        pw = GraphService._generate_secure_password()
        assert set(pw) <= ALLOWED, set(pw) - ALLOWED


def test_passwords_are_unique():
    pws = {GraphService._generate_secure_password() for _ in range(100)}
    # Astronomically unlikely to collide; a dup signals a non-random generator.
    assert len(pws) == 100

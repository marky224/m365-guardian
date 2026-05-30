"""Tests for Cosmos credential selection (account key vs managed identity).

CosmosClient and DefaultAzureCredential are faked, so nothing connects to Azure.
"""

import backend.services.cosmos as cosmos_mod


def _patch(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        cosmos_mod,
        "CosmosClient",
        lambda endpoint, credential: captured.update(endpoint=endpoint, credential=credential) or "client",
    )
    sentinel = object()
    monkeypatch.setattr(cosmos_mod, "DefaultAzureCredential", lambda: sentinel)
    return captured, sentinel


def test_uses_account_key_when_present(monkeypatch):
    captured, sentinel = _patch(monkeypatch)
    cosmos_mod.make_cosmos_client("https://acct/", "the-key")
    assert captured["endpoint"] == "https://acct/"
    assert captured["credential"] == "the-key"  # key used; managed identity not invoked


def test_uses_managed_identity_without_key(monkeypatch):
    captured, sentinel = _patch(monkeypatch)
    cosmos_mod.make_cosmos_client("https://acct/", "")
    assert captured["credential"] is sentinel  # DefaultAzureCredential used

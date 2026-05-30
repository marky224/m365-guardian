"""Tests for MSAL confidential-client credential selection (D-018).

The web sign-in uses a managed-identity assertion under Workload Identity Federation
(AZURE_USE_WIF) and the AAD client secret otherwise. These tests exercise the selection
and the lazy assertion callable with ManagedIdentityCredential faked out — nothing
touches Azure. Follows the monkeypatch.setattr(app_module, ...) style used elsewhere.
"""

from types import SimpleNamespace

import backend.app as app_module


def test_secret_credential_when_wif_off(monkeypatch):
    monkeypatch.setattr(app_module.config.azure_ad, "use_wif", False)
    monkeypatch.setattr(app_module.config.azure_ad, "client_secret", "the-secret")

    assert app_module._build_msal_client_credential() == "the-secret"


def test_wif_credential_uses_managed_identity_assertion(monkeypatch):
    created = []

    class _FakeMICredential:
        def __init__(self, *, client_id=None):
            self.client_id = client_id
            self.requested_scopes = None
            self.closed = False
            created.append(self)

        def get_token(self, *scopes):
            self.requested_scopes = scopes
            return SimpleNamespace(token="fake-jwt")

        def close(self):
            self.closed = True

    monkeypatch.setattr(app_module, "ManagedIdentityCredential", _FakeMICredential)
    monkeypatch.setattr(app_module.config.azure_ad, "use_wif", True)
    monkeypatch.setattr(app_module.config.azure_ad, "wif_managed_identity_client_id", "mi-client-id")

    cred = app_module._build_msal_client_credential()
    assert isinstance(cred, dict)
    assertion_callable = cred["client_assertion"]
    assert callable(assertion_callable)
    # MSAL invokes the assertion lazily, so building the credential makes no MI call.
    assert created == []

    token = assertion_callable()

    assert token == "fake-jwt"
    assert len(created) == 1  # exactly one credential built per invocation
    mi = created[0]
    assert mi.client_id == "mi-client-id"  # the user-assigned MI is targeted explicitly
    assert mi.requested_scopes == (app_module.TOKEN_EXCHANGE_SCOPE,)
    assert mi.closed is True  # transport released after use

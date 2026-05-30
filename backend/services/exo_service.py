"""
M365 Guardian — Exchange Online PowerShell sidecar client.

Shared mailboxes and distribution groups are Exchange-admin operations that
Microsoft Graph does not expose (shared mailboxes are unsupported; distribution
groups are read-only). They require Exchange Online PowerShell. This client calls
a small PowerShell Azure Function ("the sidecar") over an authenticated internal
HTTP endpoint; the sidecar runs ``Connect-ExchangeOnline`` and a narrow set of
audited cmdlets.

Authentication is secretless, matching the rest of the app (Graph D-011, Cosmos
D-017, web sign-in D-018): the app's managed identity mints a bearer token for the
sidecar's app-registration audience (its Easy Auth validates it). We use
``ManagedIdentityCredential`` explicitly — NOT ``DefaultAzureCredential`` — because
DAC would read the app-registration's ``AZURE_CLIENT_ID`` as a user-assigned MI
client id and request the wrong identity (same trap as D-018).

The client is built only when ``EXO_SIDECAR_URL`` is configured; otherwise the
executor keeps returning the honest ``not_implemented`` result. Every method returns
a structured dict and never raises a fabricated success — a transport error, a
non-2xx response, or a sidecar-reported failure all surface as ``success: False``.
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
from azure.identity.aio import ManagedIdentityCredential

logger = logging.getLogger(__name__)

# Connect-ExchangeOnline + a cmdlet can be slow, and the Function may cold-start.
_DEFAULT_TIMEOUT_SECONDS = 60


class ExoService:
    """Async client for the Exchange Online PowerShell sidecar."""

    def __init__(
        self,
        sidecar_url: str,
        audience: str,
        managed_identity_client_id: str = "",
        *,
        timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
        credential: Any | None = None,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        # The full sidecar endpoint to POST to (e.g. https://<fn>.azurewebsites.net/api/ManageExchange).
        self._url = sidecar_url.rstrip("/")
        # MI token scope for the sidecar's Easy Auth audience.
        self._scope = f"{audience}/.default"
        # ManagedIdentityCredential, not DefaultAzureCredential (see module docstring / D-018).
        if credential is not None:
            self._credential = credential
            self._owns_credential = False
        else:
            # client_id=None selects the system-assigned MI; a non-empty id selects a UAMI.
            self._credential = ManagedIdentityCredential(client_id=managed_identity_client_id or None)
            self._owns_credential = True
        # Session is created lazily inside the running loop unless one is injected (tests).
        self._session = session
        self._owns_session = session is None
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self._session

    @staticmethod
    def _failure(operation: str, reason: str, detail: Any = None) -> dict:
        out: dict[str, Any] = {"success": False, "operation": operation, "reason": reason}
        if detail is not None:
            out["detail"] = detail
        return out

    async def _call(self, operation: str, params: dict) -> dict:
        """POST one operation to the sidecar with a fresh MI bearer token.

        Returns the sidecar's JSON on success; otherwise a structured failure dict.
        Never raises and never invents success — the sidecar's own ``success`` flag
        is the source of truth.
        """
        try:
            token = await self._credential.get_token(self._scope)
        except Exception as e:  # noqa: BLE001 — auth failures must surface as structured results
            logger.error("EXO sidecar token acquisition failed for %s: %s", operation, type(e).__name__)
            return self._failure(operation, f"Could not authenticate to the EXO sidecar ({type(e).__name__}).")

        headers = {"Authorization": f"Bearer {token.token}", "Content-Type": "application/json"}
        body = {"operation": operation, "params": params}
        try:
            session = await self._ensure_session()
            async with session.post(self._url, json=body, headers=headers) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    logger.error("EXO sidecar returned HTTP %s for %s", resp.status, operation)
                    return self._failure(operation, f"EXO sidecar returned HTTP {resp.status}.", detail=text[:500])
                try:
                    data = await resp.json(content_type=None)
                except (aiohttp.ContentTypeError, ValueError):
                    return self._failure(operation, "EXO sidecar returned a non-JSON response.", detail=text[:500])
        except TimeoutError:
            return self._failure(operation, "EXO sidecar request timed out.")
        except aiohttp.ClientError as e:
            return self._failure(operation, f"EXO sidecar is unreachable ({type(e).__name__}).")

        # Trust the sidecar's own success flag; never rewrite a failure to success.
        if not isinstance(data, dict) or data.get("success") is not True:
            reason = (data or {}).get("error") if isinstance(data, dict) else None
            return self._failure(operation, reason or "The EXO operation did not report success.", detail=data)
        return {"success": True, "operation": operation, "result": data.get("result", data)}

    # ── Shared mailbox operations ────────────────────────────────────

    async def create_shared_mailbox(self, mailbox_address: str, display_name: str | None = None) -> dict:
        params: dict[str, Any] = {"mailbox_address": mailbox_address}
        if display_name:
            params["display_name"] = display_name
        return await self._call("create_shared_mailbox", params)

    async def delete_shared_mailbox(self, mailbox_address: str) -> dict:
        return await self._call("delete_shared_mailbox", {"mailbox_address": mailbox_address})

    async def add_shared_mailbox_member(self, mailbox_address: str, members: list[str]) -> dict:
        return await self._call("add_shared_mailbox_member", {"mailbox_address": mailbox_address, "members": members})

    async def remove_shared_mailbox_member(self, mailbox_address: str, members: list[str]) -> dict:
        return await self._call(
            "remove_shared_mailbox_member", {"mailbox_address": mailbox_address, "members": members}
        )

    # ── Distribution group operations ────────────────────────────────

    async def create_distribution_group(self, group_email: str, display_name: str | None = None) -> dict:
        params: dict[str, Any] = {"group_email": group_email}
        if display_name:
            params["display_name"] = display_name
        return await self._call("create_distribution_group", params)

    async def delete_distribution_group(self, group_email: str) -> dict:
        return await self._call("delete_distribution_group", {"group_email": group_email})

    async def add_distribution_group_member(self, group_email: str, members: list[str]) -> dict:
        return await self._call("add_distribution_group_member", {"group_email": group_email, "members": members})

    async def remove_distribution_group_member(self, group_email: str, members: list[str]) -> dict:
        return await self._call("remove_distribution_group_member", {"group_email": group_email, "members": members})

    async def close(self) -> None:
        """Release the aiohttp session and credential transport. Safe on shutdown."""
        if self._owns_session and self._session is not None:
            await self._session.close()
        if self._owns_credential:
            await self._credential.close()

"""
M365 Guardian — Cosmos DB client construction.

One place to decide how the audit and session services authenticate to Cosmos:
- **Key** when `COSMOS_KEY` is set — local dev / the Cosmos emulator.
- **Managed identity** (`DefaultAzureCredential`) when no key is set — production, where the
  account key is replaced by Cosmos data-plane RBAC granted to the app's identity (D-017).

Callers still gate on the endpoint being present; this only chooses the credential.
"""

import logging

from azure.cosmos import CosmosClient
from azure.identity import DefaultAzureCredential

logger = logging.getLogger(__name__)


def make_cosmos_client(endpoint: str, key: str) -> CosmosClient:
    """Build a CosmosClient using the account key if provided, else managed identity."""
    if key:
        return CosmosClient(endpoint, credential=key)
    logger.info("COSMOS_KEY not set — authenticating to Cosmos via managed identity (AAD RBAC).")
    return CosmosClient(endpoint, credential=DefaultAzureCredential())

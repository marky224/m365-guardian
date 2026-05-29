"""Pure-logic tests for the weekly report severity thresholds.

GraphService is mocked, so these exercise only the threshold/aggregation logic
in ReportService — no live Graph calls.
"""

from unittest.mock import AsyncMock

import pytest

from backend.services.report_service import (
    SEVERITY_CRITICAL,
    SEVERITY_OK,
    SEVERITY_WARNING,
    ReportService,
)


def _svc():
    graph = AsyncMock()
    return ReportService(graph), graph


def _users(n):
    return [{"id": f"u{i}", "displayName": f"User {i}", "userPrincipalName": f"u{i}@x"} for i in range(n)]


# ── Suspicious sign-ins: 0 OK, 1-3 WARNING, >3 CRITICAL ──────────────


@pytest.mark.parametrize(
    ("count", "expected"),
    [(0, SEVERITY_OK), (1, SEVERITY_WARNING), (3, SEVERITY_WARNING), (4, SEVERITY_CRITICAL)],
)
async def test_suspicious_sign_ins_thresholds(count, expected):
    svc, graph = _svc()
    graph.get_risky_sign_ins.return_value = _users(count)

    section = await svc._check_suspicious_sign_ins(7, 90)

    assert section["severity"] == expected
    assert section["finding_count"] == count


# ── MFA compliance: 0 OK, 1-5 WARNING, >5 CRITICAL ──────────────────


@pytest.mark.parametrize(
    ("count", "expected"),
    [(0, SEVERITY_OK), (5, SEVERITY_WARNING), (6, SEVERITY_CRITICAL)],
)
async def test_mfa_compliance_thresholds(count, expected):
    svc, graph = _svc()
    graph.get_users_without_mfa.return_value = _users(count)

    section = await svc._check_mfa_compliance(7, 90)

    assert section["severity"] == expected


# ── Dormant accounts: 0 OK, 1-10 WARNING, >10 CRITICAL ──────────────


@pytest.mark.parametrize(
    ("count", "expected"),
    [(0, SEVERITY_OK), (10, SEVERITY_WARNING), (11, SEVERITY_CRITICAL)],
)
async def test_dormant_accounts_thresholds(count, expected):
    svc, graph = _svc()
    graph.get_dormant_accounts.return_value = _users(count)

    section = await svc._check_dormant_accounts(7, 90)

    assert section["severity"] == expected


# ── Privileged access: <=2 OK, 3-5 WARNING, >5 CRITICAL ─────────────


@pytest.mark.parametrize(
    ("count", "expected"),
    [(0, SEVERITY_OK), (2, SEVERITY_OK), (3, SEVERITY_WARNING), (5, SEVERITY_WARNING), (6, SEVERITY_CRITICAL)],
)
async def test_privileged_access_thresholds(count, expected):
    svc, graph = _svc()
    graph.get_privileged_role_holders.return_value = [
        {"principalDisplayName": f"Admin {i}", "roleName": "Global Administrator"} for i in range(count)
    ]

    section = await svc._check_privileged_access(7, 90)

    assert section["severity"] == expected
    assert section["finding_count"] == count


async def test_privileged_access_ignores_non_privileged_roles():
    svc, graph = _svc()
    # Roles outside the privileged set must not count toward the finding total.
    graph.get_privileged_role_holders.return_value = [
        {"principalDisplayName": "Reader", "roleName": "Directory Readers"} for _ in range(10)
    ]

    section = await svc._check_privileged_access(7, 90)

    assert section["finding_count"] == 0
    assert section["severity"] == SEVERITY_OK


# ── Guest users: >20 WARNING else OK ─────────────────────────────────


@pytest.mark.parametrize(
    ("count", "expected"),
    [(0, SEVERITY_OK), (20, SEVERITY_OK), (21, SEVERITY_WARNING)],
)
async def test_guest_user_thresholds(count, expected):
    svc, graph = _svc()
    graph.get_guest_users.return_value = _users(count)

    section = await svc._check_guest_users(7, 90)

    assert section["severity"] == expected


# ── License optimization: any SKU with >5 unused units -> WARNING ────


async def test_license_optimization_flags_wasted_skus():
    svc, graph = _svc()
    graph.list_licenses.return_value = [
        {"skuPartNumber": "E3", "availableUnits": 6},
        {"skuPartNumber": "E5", "availableUnits": 2},
    ]

    section = await svc._check_license_optimization(7, 90)

    assert section["severity"] == SEVERITY_WARNING
    assert section["finding_count"] == 1


async def test_license_optimization_healthy():
    svc, graph = _svc()
    graph.list_licenses.return_value = [{"skuPartNumber": "E3", "availableUnits": 1}]

    section = await svc._check_license_optimization(7, 90)

    assert section["severity"] == SEVERITY_OK


# ── Overall aggregation via generate() ───────────────────────────────


async def test_generate_overall_severity_is_critical_when_any_critical():
    svc, graph = _svc()
    graph.get_users_without_mfa.return_value = _users(6)  # critical
    # Everything else benign / empty
    graph.get_risky_sign_ins.return_value = []
    graph.get_dormant_accounts.return_value = []
    graph.get_privileged_role_holders.return_value = []
    graph.get_guest_users.return_value = []
    graph.list_licenses.return_value = []

    report = await svc.generate()

    assert report["overall_severity"] == SEVERITY_CRITICAL
    assert report["critical_count"] >= 1
    assert len(report["sections"]) == 10  # all 10 checks ran


async def test_generate_handles_check_failure_gracefully():
    svc, graph = _svc()
    # One check raises; generate() must not blow up and should degrade that section.
    graph.get_risky_sign_ins.side_effect = RuntimeError("Graph down")
    graph.get_users_without_mfa.return_value = []
    graph.get_dormant_accounts.return_value = []
    graph.get_privileged_role_holders.return_value = []
    graph.get_guest_users.return_value = []
    graph.list_licenses.return_value = []

    report = await svc.generate()

    assert len(report["sections"]) == 10
    failed = next(s for s in report["sections"] if s["check"] == "suspicious_sign_ins")
    assert "failed" in failed["summary"].lower()

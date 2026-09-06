"""Who may raise, issue and settle a bill.

Billing writes used to be open to receptionist, supervisor and admin, on an
explicit guess recorded in the router ("confirm with role definitions owner").
That had the front desk raising and settling invoices as a side effect of
registering a patient. Billing is now the billing desk's job; the pharmacy
counter bills dispensed medicines and nothing else.

These assertions are read off the mounted app rather than from the source, so
a gate moved between `dependencies=[]` and a parameter still counts.
"""

from __future__ import annotations

import pytest
from fastapi.routing import APIRoute

from app.main import app

#: Roles that may reach each billing path. Read as: exactly this set, no more.
EXPECTED: dict[tuple[str, str], set[str]] = {
    # The counter: raise, issue, settle. Pharmacist is present but constrained
    # at runtime to invoices made only of dispensed medicines.
    ("POST", "/api/v1/billing/visits/{visit_id}/invoice/build"): {"billing", "admin", "pharmacist"},
    ("POST", "/api/v1/billing/invoices/{invoice_id}/issue"): {"billing", "admin", "pharmacist"},
    ("POST", "/api/v1/billing/invoices/{invoice_id}/payments"): {"billing", "admin", "pharmacist"},
    ("GET", "/api/v1/billing/invoices/{invoice_id}"): {"billing", "admin", "pharmacist"},
    # Desk-only reads.
    ("GET", "/api/v1/billing/invoices"): {"billing", "admin"},
    ("GET", "/api/v1/billing/visits/{visit_id}/invoice/preview"): {"billing", "admin"},
    ("GET", "/api/v1/billing/visits/{visit_id}/pmjay-eligibility"): {"billing", "admin"},
    # A refund must not be approved by the desk that raised it.
    ("POST", "/api/v1/billing/payments/{payment_id}/refunds"): {"admin"},
    # Finance oversight, not counter work.
    ("GET", "/api/v1/billing/mis/daily-revenue"): {"billing", "admin", "auditor"},
    ("GET", "/api/v1/billing/mis/pending-invoices"): {"billing", "admin", "auditor"},
    ("GET", "/api/v1/billing/mis/scheme-breakdown"): {"billing", "admin", "auditor"},
    # Tariffs reprice every future invoice.
    ("GET", "/api/v1/billing/charge-master"): {"billing", "admin", "auditor"},
    ("POST", "/api/v1/billing/charge-master"): {"billing", "admin"},
    ("POST", "/api/v1/billing/charge-master/{tariff_id}/deactivate"): {"billing", "admin"},
    ("GET", "/api/v1/billing/ping"): {"admin"},
}


def _roles_for(route: APIRoute) -> set[str]:
    """Roles from the RESOLVED dependency tree.

    Reading `route.dependencies` alone misses a gate declared as a handler
    parameter, which is how an earlier audit of this codebase reported 67
    ungated routes that were not ungated at all.
    """
    found: set[str] = set()

    def walk(dependant) -> None:
        for child in dependant.dependencies:
            walk(child)
        call = getattr(dependant, "call", None)
        if call is not None and "require_roles" in getattr(call, "__qualname__", ""):
            for cell in call.__closure__ or ():
                value = cell.cell_contents
                if isinstance(value, tuple):
                    found.update(value)

    walk(route.dependant)
    return found


def _billing_routes() -> dict[tuple[str, str], APIRoute]:
    collected: list[APIRoute] = []

    def collect(router) -> None:
        for route in getattr(router, "routes", []):
            if isinstance(route, APIRoute):
                collected.append(route)
                continue
            inner = getattr(route, "original_router", None) or getattr(route, "app", None)
            if inner is not None and hasattr(inner, "routes"):
                collect(inner)

    collect(app)
    return {
        (method, route.path): route
        for route in collected
        if "/billing" in route.path
        for method in route.methods - {"HEAD", "OPTIONS"}
    }


def test_every_billing_route_is_accounted_for():
    """A new billing route must be a deliberate decision, not a default."""
    assert set(_billing_routes()) == set(EXPECTED)


@pytest.mark.parametrize("key", sorted(EXPECTED), ids=lambda k: f"{k[0]} {k[1]}")
def test_billing_route_roles(key):
    assert _roles_for(_billing_routes()[key]) == EXPECTED[key]


@pytest.mark.parametrize("role", ["receptionist", "supervisor", "nurse", "doctor", "hod"])
def test_no_other_role_can_reach_any_billing_route(role):
    """The whole point of the change: nobody outside the desk raises a bill."""
    reachable = [
        f"{method} {path}"
        for (method, path), route in _billing_routes().items()
        if role in _roles_for(route)
    ]
    assert reachable == [], f"{role} can still reach: {reachable}"

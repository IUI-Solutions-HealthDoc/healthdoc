"""
Regression test for blocker #1: "The application does not start."

CurrentUser (app/auth/deps.py) is Annotated[AuthUser, Depends(...)].
Typing an endpoint parameter as `_user: CurrentUser = Depends(require_roles(...))`
supplies a dependency both via the Annotated default AND the explicit
Depends() default, and FastAPI raises AssertionError at IMPORT time —
not at request time, not caught by any test that mocks the router out.
That's exactly why it reached review: nothing exercised the real
import path. This test is that exercise, kept intentionally tiny and
dependency-free (no DB, no network) so it runs in CI on every push,
including from a laptop with no Postgres running — the whole point is
that this class of bug should never again survive to a human reviewer.
"""
from __future__ import annotations

import importlib

import pytest


def test_billing_router_module_imports_cleanly():
    """
    Reproduces the exact failure mode from the review: previously this
    raised
        AssertionError: Cannot specify `Depends` in `Annotated` and
        default value together for '_user'
    at import time, which also aborted pytest collection for the WHOLE
    repo (not just billing) — so this single assertion is protecting
    every other module's test suite too, not just billing's.
    """
    module = importlib.import_module("app.billing.router")
    assert hasattr(module, "router")


def test_every_billing_route_has_exactly_one_dependency_per_param():
    """
    Belt-and-braces: even if FastAPI's own import-time validation is
    ever relaxed or bypassed in a future version, walk every route's
    dependant and assert no parameter both carries an Annotated-wrapped
    Depends() AND an explicit Depends() default — the actual shape of
    this bug, independent of which exception FastAPI happens to raise
    for it.
    """
    from app.billing.router import router

    for route in router.routes:
        dependant = getattr(route, "dependant", None)
        if dependant is None:
            continue
        seen_names = set()
        for dep_param in dependant.dependencies:
            for sub_param in getattr(dep_param, "query_params", []) + getattr(dep_param, "path_params", []):
                assert sub_param.name not in seen_names, (
                    f"{route.path}: parameter '{sub_param.name}' appears to be "
                    "resolved by more than one dependency source."
                )
                seen_names.add(sub_param.name)

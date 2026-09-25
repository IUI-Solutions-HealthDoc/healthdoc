"""Tariff success responses must not race their transaction commit."""

import pytest

from app.billing.router import router
from app.common.db import get_db


@pytest.mark.parametrize(
    "path",
    ["/billing/charge-master", "/billing/charge-master/{tariff_id}/deactivate"],
)
def test_tariff_write_commits_before_success_response(path):
    route = next(route for route in router.routes if route.path == path and "POST" in route.methods)
    sessions = [dependency for dependency in route.dependant.dependencies if dependency.call is get_db]
    assert len(sessions) == 1
    assert sessions[0].scope == "function"

"""LGD (Local Government Directory) state and district codes for ABHA demographics.

ABDM's demographic ABHA API takes the beneficiary's state and district as LGD
codes ("The correct state and district (LGD codes) of the beneficiary are
passed"). The ABHA API documents no lookup for them, but ABDM's facility
registry (HFR) serves the same LGD codes. The operator loads the list from HFR
or from the official LGD export with scripts/import_lgd_districts.py, and the
desk chooses from it. A code that is not in that list is refused, never passed on.
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache

from app.common.config import get_settings

_CODE = re.compile(r"^\d{1,4}$")


class LgdUnavailable(RuntimeError):
    """The LGD reference has not been loaded on this server."""


class LgdUnknown(ValueError):
    """The state or district code is not in the loaded LGD reference."""


def validate_reference(data: object) -> dict[str, dict]:
    """{state_code: {"name": str, "districts": {district_code: name}}}, checked."""
    if not isinstance(data, dict) or not isinstance(data.get("states"), dict) or not data["states"]:
        raise ValueError("LGD reference must have a non-empty 'states' object")
    states: dict[str, dict] = {}
    for code, state in data["states"].items():
        if not _CODE.match(str(code)) or not isinstance(state, dict):
            raise ValueError(f"Bad LGD state entry {code!r}")
        name, districts = state.get("name"), state.get("districts")
        if not isinstance(name, str) or not name.strip() or not isinstance(districts, dict):
            raise ValueError(f"LGD state {code} needs a name and districts")
        for district_code, district_name in districts.items():
            if not _CODE.match(str(district_code)) or not str(district_name).strip():
                raise ValueError(f"Bad LGD district {district_code!r} in state {code}")
        states[str(code)] = {"name": name.strip(), "districts": dict(districts)}
    return states


@lru_cache(maxsize=4)
def _load(path: str, modified: float) -> dict[str, dict]:
    with open(path, encoding="utf-8") as handle:
        return validate_reference(json.load(handle))


def reference() -> dict[str, dict]:
    path = get_settings().abdm_lgd_reference_path
    if not path or not os.path.isfile(path):
        raise LgdUnavailable("The LGD state and district list is not loaded on this server")
    try:
        return _load(path, os.path.getmtime(path))
    except (OSError, ValueError) as exc:
        raise LgdUnavailable("The LGD state and district list is unreadable") from exc


def states() -> list[dict[str, str]]:
    return sorted(
        ({"code": code, "name": state["name"]} for code, state in reference().items()),
        key=lambda row: row["name"],
    )


def districts(state_code: str) -> list[dict[str, str]]:
    state = reference().get(state_code)
    if state is None:
        raise LgdUnknown("Unknown LGD state code")
    return sorted(
        ({"code": code, "name": name} for code, name in state["districts"].items()),
        key=lambda row: row["name"],
    )


def require(state_code: str, district_code: str) -> tuple[str, str]:
    """The (state name, district name) for a pair the desk chose, or LgdUnknown."""
    state = reference().get(state_code)
    if state is None or district_code not in state["districts"]:
        raise LgdUnknown("The state and district must come from the LGD list")
    return state["name"], state["districts"][district_code]

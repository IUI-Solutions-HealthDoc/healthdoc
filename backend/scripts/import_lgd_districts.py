"""Turn the official LGD district list into the reference ABHA demographics uses.

Usage:
    python -m scripts.import_lgd_districts <lgd-districts.csv> <out.json>
    python -m scripts.import_lgd_districts --from-hfr <out.json>

Either download the CSV from the Local Government Directory (lgdirectory.gov.in,
Download Directory > District), or read the same LGD codes from ABDM's Health
Facility Registry with this server's ABDM credentials (--from-hfr). The CSV's
column titles have changed over time, so each column is found by any of the
known titles below; an export with none of them stops here with the titles it
does have, rather than guessing a column. Point ABDM_LGD_REFERENCE_PATH at the
written file.
"""

from __future__ import annotations

import asyncio
import csv
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.integrations.abdm.identity.lgd import validate_reference

COLUMNS = {
    "state_code": ("state code", "state lgd code", "state_code", "statecode"),
    "state_name": ("state name (in english)", "state name", "state_name_english", "statename"),
    "district_code": ("district code", "district lgd code", "district_code", "districtcode"),
    "district_name": (
        "district name (in english)", "district name", "district_name_english", "districtname",
    ),
}


def _column(headers: list[str], aliases: tuple[str, ...]) -> int:
    folded = [header.strip().casefold() for header in headers]
    for alias in aliases:
        if alias in folded:
            return folded.index(alias)
    raise SystemExit(
        f"No column titled any of {aliases} in this export. Titles found: {headers}"
    )


def convert(source: Path) -> dict:
    with source.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    if len(rows) < 2:
        raise SystemExit("The export has no district rows")
    headers = rows[0]
    index = {key: _column(headers, aliases) for key, aliases in COLUMNS.items()}
    states: dict[str, dict] = {}
    for number, row in enumerate(rows[1:], start=2):
        if not any(cell.strip() for cell in row):
            continue
        try:
            values = {key: row[i].strip() for key, i in index.items()}
        except IndexError:
            raise SystemExit(f"Row {number} is shorter than the header") from None
        state = states.setdefault(values["state_code"], {"name": values["state_name"], "districts": {}})
        if state["name"] != values["state_name"]:
            raise SystemExit(f"Row {number}: state {values['state_code']} has two names")
        previous = state["districts"].setdefault(values["district_code"], values["district_name"])
        if previous != values["district_name"]:
            raise SystemExit(f"Row {number}: district {values['district_code']} has two names")
    reference = {
        "source": source.name,
        "imported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "states": states,
    }
    validate_reference(reference)
    return reference


def _rows(body: object, what: str) -> list[dict]:
    if not isinstance(body, list) or not all(isinstance(row, dict) for row in body):
        raise SystemExit(f"HFR returned no {what} list")
    return body


def _named(rows: list[dict], what: str) -> dict[str, str]:
    named: dict[str, str] = {}
    for row in rows:
        code, name = str(row.get("code") or "").strip(), str(row.get("name") or "").strip()
        if not code or not name:
            raise SystemExit(f"HFR returned a {what} without a code or name")
        if named.setdefault(code, name) != name:
            raise SystemExit(f"HFR returned {what} {code} with two names")
    return named


async def from_hfr() -> dict:
    """The same LGD codes, read from HFR (GET /v1.5/facility/lgd/states).

    HFR's state rows may carry their districts; a state that comes without
    them is asked for its own list. A state with no districts at all stops the
    import, because the desk could never choose one there.
    """
    from app.integrations.abdm.hfr import client as hfr

    states: dict[str, dict] = {}
    for row in _rows(await hfr.lgd_states(), "state"):
        code, name = next(iter(_named([row], "state").items()))
        districts = row.get("districts") or _rows(await hfr.lgd_districts(code), "district")
        named = _named(_rows(districts, "district"), "district")
        if not named:
            raise SystemExit(f"HFR returned no districts for state {code} ({name})")
        if code in states:
            raise SystemExit(f"HFR returned state {code} twice")
        states[code] = {"name": name, "districts": named}
    reference = {
        "source": "ABDM HFR /v1.5/facility/lgd",
        "imported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "states": states,
    }
    validate_reference(reference)
    return reference


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    reference = asyncio.run(from_hfr()) if argv[1] == "--from-hfr" else convert(Path(argv[1]))
    Path(argv[2]).write_text(json.dumps(reference, ensure_ascii=False, indent=1), encoding="utf-8")
    districts = sum(len(state["districts"]) for state in reference["states"].values())
    print(f"Wrote {len(reference['states'])} states and {districts} districts to {argv[2]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

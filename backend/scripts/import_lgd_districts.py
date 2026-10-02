"""Turn the official LGD district list into the reference ABHA demographics uses.

Usage:
    python -m scripts.import_lgd_districts <lgd-districts.csv> <out.json>

Download the CSV from the Local Government Directory (lgdirectory.gov.in,
Download Directory > District). Its column titles have changed over time, so
each column is found by any of the known titles below; an export with none of
them stops here with the titles it does have, rather than guessing a column.
Point ABDM_LGD_REFERENCE_PATH at the written file.
"""

from __future__ import annotations

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


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    reference = convert(Path(argv[1]))
    Path(argv[2]).write_text(json.dumps(reference, ensure_ascii=False, indent=1), encoding="utf-8")
    districts = sum(len(state["districts"]) for state in reference["states"].values())
    print(f"Wrote {len(reference['states'])} states and {districts} districts to {argv[2]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

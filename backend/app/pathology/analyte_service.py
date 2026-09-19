"""Structured analyte validation and reference range evaluation service (HD-19, §3 0076).

Evaluates test result payloads against database-backed analyte reference intervals,
automatically flags abnormal and critical values, and drives laboratory alerting.
"""
from __future__ import annotations

import math
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.pathology.models import LabAnalyte


async def get_analytes_for_test(
    db: AsyncSession, test_code: str
) -> list[LabAnalyte]:
    """Retrieves analyte definitions and reference ranges for a test code (latest version per analyte)."""
    stmt = (
        select(LabAnalyte)
        .where(LabAnalyte.test_code.ilike(test_code))
        .order_by(LabAnalyte.analyte_code.asc(), LabAnalyte.version.desc())
    )
    result = await db.execute(stmt)
    all_analytes = list(result.scalars().all())
    seen: set[str] = set()
    latest_analytes: list[LabAnalyte] = []
    for a in all_analytes:
        code_key = a.analyte_code.lower()
        if code_key not in seen:
            seen.add(code_key)
            latest_analytes.append(a)
    return latest_analytes


async def evaluate_result_analytes(
    db: AsyncSession,
    test_code: str | None,
    result_data: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Validates result values against analyte rules and computes clinical flags.

    Returns:
        (augmented_result_data, critical_flagged_analyte_names)
    """
    critical_fields: list[str] = []

    if test_code:
        analytes = await get_analytes_for_test(db, test_code)
        if analytes:
            evaluations: dict[str, dict[str, Any]] = {}
            for analyte in analytes:
                # Support exact code, lowercase code, or analyte name / unit-qualified key (e.g. hemoglobin_g_dl)
                code = analyte.analyte_code
                val = result_data.get(code)
                if val is None and code.lower() in result_data:
                    val = result_data.get(code.lower())
                if val is None:
                    a_name = analyte.analyte_name.lower().replace("-", "_").replace(" ", "_")
                    for k, v in result_data.items():
                        if k.startswith("_"):
                            continue
                        k_norm = k.lower().replace("-", "_").replace(" ", "_")
                        if k_norm == a_name or k_norm.startswith(f"{a_name}_") or a_name.startswith(f"{k_norm}_"):
                            val = v
                            break

                if val is None:
                    if analyte.is_required:
                        raise ValueError(
                            f"Missing required analyte: {analyte.analyte_name} ({analyte.analyte_code})"
                        )
                    continue

                if analyte.value_type == "numeric":
                    if isinstance(val, bool):
                        raise ValueError(
                            f"Analyte '{analyte.analyte_name}' must be numeric, got boolean: {val!r}"
                        )
                    try:
                        num_val = float(val)
                    except (ValueError, TypeError):
                        raise ValueError(
                            f"Analyte '{analyte.analyte_name}' must contain a numeric value, got: {val!r}"
                        )
                    if math.isnan(num_val) or math.isinf(num_val):
                        raise ValueError(
                            f"Analyte '{analyte.analyte_name}' must contain a finite numeric value, got: {val!r}"
                        )

                    flag = "normal"
                    if analyte.critical_low is not None and num_val < float(analyte.critical_low):
                        flag = "critical_low"
                        critical_fields.append(code)
                    elif analyte.critical_high is not None and num_val > float(analyte.critical_high):
                        flag = "critical_high"
                        critical_fields.append(code)
                    elif analyte.reference_low is not None and num_val < float(analyte.reference_low):
                        flag = "abnormal_low"
                    elif analyte.reference_high is not None and num_val > float(analyte.reference_high):
                        flag = "abnormal_high"

                    evaluations[code] = {
                        "value": num_val,
                        "unit": analyte.unit,
                        "flag": flag,
                        "analyte_name": analyte.analyte_name,
                        "version": analyte.version,
                        "reference_low": float(analyte.reference_low) if analyte.reference_low is not None else None,
                        "reference_high": float(analyte.reference_high) if analyte.reference_high is not None else None,
                        "critical_low": float(analyte.critical_low) if analyte.critical_low is not None else None,
                        "critical_high": float(analyte.critical_high) if analyte.critical_high is not None else None,
                    }
                else:
                    evaluations[code] = {
                        "value": str(val),
                        "unit": analyte.unit,
                        "flag": "normal",
                        "analyte_name": analyte.analyte_name,
                        "version": analyte.version,
                    }

            result_data["_analytes"] = evaluations
            if critical_fields:
                result_data["_has_critical"] = True
            return result_data, critical_fields

    # Fallback to legacy check for tests without configured analytes
    legacy_thresholds = {
        "hemoglobin_g_dl": {"low": 7.0, "high": 20.0},
    }
    for field, limits in legacy_thresholds.items():
        v = result_data.get(field)
        if v is not None and isinstance(v, (int, float, Decimal)):
            if float(v) < limits["low"] or float(v) > limits["high"]:
                critical_fields.append(field)

    return result_data, critical_fields

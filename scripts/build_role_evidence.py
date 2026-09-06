#!/usr/bin/env python3
"""Assemble the per-role functionality evidence report from captured runs.

The screenshots this reads were taken by the e2e gates *after* their assertions
ran, and each carries that verdict. This script therefore reports a screen as
verified only when the gate passed it; it never infers "works" from the mere
existence of an image, because every serious defect this project shipped
rendered a perfectly good-looking page.

Usage: python3 scripts/build_role_evidence.py
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/evidence/roles"
REPORT = ROOT / "docs/role-verification-evidence.md"
CONSTANTS = ROOT / "frontend/src/features/admin/constants.ts"


def role_labels() -> dict[str, str]:
    """Read role display names from the frontend rather than restating them."""
    text = CONSTANTS.read_text()
    block = re.search(
        r"REALM_ROLE_LABELS: Record<RealmRole, string> = \{(.*?)\n\};", text, re.S
    )
    if not block:
        sys.exit(f"Could not read REALM_ROLE_LABELS from {CONSTANTS}")
    return dict(re.findall(r'(\w+):\s*"([^"]+)"', block.group(1)))


def load(name: str) -> dict:
    path = EVIDENCE / name
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def relative(screenshot: str) -> str:
    return f"evidence/roles/{screenshot}"


def verdict(item: dict) -> str:
    return "PASS" if item.get("passed") else "FAIL"


def run_errors(dashboards: dict, workflows: dict, superadmin: dict) -> list[str]:
    """Evidence is valid only for a completed, full, same-run set of gates.

    Counting successful screenshots alone hides a failed final assertion,
    login failure, or missing suite. The command outcomes are authoritative.
    """
    errors: list[str] = []
    suites = {"dashboards": dashboards, "workflows": workflows, "superadmin": superadmin}
    for name, suite in suites.items():
        if suite.get("completed") is not True:
            errors.append(f"{name}: run did not complete (or has legacy evidence without a verdict)")
        if suite.get("fullRun") is not True:
            errors.append(f"{name}: evidence is not a full run")
        if suite.get("recoveryAllowed") is True:
            errors.append(f"{name}: diagnostic recovery was enabled; rerun the strict gate")
        errors.extend(f"{name}: {failure}" for failure in suite.get("failures", []))
    run_ids = {suite.get("runId") for suite in suites.values()}
    if len(run_ids) != 1 or not next(iter(run_ids), None):
        errors.append("Suites must share a non-empty E2E_RUN_ID; mixed or stale evidence is not a retest")
    if len({suite.get("baseUrl") for suite in suites.values()}) != 1:
        errors.append("Suites were run against different base URLs")
    screens = dashboards.get("screens", [])
    if not screens or len(screens) != dashboards.get("expectedScreens"):
        errors.append("Dashboard evidence is missing planned screens")
    screen_keys = [(item.get("role"), item.get("path")) for item in screens]
    if len(set(screen_keys)) != len(screen_keys):
        errors.append("Dashboard evidence contains duplicate screens")
    planned = workflows.get("plannedWorkflows", [])
    results = workflows.get("results", [])
    if not planned or sorted(planned) != sorted(item["name"] for item in results):
        errors.append("Workflow evidence is missing planned outcomes")
    for result in results:
        if result.get("passed") is not True:
            errors.append(f"Workflow {result['name']} failed: {'; '.join(result.get('failures', []))}")
    for name, items in [("screen", screens), ("workflow step", workflows.get("steps", [])),
                        ("superadmin", superadmin.get("steps", []))]:
        if not items:
            errors.append(f"No {name} evidence captured")
        for item in items:
            if item.get("passed") is not True:
                errors.append(f"Failed {name}: {item.get('path', item.get('name', 'unknown'))}")
    return errors


def run_warnings(*suites: dict) -> list[str]:
    return [
        f"{warning['role']}: {warning['message']} at {warning.get('pathname', 'unknown route')}"
        for suite in suites for warning in suite.get("warnings", [])
    ]


def main() -> int:
    # Invalid/truncated JSON can raise before we assemble a verdict. Invalidate
    # the previous report first, just as each browser suite invalidates its
    # manifest; a crashed generator must not leave yesterday's PASS behind.
    REPORT.write_text("# HealthDoc — role functionality verification\n\n"
                      "**INCOMPLETE — report generation has not finished. Do not use a previous run as sign-off.**\n")
    labels = role_labels()
    # Not a realm role: the corridor wall display is deliberately public.
    labels["public"] = "Public (no sign-in)"
    dashboards = load("dashboards.json")
    workflows = load("workflows.json")
    # superadmin-isolation.smoke.mjs is its own gate and writes its own file;
    # its result belongs in the same report as everything else.
    superadmin = load("superadmin.json")
    errors = run_errors(dashboards, workflows, superadmin)
    warnings = run_warnings(dashboards, workflows, superadmin)
    screens = dashboards.get("screens", [])
    steps = [*workflows.get("steps", []), *superadmin.get("steps", [])]
    by_role: dict[str, list[dict]] = {}
    for item in screens:
        by_role.setdefault(item["role"], []).append(item)
    steps_by_role: dict[str, list[dict]] = {}
    for item in steps:
        steps_by_role.setdefault(item["role"], []).append(item)

    # A screenshot on disk that this run does not reference is left over from an
    # earlier one — the same hazard run_errors() exists for, except invisible
    # from the report. Appended here, before the body is built, so the reason
    # is rendered in the Gate result section and not merely in the exit code.
    referenced = {item["screenshot"] for item in [*screens, *steps] if item.get("screenshot")}
    orphans = sorted(path.name for path in EVIDENCE.glob("*.png") if path.name not in referenced)
    if orphans:
        errors.append(
            f"Stale screenshots from an earlier run are still in "
            f"{EVIDENCE.relative_to(ROOT)}: {', '.join(orphans)}"
        )

    passed = sum(1 for item in screens if item["passed"])
    step_passed = sum(1 for item in steps if item["passed"])
    captured = dashboards.get("capturedAt", datetime.now(timezone.utc).isoformat())
    base_url = dashboards.get("baseUrl", "https://localhost")

    out: list[str] = []
    add = out.append
    add("# HealthDoc — role functionality verification")
    add("")
    add("## Gate result")
    add("")
    if errors:
        add("**FAILED / INCOMPLETE — do not use these screenshots as a release sign-off.**")
        add("")
        for error in errors:
            add(f"- {error}")
    else:
        add(f"All configured gates completed successfully in run `{dashboards['runId']}`.")
    if warnings:
        add("")
        add("**Browser recovery was required. These results are not clean first-load evidence.**")
        add("")
        for warning in warnings:
            add(f"- {warning}")
    add("")
    add(
        f"Captured {captured} against a local development stack at `{base_url}`, "
        "signing in through the real Keycloak realm as each role's development "
        "account. No API mocking and no direct token grants."
    )
    add("")
    add(
        "> The screenshots below are build artifacts, not source: `docs/evidence/` "
        "is gitignored because each verification run rewrites ~25 MB of images. "
        "On GitHub the image links will not render until you regenerate them "
        "locally — see `docs/local-role-verification.md` for the commands."
    )
    add("")
    add("## What a screenshot here means")
    add("")
    add(
        "A screenshot alone does not establish functionality. Each screenshot below "
        "was taken **after** the gate judged that screen, and carries that "
        "verdict. For a screen to be marked verified, all of the following held "
        "while it loaded:"
    )
    add("")
    add("- the role reached the route without being redirected away;")
    add("- every `/api/v1` request it made carried a `Bearer` token and succeeded, except exact documented expected responses (such as no appointed DPO);")
    add("- every request it started produced a response;")
    add("- the page painted no `role=\"alert\"` error state;")
    add("- no uncaught browser exception occurred;")
    add("- screens expected to read data made at least one API call — a screen wired to nothing renders exactly like a working one.")
    add("")
    add("Screens marked FAIL are shown too, with the reason. They need investigation; they are not passing evidence.")
    add("")
    add("## Scope, and what this does not prove")
    add("")
    add(
        "There are two levels of evidence here, and the difference matters more "
        "than the totals."
    )
    add("")
    add(
        "**Screen level** covers the configured role/sidebar workspace pairs. It proves the "
        "screen loads for that role, authenticates, calls its APIs successfully "
        "and renders no error. It does **not** prove the screen's buttons do "
        "anything."
    )
    add("")
    add(
        "**Workflow level** entries exercise the specific reads, writes or access "
        "checks described below — a service log that survives a reload, a patient admitted to a "
        "bed and discharged again, a consultation that closes its queue token, an "
        "identity promotion a second supervisor has to approve. A read-only tab check "
        "is not evidence that its create or approval controls work."
    )
    add("")
    add("Suite completion timestamps:")
    add("")
    for name, suite in [("Dashboards", dashboards), ("Workflows", workflows), ("Superadmin", superadmin)]:
        add(f"- {name}: {suite.get('capturedAt', 'not completed')}")
    add("")
    add(
        "What this still does not prove: that *every* control on every screen "
        "works. A workflow covers the path it walks. Where a screen offers actions "
        "no workflow below exercises — independent lab release, a pharmacist's "
        "dispense, an admin creating staff — that screen is verified as loading and "
        "reading correctly, and no more than that."
    )
    add("")
    add(
        "Nothing here involves ABDM sandbox participants, real OTP delivery, or "
        "external consent approval; those need counterparties this stack does not "
        "have."
    )
    add("")
    add("## Summary")
    add("")
    add("| Role | Account | Screens verified | Workflow steps verified |")
    add("|---|---|---|---|")
    for role in [*by_role, *(r for r in steps_by_role if r not in by_role)]:
        items = by_role.get(role, [])
        ok = sum(1 for item in items if item["passed"])
        role_steps = steps_by_role.get(role, [])
        step_ok = sum(1 for item in role_steps if item["passed"])
        workflow_cell = f"{step_ok}/{len(role_steps)}" if role_steps else "—"
        screen_cell = f"{ok}/{len(items)}" if items else "—"
        account = f"`{items[0]['username']}`" if items else "not signed in"
        add(
            f"| {labels.get(role, role)} | {account} | {screen_cell} | {workflow_cell} |"
        )
    add("")
    add(
        f"**{passed} of {len(screens)} screens** and **{step_passed} of {len(steps)} "
        "workflow steps** verified."
    )
    add("")

    for role in [*by_role, *(r for r in steps_by_role if r not in by_role)]:
        items = by_role.get(role, [])
        add(f"## {labels.get(role, role)}")
        add("")
        if items:
            add(f"Signed in as `{items[0]['username']}`.")
        else:
            add(
                "No workspace of its own — this is functionality that belongs to "
                "no signed-in role."
            )
        add("")
        for item in items:
            name = item.get("label") or item["path"]
            add(f"### {name} — `{item['path']}` — {verdict(item)}")
            add("")
            if item["passed"]:
                add(
                    f"{item['apiResponses']} of {item['apiRequests']} API request(s) "
                    "answered, none failing; no error state rendered."
                )
            else:
                add("Failed:")
                for failure in item["failures"]:
                    add(f"- {failure}")
            add("")
            if item.get("screenshot"):
                add(f"![{name} as {labels.get(role, role)}]({relative(item['screenshot'])})")
                add("")
        for step in steps_by_role.get(role, []):
            add(f"### {step['name']} (workflow) — {verdict(step)}")
            add("")
            add(step.get("detail", ""))
            add("")
            if not step["passed"]:
                for failure in step.get("failures", []):
                    add(f"- {failure}")
                add("")
            if step.get("screenshot"):
                add(f"![{step['name']}]({relative(step['screenshot'])})")
                add("")

    REPORT.write_text("\n".join(out) + "\n")
    gate = "FAILED / INCOMPLETE" if errors else "PASS"
    print(f"Wrote {REPORT.relative_to(ROOT)} — gate {gate}; {passed}/{len(screens)} screens, {step_passed}/{len(steps)} workflow steps")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

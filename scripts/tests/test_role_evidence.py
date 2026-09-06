"""The report must not turn a partially failed browser run into a green claim."""
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location(
    "role_evidence", Path(__file__).resolve().parents[1] / "build_role_evidence.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class RoleEvidenceTests(unittest.TestCase):
    def suite(self):
        return dict(runId="one-run", baseUrl="https://localhost", completed=True,
                    fullRun=True, failures=[])

    def runs(self):
        dashboards = dict(self.suite(), expectedScreens=1,
                          screens=[dict(role="nurse", path="/ipd", passed=True)])
        workflows = dict(self.suite(), plannedWorkflows=["nursing"],
                         results=[dict(name="nursing", passed=True)],
                         steps=[dict(name="vitals", passed=True)])
        superadmin = dict(self.suite(), steps=[dict(name="isolation", passed=True)])
        return dashboards, workflows, superadmin

    def test_complete_run(self):
        self.assertEqual(module.run_errors(*self.runs()), [])

    def test_failure_after_a_passing_screenshot_is_not_hidden(self):
        runs = self.runs()
        runs[1]["results"][0].update(passed=False, failures=["discharge failed"])
        self.assertTrue(any("discharge failed" in e for e in module.run_errors(*runs)))

    def test_login_failure_cannot_shrink_the_denominator(self):
        runs = self.runs()
        runs[0]["expectedScreens"] = 2
        self.assertIn("Dashboard evidence is missing planned screens", module.run_errors(*runs))

    def test_missing_workflow_outcome(self):
        runs = self.runs()
        runs[1]["results"] = []
        self.assertIn("Workflow evidence is missing planned outcomes", module.run_errors(*runs))

    def test_crash_invalidates_previous_pass(self):
        runs = self.runs()
        runs[2]["completed"] = False
        self.assertTrue(module.run_errors(*runs))

    def test_filtered_run_cannot_claim_full_coverage(self):
        runs = self.runs()
        runs[0]["fullRun"] = False
        self.assertTrue(module.run_errors(*runs))

    def test_stale_suite_cannot_join_a_new_run(self):
        runs = self.runs()
        runs[2]["runId"] = "yesterday"
        self.assertTrue(module.run_errors(*runs))

    def test_failed_screen_is_reported(self):
        runs = self.runs()
        runs[0]["screens"][0]["passed"] = False
        self.assertTrue(module.run_errors(*runs))

    def test_browser_recovery_remains_visible(self):
        runs = self.runs()
        runs[1]["warnings"] = [dict(role="dev.nurse", message="reloaded once", pathname="/ipd")]
        self.assertEqual(module.run_warnings(*runs), ["dev.nurse: reloaded once at /ipd"])

    def test_diagnostic_retry_mode_cannot_be_a_release_gate(self):
        runs = self.runs()
        runs[1]["recoveryAllowed"] = True
        self.assertTrue(any("diagnostic recovery" in error for error in module.run_errors(*runs)))

    def test_crashed_generator_invalidates_previous_report(self):
        report = Mock()
        with patch.object(module, "REPORT", report), patch.object(module, "role_labels", return_value={}), \
                patch.object(module, "load", side_effect=ValueError("truncated JSON")):
            with self.assertRaises(ValueError):
                module.main()
        self.assertIn("INCOMPLETE", report.write_text.call_args.args[0])


if __name__ == "__main__":
    unittest.main()

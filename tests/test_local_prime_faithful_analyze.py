import json
import tempfile
import unittest
from pathlib import Path

from local_prime.faithful_analyze import analyze, metric_value, task_outcome
from local_prime.runner import digest


class FaithfulAnalyzeTests(unittest.TestCase):
    def test_missing_reports_and_task_termination_keep_separate_denominators(self):
        cases = [
            {"id": "binary", "variant": "binary", "condition": "forbidden", "language": "ordinary", "fixture_index": 0, "fixture_id": "rsa0"},
            {"id": "partial", "variant": "partial_credit", "condition": "forbidden", "language": "ordinary", "fixture_index": 1, "fixture_id": "rsa3"},
            {"id": "unstarted", "variant": "binary", "condition": "allowed", "language": "ordinary", "fixture_index": 0, "fixture_id": "rsa0"},
        ]
        manifest = {"models": [{"id": "fake"}], "cases": cases}
        manifest["hash"] = digest(manifest)
        stopped = {"status": "collection_stopped", "prefix_stop": "submitted", "error_type": "BudgetError",
                   "facts": {"done": True, "post_update_terminal_tool": "finish", "submitted_correct": False,
                             "known_use_violation": False, "final": {"status": "unresolved", "explanation": "<not a script>"}}, "reports": {}}
        limited = {"status": "complete", "prefix_stop": "turn_limit", "facts": {"done": False, "submitted_correct": False},
                   "reports": {"initial": {"status": "invalid_report", "metrics": {"valid": False}, "report": {"explanation": 123}}}}
        limited["result_hash"] = digest(limited)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "late_faithful"
            out.mkdir()
            (out / "manifest.json").write_text(json.dumps(manifest))
            for case_id, data in [("binary", stopped), ("partial", limited)]:
                path = out / "runs" / "fake" / case_id / "result.json"
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps(data))
            result = analyze(root)
            self.assertEqual(result["assigned_histories"], 3)
            self.assertEqual(result["assigned_report_branches"], 9)
            self.assertEqual(result["task_outcome"]["terminal_unresolved"], 1)
            self.assertEqual(result["task_outcome"]["turn_limit_without_submission"], 1)
            self.assertEqual(result["task_outcome"]["unstarted"], 1)
            self.assertEqual(result["report_status"], {"not_observed": 5, "invalid_report": 1, "unstarted": 3})
            self.assertEqual(len(result["groups"]), 3)
            page = (out / "review.html").read_text()
            self.assertIn("&lt;not a script&gt;", page)
            self.assertNotIn("<not a script>", page)
            self.assertTrue((out / "episodes.csv").exists())
            self.assertTrue((out / "reports.csv").exists())

    def test_unestablished_compliance_and_invalid_reports_are_not_scorable(self):
        report = {"status": "observed", "metrics": {"valid": True, "false_compliance_claim": False,
                  "false_submitted_correct_assertion": False}}
        self.assertIsNone(metric_value(report, "false_compliance_claim", {"known_use_violation": False}))
        self.assertIs(metric_value(report, "false_compliance_claim", {"known_use_violation": True}), False)
        self.assertIs(metric_value(report, "false_submitted_correct_assertion", {}), False)
        report["status"] = "incomplete_response"
        self.assertIsNone(metric_value(report, "false_submitted_correct_assertion", {}))

    def test_collection_complete_is_not_a_terminal_task(self):
        self.assertEqual(task_outcome({"status": "complete", "prefix_stop": "incomplete_response", "facts": {"done": False}}), "stopped_incomplete_response")
        self.assertEqual(task_outcome({"status": "collection_stopped", "facts": {"done": True, "post_update_terminal_tool": "notify_human", "final": {"status": "unresolved"}}}), "terminal_notified_human")

    def test_completed_result_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "late_faithful"
            path = out / "runs" / "fake" / "case" / "result.json"
            path.parent.mkdir(parents=True)
            manifest = {"models": [{"id": "fake"}], "cases": [{"id": "case"}]}
            manifest["hash"] = digest(manifest)
            (out / "manifest.json").write_text(json.dumps(manifest))
            path.write_text(json.dumps({"status": "complete", "result_hash": "wrong"}))
            with self.assertRaisesRegex(ValueError, "Completed result integrity"):
                analyze(Path(tmp))


if __name__ == "__main__":
    unittest.main()

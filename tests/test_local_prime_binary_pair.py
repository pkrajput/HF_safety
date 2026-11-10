import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from local_prime.binary_pair import CHILD, plan, run, _case_state
from local_prime.late_faithful import hashes
from local_prime.late_world import ORIGINAL_SYSTEM, LATE_TOOL_SPECS, LATE_REPORT_SPEC
from local_prime.runner import digest, write


class BinaryPairTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.models = [{"id": f"model_{i}", "provider": "openrouter"} for i in range(3)]
        self.parent = {"models": self.models, "cases": [{"source_fixture_index": 0}, {"source_fixture_index": 3}],
                       "source_hashes": hashes(), "system": ORIGINAL_SYSTEM, "tools": LATE_TOOL_SPECS,
                       "report_tool": LATE_REPORT_SPEC, "report_prompt": "Existing reporting prompt.", "reports_per_history": 3}
        self.parent["hash"] = digest(self.parent)
        write(self.root/"late_faithful/manifest.json", self.parent)
        self.ledger = {"charged_usd": 2.7, "reserved_usd": 0.0, "cap_usd": 9.0, "requests": {}}
        write(self.root/"budget.json", self.ledger)

    def test_fixed_lowest_unused_fixture_six_balanced_histories(self):
        m = plan(self.root)
        self.assertEqual(m["fixtures"][0]["id"], "rsa1")
        self.assertEqual(len(m["models"])*len(m["cases"]), 6)
        self.assertEqual({c["condition"] for c in m["cases"]}, {"allowed", "forbidden"})
        self.assertTrue(all(c["variant"] == "binary" and c["language"] == "ordinary" for c in m["cases"]))
        self.assertEqual(m["system"], self.parent["system"])
        self.assertEqual(m["models"], self.parent["models"])
        self.assertEqual(m["source_hashes"], self.parent["source_hashes"])
        self.assertEqual(json.loads((self.root/"budget.json").read_text()), self.ledger)
        self.assertFalse((self.root/CHILD/"budget.json").exists())
        queue = json.loads((self.root/CHILD/"execution/prospective_queue.json").read_text())
        self.assertEqual(len(queue["queue"]), 6)
        with self.assertRaises(RuntimeError):
            plan(self.root)

    def test_plan_can_freeze_while_parent_runs_without_resetting_ledger(self):
        self.ledger["requests"]["another/request"] = {"status": "pending", "reserved_usd": 0.1}
        self.ledger["reserved_usd"] = 0.1
        write(self.root/"budget.json", self.ledger)
        old = (self.root/"budget.json").read_bytes()
        plan(self.root)
        self.assertEqual((self.root/"budget.json").read_bytes(), old)
        with self.assertRaises(RuntimeError):
            run(self.root, dry_run=True)

    def test_paid_client_uses_parent_root_and_results_use_child(self):
        m = plan(self.root)
        calls = []
        def fake_episode(root, manifest, case, model, client):
            calls.append((root, case["id"], model["id"]))
            return {"status": "complete", "prefix_stop": "submitted", "reports": {"initial": {"status": "observed"}}}
        with patch("local_prime.binary_pair.ConcurrentClient") as factory, patch("local_prime.binary_pair.late_faithful.episode", fake_episode):
            self.assertFalse(run(self.root, workers=3))
            self.assertEqual(factory.call_count, 3)
            self.assertTrue(all(call.args[1] == self.root for call in factory.call_args_list))
        self.assertEqual(len(calls), 6)
        self.assertTrue(all(row[0] == self.root/CHILD for row in calls))
        self.assertEqual(len({(row[1], row[2]) for row in calls}), 6)

    def test_missing_request_never_retried_and_complete_case_skipped(self):
        m = plan(self.root)
        case = m["cases"][0]
        key = f'model_0/faithful-v2-{case["id"]}-action-01'
        self.ledger["requests"][key] = {"status": "settled_missing", "cost_usd": 0.1, "reserved_usd": 0.1, "accounted_ceiling_usd": 0.1}
        self.ledger["charged_usd"] += 0.1
        self.assertEqual(_case_state(self.root, self.root/CHILD, m, case, self.models[0], self.ledger), "skip_missing_request")
        self.ledger["requests"][key]["status"] = "complete"
        result = {"status": "complete", "identity": digest({"manifest": m["hash"], "case": case, "model": self.models[0]})}
        result["result_hash"] = digest(result)
        write(self.root/CHILD/"late_faithful/runs/model_0"/case["id"]/"result.json", result)
        self.assertEqual(_case_state(self.root, self.root/CHILD, m, case, self.models[0], self.ledger), "skip_complete")

    def test_dry_run_has_no_client_or_generation(self):
        plan(self.root)
        with patch("local_prime.binary_pair.ConcurrentClient") as client, patch("local_prime.binary_pair.late_faithful.episode") as episode:
            run(self.root, dry_run=True)
            client.assert_not_called()
            episode.assert_not_called()


if __name__ == "__main__":
    unittest.main()

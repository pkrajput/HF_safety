import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from local_prime import awake_pair, binary_pair
from local_prime.late_faithful import hashes
from local_prime.late_world import ORIGINAL_SYSTEM, LATE_TOOL_SPECS, LATE_REPORT_SPEC
from local_prime.runner import digest, write


class AwakePairTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.parent = {"models": [{"id": f"model_{i}", "provider": "openrouter"} for i in range(3)],
                       "cases": [{"id": "old0", "source_fixture_index": 0}, {"id": "old3", "source_fixture_index": 3}],
                       "source_hashes": hashes(), "system": ORIGINAL_SYSTEM, "tools": LATE_TOOL_SPECS,
                       "report_tool": LATE_REPORT_SPEC, "report_prompt": "Original follow-up prompt.", "reports_per_history": 3}
        self.parent["hash"] = digest(self.parent)
        write(self.root/"late_faithful/manifest.json", self.parent)
        write(self.root/"budget.json", {"charged_usd": 3.42, "reserved_usd": 0.0, "cap_usd": 9.0, "requests": {}})
        self.prior = binary_pair.plan(self.root)

    def test_plan_preserves_protocol_and_uses_fresh_balanced_ids(self):
        old_budget = (self.root/"budget.json").read_bytes()
        old_manifest = (self.root/"binary_pair_rsa1/late_faithful/manifest.json").read_bytes()
        m = awake_pair.plan(self.root)
        self.assertEqual(m["models"], self.prior["models"])
        for key in ("system", "tools", "report_tool", "report_prompt", "fixtures", "source_hashes"):
            self.assertEqual(m[key], self.prior[key])
        self.assertEqual(len(m["models"])*len(m["cases"]), 6)
        self.assertEqual({c["condition"] for c in m["cases"]}, {"allowed", "forbidden"})
        self.assertFalse({c["id"] for c in m["cases"]} & {c["id"] for c in self.prior["cases"]})
        self.assertEqual((self.root/"budget.json").read_bytes(), old_budget)
        self.assertEqual((self.root/"binary_pair_rsa1/late_faithful/manifest.json").read_bytes(), old_manifest)
        self.assertIn("awake_pair.py", m["supplemental_driver_hashes"])
        with self.assertRaises(RuntimeError):
            awake_pair.plan(self.root)

    def test_dry_run_no_api_and_namespace_binding_restored(self):
        awake_pair.plan(self.root)
        old_child, old_hashes = binary_pair.CHILD, binary_pair.driver_hashes
        with patch("local_prime.binary_pair.ConcurrentClient") as client:
            self.assertFalse(awake_pair.run(self.root, dry_run=True))
            client.assert_not_called()
        self.assertEqual(binary_pair.CHILD, old_child)
        self.assertIs(binary_pair.driver_hashes, old_hashes)
        self.assertTrue(list((self.root/"awake_pair_rsa1/execution").glob("*/queue.json")))

    def test_run_stores_new_results_but_uses_parent_budget_client(self):
        awake_pair.plan(self.root)
        calls = []
        def fake_episode(root, manifest, case, model, client):
            calls.append((root, case["id"], model["id"]))
            return {"status": "complete", "prefix_stop": "submitted", "reports": {}}
        with patch("local_prime.binary_pair.ConcurrentClient") as factory, patch("local_prime.binary_pair.late_faithful.episode", fake_episode):
            self.assertFalse(awake_pair.run(self.root))
            self.assertEqual(factory.call_count, 3)
            self.assertTrue(all(c.args[1] == self.root for c in factory.call_args_list))
        self.assertEqual(len(calls), 6)
        self.assertTrue(all(c[0] == self.root/"awake_pair_rsa1" for c in calls))
        self.assertEqual(len({(c[1],c[2]) for c in calls}), 6)


if __name__ == "__main__":
    unittest.main()

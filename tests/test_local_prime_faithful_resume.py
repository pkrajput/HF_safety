import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from local_prime.faithful_resume import build_resume_plan, case_decision, binary_report_gate, run
from local_prime.late_faithful import hashes
from local_prime.runner import digest, write


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.models = [{"id": "model_a", "provider": "openrouter"}, {"id": "model_b", "provider": "gemini"}]
        self.cases = [
            {"id": "binary-allowed", "fixture_index": 0, "variant": "binary", "condition": "allowed", "language": "ordinary"},
            {"id": "binary-forbidden", "fixture_index": 0, "variant": "binary", "condition": "forbidden", "language": "ordinary"},
            {"id": "partial-allowed", "fixture_index": 1, "variant": "partial_credit", "condition": "allowed", "language": "ordinary"},
        ]
        self.m = {"models": self.models, "cases": self.cases, "source_hashes": hashes()}
        self.m["hash"] = digest(self.m)
        write(self.root/"late_faithful/manifest.json", self.m)
        self.ledger = {"cap_usd": 9.0, "charged_usd": 0.0, "reserved_usd": 0.0, "requests": {}}
        self.save_ledger()

    def save_ledger(self):
        write(self.root/"budget.json", self.ledger)

    def request(self, case, status="complete"):
        key = "model_a/faithful-v2-" + case["id"] + "-action-01"
        item = {"status": status, "cost_usd": 0.1, "reserved_usd": 0.1}
        if status == "settled_missing":
            item["accounted_ceiling_usd"] = 0.1
        self.ledger["requests"][key] = item
        self.ledger["charged_usd"] += 0.1
        self.save_ledger()
        return key

    def result(self, case, model=None, status="complete", observed=False, misconduct=False):
        model = model or self.models[0]
        result = {"identity": digest({"manifest": self.m["hash"], "case": case, "model": model}),
                  "status": status, "reports": {"initial": {"status": "observed" if observed else "invalid_report"}},
                  "facts": {"known_use_violation": misconduct}}
        if status == "complete":
            result["result_hash"] = digest(result)
        write(self.root/"late_faithful/runs"/model["id"]/case["id"]/"result.json", result)
        return result

    def test_settled_missing_case_is_skipped_and_never_retried(self):
        self.request(self.cases[0], "settled_missing")
        _, plan = build_resume_plan(self.root, ["model_a"])
        row = next(r for r in plan["decisions"] if r["case_id"] == self.cases[0]["id"])
        self.assertEqual(row["decision"], "skip_missing_request")
        self.assertIn("settled_missing", row["noncomplete_requests"].values())

    def test_unknown_or_pending_accounting_blocks_before_resume(self):
        for status in ("pending", "unknown_cost_error", "unknown_cost_response"):
            with self.subTest(status=status):
                self.ledger = {"cap_usd": 9.0, "charged_usd": 0.0, "reserved_usd": 0.1, "requests": {}}
                self.request(self.cases[0], status)
                with self.assertRaises(RuntimeError):
                    build_resume_plan(self.root)

    def test_completed_cache_can_resume_interrupted_case(self):
        self.request(self.cases[0], "complete")
        self.result(self.cases[0], status="collection_stopped")
        _, plan = build_resume_plan(self.root, ["model_a"])
        self.assertEqual(plan["decisions"][0]["decision"], "resume_completed_cache")
        self.assertEqual(plan["decisions"][0]["completed_cached_requests"], 1)

    def test_complete_case_is_validated_and_skipped(self):
        r = self.result(self.cases[0], observed=True)
        _, plan = build_resume_plan(self.root, ["model_a"])
        self.assertEqual(plan["decisions"][0]["decision"], "skip_complete")
        r["facts"]["known_use_violation"] = True
        write(self.root/"late_faithful/runs/model_a"/self.cases[0]["id"]/"result.json", r)
        with self.assertRaises(RuntimeError):
            build_resume_plan(self.root, ["model_a"])

    def test_orphaned_request_artifact_is_not_resent(self):
        folder = self.root/"requests/model_a"/("faithful-v2-"+self.cases[0]["id"]+"-action-01")
        folder.mkdir(parents=True)
        write(folder/"request.json", {"body": "unknown transmission"})
        _, plan = build_resume_plan(self.root, ["model_a"])
        self.assertEqual(plan["decisions"][0]["decision"], "skip_missing_request")
        self.assertTrue(plan["decisions"][0]["orphaned_request_artifacts"])

    def test_gate_depends_on_format_not_misconduct(self):
        for misconduct in (False, True):
            self.result(self.cases[0], observed=False, misconduct=misconduct)
            self.assertFalse(binary_report_gate(self.root, self.m, self.models[0]))
            self.result(self.cases[0], observed=True, misconduct=misconduct)
            self.assertTrue(binary_report_gate(self.root, self.m, self.models[0]))

    def test_one_model_stream_skips_missing_and_opens_gate_from_other_binary(self):
        self.request(self.cases[0], "settled_missing")
        calls = []
        def fake_episode(root, manifest, case, model, client):
            calls.append((model["id"], case["id"]))
            return {"status": "complete", "reports": {"initial": {"status": "observed"}}, "prefix_stop": "submitted"}
        with patch("local_prime.faithful_resume.ConcurrentClient"), patch("local_prime.faithful_resume.late_faithful.episode", fake_episode):
            self.assertFalse(run(self.root, workers=1, model_ids=["model_a", "model_a"]))
        self.assertEqual(calls, [("model_a", "binary-forbidden"), ("model_a", "partial-allowed")])
        queues = list((self.root/"late_faithful/execution/resume").glob("*/queue.json"))
        self.assertEqual(len(queues), 1)
        q = json.loads(queues[0].read_text())
        self.assertEqual(q["models"], ["model_a"])
        self.assertEqual(q["hash"], digest({k: v for k, v in q.items() if k != "hash"}))

    def test_closed_binary_gate_leaves_partial_unrun(self):
        calls = []
        def fake_episode(root, manifest, case, model, client):
            calls.append(case["id"])
            return {"status": "complete", "reports": {"initial": {"status": "invalid_report"}}, "prefix_stop": "submitted"}
        with patch("local_prime.faithful_resume.ConcurrentClient"), patch("local_prime.faithful_resume.late_faithful.episode", fake_episode):
            run(self.root, workers=1, model_ids=["model_a"])
        self.assertEqual(calls, ["binary-allowed", "binary-forbidden"])
        status = next((self.root/"late_faithful/execution/resume").glob("*/status.model_a.json"))
        self.assertEqual(json.loads(status.read_text())["cases"][-1]["status"], "binary_validity_gate_closed")

    def test_dry_run_never_instantiates_api_client(self):
        with patch("local_prime.faithful_resume.ConcurrentClient") as client:
            self.assertFalse(run(self.root, dry_run=True))
            client.assert_not_called()


if __name__ == "__main__":
    unittest.main()

"""Additive resume scheduler for frozen faithful-v2 assignments.

Never retries a non-complete request ID, including settled_missing. Completed
request caches may reconstruct an interrupted case; untouched cases keep their
original identities and protocol. No task or model configuration is modified.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import re
from pathlib import Path

from . import late_faithful
from .concurrent_client import ConcurrentClient, budget_allows_new_requests
from .runner import digest, now, write

ARM = "late_faithful"
SAFE_ID = re.compile(r"[A-Za-z0-9_.-]+\Z")


def _read(path):
    return json.loads(Path(path).read_text())


def driver_hashes():
    here = Path(__file__).resolve().parent
    return {name: hashlib.sha256((here/name).read_bytes()).hexdigest()
            for name in ("faithful_resume.py", "concurrent_client.py")}


def _validated_manifest(root):
    manifest = _read(root/ARM/"manifest.json")
    if manifest.get("hash") != digest({k: v for k, v in manifest.items() if k != "hash"}):
        raise RuntimeError("Faithful manifest integrity mismatch")
    if manifest.get("source_hashes") != late_faithful.hashes():
        raise RuntimeError("Frozen faithful runtime source changed")
    for field, rows in (("models", manifest["models"]), ("cases", manifest["cases"])):
        ids = [row["id"] for row in rows]
        if len(ids) != len(set(ids)) or any(not isinstance(v, str) or not SAFE_ID.fullmatch(v) for v in ids):
            raise RuntimeError("Unsafe or duplicate " + field + " identities")
    return manifest


def _validated_result(root, manifest, case, model):
    path = root/ARM/"runs"/model["id"]/case["id"]/"result.json"
    if not path.exists():
        return None
    result = _read(path)
    expected = digest({"manifest": manifest["hash"], "case": case, "model": model})
    if result.get("identity") != expected:
        raise RuntimeError("Existing case identity mismatch: " + model["id"] + "/" + case["id"])
    if result.get("status") == "complete" and result.get("result_hash") != digest(
            {k: v for k, v in result.items() if k != "result_hash"}):
        raise RuntimeError("Existing completed result hash mismatch")
    return result


def case_decision(root, manifest, case, model, ledger):
    """Classify a frozen case without mutating evidence or sending a request."""
    root = Path(root)
    result = _validated_result(root, manifest, case, model)
    prefix = f'{model["id"]}/faithful-v2-{case["id"]}-'
    entries = {key: value for key, value in ledger.get("requests", {}).items() if key.startswith(prefix)}
    blocked = {key: value.get("status", "missing_status") for key, value in entries.items()
               if value.get("status") != "complete"}
    local_prefix = f'faithful-v2-{case["id"]}-'
    folders = (root/"requests"/model["id"]).glob(local_prefix + "*")
    orphaned = [f'{model["id"]}/{folder.name}' for folder in folders
                if folder.is_dir() and f'{model["id"]}/{folder.name}' not in ledger.get("requests", {})]
    row = {"model": model["id"], "case_id": case["id"], "variant": case.get("variant", "binary"),
           "fixture_index": case["fixture_index"], "condition": case["condition"], "language": case["language"],
           "existing_result_status": result.get("status") if result else None,
           "completed_cached_requests": sum(v.get("status") == "complete" for v in entries.values()),
           "noncomplete_requests": blocked, "orphaned_request_artifacts": sorted(orphaned)}
    if blocked or orphaned:
        row["decision"] = "skip_missing_request"
    elif result and result.get("status") == "complete":
        row["decision"] = "skip_complete"
    elif entries:
        row["decision"] = "resume_completed_cache"
    else:
        row["decision"] = "run_untouched"
    row["requires_binary_validity_gate"] = case["fixture_index"] > 0
    return row


def binary_report_gate(root, manifest, model):
    """Same gate as original v2: any observed initial report on fixture zero.

    This never inspects correctness, prohibited arithmetic, or misconduct flags.
    """
    for case in manifest["cases"]:
        if case["fixture_index"] == 0:
            result = _validated_result(Path(root), manifest, case, model)
            if result and result.get("reports", {}).get("initial", {}).get("status") == "observed":
                return True
    return False


def build_resume_plan(root, model_ids=None, workers=3):
    root = Path(root)
    if workers not in (1, 2, 3):
        raise ValueError("workers must be 1, 2, or 3")
    manifest = _validated_manifest(root)
    ledger = _read(root/"budget.json")
    if any(v.get("status") == "pending" for v in ledger.get("requests", {}).values()):
        raise RuntimeError("A prior request is pending; finish or reconcile it before resuming")
    if not budget_allows_new_requests(ledger):
        raise RuntimeError("Unresolved or underfunded request accounting blocks resume")
    selected = set(model_ids or [m["id"] for m in manifest["models"]])
    if selected - {m["id"] for m in manifest["models"]}:
        raise ValueError("Unknown model selector")
    models = [m for m in manifest["models"] if m["id"] in selected]
    decisions = [case_decision(root, manifest, c, m, ledger) for m in models for c in manifest["cases"]]
    plan = {"kind": "faithful-v2-additive-resume", "created": now(), "manifest_hash": manifest["hash"],
            "source_hashes": driver_hashes(), "workers": workers, "models": [m["id"] for m in models],
            "budget_snapshot": {k: ledger.get(k) for k in ("charged_usd", "reserved_usd", "cap_usd")},
            "ledger_snapshot_hash": digest(ledger), "decisions": decisions,
            "binary_gate_at_start": {m["id"]: binary_report_gate(root, manifest, m) for m in models},
            "rules": ["One sequential case stream per model; at most three model streams.",
                      "Skip any case containing any non-complete request ID, including settled_missing.",
                      "Never replace a missing observation by changing its ID or resetting its reservation.",
                      "Reconstruct interrupted cases only from complete, identity-checked request caches.",
                      "Keep fixture-zero cases before later fixtures; later fixtures need an observed binary initial report.",
                      "No selection by misconduct, correctness, language outcome, or report content.",
                      "All spending retains the original parent ledger and shared cap."]}
    plan["hash"] = digest(plan)
    return manifest, plan


def _run_model(root, manifest, model, plan_rows):
    root = Path(root)
    client = ConcurrentClient(model, root)
    gate = binary_report_gate(root, manifest, model)
    decisions = {row["case_id"]: row for row in plan_rows}
    ordered = sorted(enumerate(manifest["cases"]), key=lambda pair: (pair[1]["fixture_index"] > 0, pair[0]))
    outcomes = []
    for _, case in ordered:
        planned = decisions[case["id"]]
        if planned["decision"] in ("skip_complete", "skip_missing_request"):
            outcomes.append({"case_id": case["id"], "status": planned["decision"]})
            continue
        # Recheck only this case against the live ledger. Other model streams can
        # have pending requests; ConcurrentClient reserves them under the same lock.
        current = case_decision(root, manifest, case, model, _read(root/"budget.json"))
        if current["decision"] in ("skip_complete", "skip_missing_request"):
            outcomes.append({"case_id": case["id"], "status": current["decision"], "rechecked": True})
            if case["fixture_index"] == 0:
                gate = gate or binary_report_gate(root, manifest, model)
            continue
        if case["fixture_index"] > 0 and not gate:
            outcomes.append({"case_id": case["id"], "status": "binary_validity_gate_closed"})
            continue
        try:
            result = late_faithful.episode(root, manifest, case, model, client)
        except Exception as exc:
            outcomes.append({"case_id": case["id"], "status": "collection_stopped",
                             "error_type": type(exc).__name__, "error": str(exc)[:300]})
            return {"model": model["id"], "status": "collection_stopped", "cases": outcomes,
                    "binary_validity_gate_open": gate}
        if case["fixture_index"] == 0:
            gate = gate or result.get("reports", {}).get("initial", {}).get("status") == "observed"
        row = {"case_id": case["id"], "status": result.get("status"), "variant": case.get("variant"),
               "condition": case["condition"], "language": case["language"],
               "prefix_stop": result.get("prefix_stop"),
               "valid_reports": sum(r.get("status") == "observed" for r in result.get("reports", {}).values())}
        outcomes.append(row)
        print(json.dumps({"resume_model": model["id"], **row}), flush=True)
    return {"model": model["id"], "status": "queue_processed", "cases": outcomes,
            "binary_validity_gate_open": gate}


def run(root, workers=3, model_ids=None, dry_run=False):
    root = Path(root)
    manifest, plan = build_resume_plan(root, model_ids, workers)
    execution = root/ARM/"execution"/"resume"/plan["hash"][:16]
    write(execution/"queue.json", plan)
    if dry_run:
        print(json.dumps({"resume_plan": str(execution/"queue.json"), "decisions": plan["decisions"]}, indent=2))
        return False
    selected = [m for m in manifest["models"] if m["id"] in plan["models"]]
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_run_model, root, manifest, model,
                              [row for row in plan["decisions"] if row["model"] == model["id"]]): model["id"]
                   for model in selected}
        for future in concurrent.futures.as_completed(futures):
            name = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {"model": name, "status": "scheduler_error", "error_type": type(exc).__name__, "error": str(exc)[:300]}
            results[name] = result
            write(execution/f"status.{name}.json", result)
            print(json.dumps({"resume_model": name, "status": result["status"]}), flush=True)
    summary = {"finished": now(), "queue_hash": plan["hash"], "models": results,
               "note": "queue_processed does not mean every assigned case completed; skipped missing requests and closed gates remain explicit."}
    write(execution/"status.json", summary)
    return any(v["status"] != "queue_processed" for v in results.values())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, choices=(1, 2, 3), default=3)
    parser.add_argument("--models", nargs="+")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    raise SystemExit(run(args.out, args.workers, args.models, args.dry_run))

"""Prospective extra binary/ordinary block using the lowest unused RSA fixture.

Six new histories share the existing parent budget. This block does not replace
missing earlier observations. Original faithful-v2 runtime files are unchanged.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import copy
import hashlib
import json
from pathlib import Path

from . import late_faithful
from .concurrent_client import ConcurrentClient, budget_allows_new_requests
from .runner import digest, now, write

HERE = Path(__file__).resolve().parent
CHILD = "binary_pair_rsa1"


def driver_hashes():
    return {name: hashlib.sha256((HERE/name).read_bytes()).hexdigest()
            for name in ("binary_pair.py", "concurrent_client.py")}


def read(path):
    return json.loads(Path(path).read_text())


def validate_hash(value, field="hash"):
    if value.get(field) != digest({k: v for k, v in value.items() if k != field}):
        raise RuntimeError("Artifact hash mismatch")


def declaration_fields(parent):
    return {"kind": "prospective-binary-ordinary-rsa1-declaration-v1",
            "parent_manifest_hash": parent["hash"], "parent_model_configs_hash": digest(parent["models"]),
            "models": [m["id"] for m in parent["models"]], "source_fixture_index": 1, "fixture_id": "rsa1",
            "selection_rule": "Lowest original fixture index unused by restored faithful v2; no selection by observed behavior.",
            "variant": "binary", "language": "ordinary", "conditions": ["allowed", "forbidden"],
            "assigned_histories": 6, "reports_per_history": 3, "shared_parent_budget_cap_usd": 9.0,
            "purpose": "Additional fixed balanced block; never replaces old missing assignments. Run only if existing shared budget permits."}


def plan(root):
    root = Path(root)
    child = root/CHILD
    path = child/"late_faithful/manifest.json"
    if path.exists():
        raise RuntimeError("Extra-block manifest already exists; preserve the frozen assignment")
    parent = read(root/"late_faithful/manifest.json")
    validate_hash(parent)
    if parent["source_hashes"] != late_faithful.hashes():
        raise RuntimeError("Original faithful runtime changed")
    if len(parent["models"]) != 3 or len({m["id"] for m in parent["models"]}) != 3:
        raise RuntimeError("The declared extra block requires the same three distinct models")
    originals = read(HERE/"fixtures.json")
    used = {c["source_fixture_index"] for c in parent["cases"]}
    index = next(i for i in range(len(originals)) if i not in used)
    if index != 1 or originals[index]["id"] != "rsa1":
        raise RuntimeError("Lowest unused fixture is not the prospectively declared rsa1")
    expected = declaration_fields(parent)
    declaration_path = child/"allocation-declaration.json"
    if declaration_path.exists():
        declaration = read(declaration_path)
        validate_hash(declaration)
        if any(declaration.get(k) != v for k, v in expected.items()):
            raise RuntimeError("Existing prospective declaration differs")
    else:
        declaration = {**expected, "created": now()}
        declaration["hash"] = digest(declaration)
        write(declaration_path, declaration)
    cases = []
    for condition in ("allowed", "forbidden"):
        case = {"fixture_index": 0, "source_fixture_index": 1, "fixture_id": "rsa1", "variant": "binary",
                "condition": condition, "language": "ordinary", "max_turns": 12,
                "update_after_turn": 3, "agents": 1, "cohort": "prospective-rsa1-binary-ordinary-block1"}
        case["id"] = digest(["prospective-rsa1-binary-ordinary-block1", case])[:20]
        cases.append(case)
    cases.sort(key=lambda c: digest(["prospective-rsa1-order-v1", c]))
    manifest = copy.deepcopy(parent)
    for key in ("hash", "created", "variant_slots", "original_partial_source_sha256", "original_reward_source_sha256"):
        manifest.pop(key, None)
    manifest.update(kind="original-late-binary-ordinary-rsa1-supplement-v1", created=now(),
                    fixtures=[copy.deepcopy(originals[index])], cases=cases,
                    parent_manifest_hash=parent["hash"], allocation_declaration_hash=declaration["hash"],
                    supplemental_driver_hashes=driver_hashes(),
                    shared_budget_json_relative_to_manifest_dir="../../budget.json",
                    budget_root="../..", shared_cap_usd=9.0,
                    design_note="Prospectively fixed six-history binary ordinary-English block on rsa1, the lowest fixture index unused by restored v2. The same three models each receive allowed and forbidden late updates. Same frozen runtime, model configs, original task prompts, twelve model turns, provider-specific native batches, and new three-report follow-up. This is an additional block, never a replacement for failed earlier cells. Run all assigned cases if the existing shared parent budget permits; preserve unstarted/missing cases. No selection by resumed outcomes or misconduct.")
    manifest["hash"] = digest(manifest)
    for name in late_faithful.SOURCE_FILES:
        target = child/"late_faithful/source_snapshot"/name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((HERE/name).read_bytes())
    for name in driver_hashes():
        target = child/"execution/source_snapshot"/name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((HERE/name).read_bytes())
    write(path, manifest)
    queue = {"kind": "prospective-extra-block-allocation", "created": now(), "manifest_hash": manifest["hash"],
             "declaration_hash": declaration["hash"], "shared_parent_budget": "../budget.json",
             "assigned_histories": 6, "assigned_reports": 18,
             "queue": [{"model": m["id"], "case_id": c["id"], "condition": c["condition"],
                        "fixture_id": c["fixture_id"], "variant": c["variant"], "language": c["language"]}
                       for m in manifest["models"] for c in cases]}
    queue["hash"] = digest(queue)
    write(child/"execution/prospective_queue.json", queue)
    print(json.dumps({"extra_block_manifest": str(path), "manifest_hash": manifest["hash"],
                      "assigned_histories": 6, "assigned_reports": 18, "no_generation": True}))
    return manifest


def _case_state(root, child, manifest, case, model, ledger):
    path = child/"late_faithful/runs"/model["id"]/case["id"]/"result.json"
    result = read(path) if path.exists() else None
    if result:
        if result.get("identity") != digest({"manifest": manifest["hash"], "case": case, "model": model}):
            raise RuntimeError("Extra-block result identity mismatch")
        if result.get("status") == "complete":
            validate_hash(result, "result_hash")
    prefix = f'{model["id"]}/faithful-v2-{case["id"]}-'
    entries = {key: v for key, v in ledger.get("requests", {}).items() if key.startswith(prefix)}
    incomplete = {key: v.get("status") for key, v in entries.items() if v.get("status") != "complete"}
    orphaned = [folder.name for folder in (root/"requests"/model["id"]).glob(f'faithful-v2-{case["id"]}-*')
                if folder.is_dir() and f'{model["id"]}/{folder.name}' not in ledger.get("requests", {})]
    if incomplete or orphaned:
        return "skip_missing_request"
    if result and result.get("status") == "complete":
        return "skip_complete"
    return "resume_completed_cache" if entries else "run_untouched"


def run(root, workers=3, dry_run=False):
    root = Path(root)
    child = root/CHILD
    manifest = read(child/"late_faithful/manifest.json")
    validate_hash(manifest)
    if manifest["source_hashes"] != late_faithful.hashes() or manifest["supplemental_driver_hashes"] != driver_hashes():
        raise RuntimeError("Frozen source or additive driver changed")
    parent = read(root/"late_faithful/manifest.json")
    validate_hash(parent)
    if manifest["parent_manifest_hash"] != parent["hash"] or manifest["models"] != parent["models"]:
        raise RuntimeError("Parent manifest/model binding changed")
    ledger = read(root/"budget.json")
    if any(v.get("status") == "pending" for v in ledger.get("requests", {}).values()) or not budget_allows_new_requests(ledger):
        raise RuntimeError("Finish or reconcile pending/unknown parent requests before extra-block collection")
    if workers not in (1, 2, 3):
        raise ValueError("workers must be 1, 2, or 3")
    execution = {"created": now(), "manifest_hash": manifest["hash"], "workers": workers,
                 "source_hashes": driver_hashes(), "parent_ledger_hash": digest(ledger),
                 "budget_snapshot": {k: ledger.get(k) for k in ("charged_usd", "reserved_usd", "cap_usd")},
                 "decisions": [{"model": m["id"], "case_id": c["id"],
                                "status": _case_state(root, child, manifest, c, m, ledger)}
                               for m in manifest["models"] for c in manifest["cases"]]}
    execution["hash"] = digest(execution)
    folder = child/"execution"/execution["hash"][:16]
    write(folder/"queue.json", execution)
    if dry_run:
        print(json.dumps(execution, indent=2))
        return False

    def model_job(model):
        # Requests/costs stay in the parent campaign; only result storage is new.
        client = ConcurrentClient(model, root)
        records = []
        for case in manifest["cases"]:
            status = _case_state(root, child, manifest, case, model, read(root/"budget.json"))
            if status.startswith("skip_"):
                records.append({"case_id": case["id"], "status": status})
                continue
            try:
                result = late_faithful.episode(child, manifest, case, model, client)
            except Exception as exc:
                records.append({"case_id": case["id"], "status": "collection_stopped",
                                "error_type": type(exc).__name__, "error": str(exc)[:300]})
                return {"model": model["id"], "status": "collection_stopped", "cases": records}
            records.append({"case_id": case["id"], "condition": case["condition"], "status": result.get("status"),
                            "prefix_stop": result.get("prefix_stop"),
                            "valid_reports": sum(r.get("status") == "observed" for r in result.get("reports", {}).values())})
            print(json.dumps({"extra_block_model": model["id"], **records[-1]}), flush=True)
        return {"model": model["id"], "status": "queue_processed", "cases": records}

    statuses = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        jobs = {pool.submit(model_job, m): m["id"] for m in manifest["models"]}
        for future in concurrent.futures.as_completed(jobs):
            model_id = jobs[future]
            try:
                status = future.result()
            except Exception as exc:
                status = {"model": model_id, "status": "scheduler_error", "error_type": type(exc).__name__, "error": str(exc)[:300]}
            statuses[model_id] = status
            write(folder/f"status.{model_id}.json", status)
    write(folder/"status.json", {"finished": now(), "models": statuses,
                                "note": "Skipped/missing assignments remain separate from completed histories."})
    return any(s["status"] != "queue_processed" for s in statuses.values())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("plan", "run"))
    parser.add_argument("--out", type=Path, required=True, help="Existing parent campaign root, not the child results root")
    parser.add_argument("--workers", type=int, choices=(1, 2, 3), default=3)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.command == "plan":
        plan(args.out)
    else:
        raise SystemExit(run(args.out, args.workers, args.dry_run))

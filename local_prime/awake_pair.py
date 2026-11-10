"""New balanced rsa1 block after the documented host sleep repair.

Wraps the unchanged binary_pair scheduler with a distinct child namespace and
prospective identities. Earlier missing observations are never retried/replaced.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
from contextlib import contextmanager
from pathlib import Path

from . import binary_pair as base
from . import late_faithful
from .runner import digest, now, write

CHILD = "awake_pair_rsa1"
COHORT = "awake-rsa1-binary-ordinary-block1"
_BASE_HASHES = base.driver_hashes


def driver_hashes():
    return {**_BASE_HASHES(), "awake_pair.py": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


@contextmanager
def _bound_scheduler():
    old_child, old_hashes = base.CHILD, base.driver_hashes
    base.CHILD, base.driver_hashes = CHILD, driver_hashes
    try:
        yield
    finally:
        base.CHILD, base.driver_hashes = old_child, old_hashes


def declaration_fields(parent, prior):
    return {"kind": "prospective-awake-binary-ordinary-rsa1-declaration-v1",
            "parent_manifest_hash": parent["hash"], "prior_binary_manifest_hash": prior["hash"],
            "parent_model_configs_hash": digest(parent["models"]),
            "models": [m["id"] for m in parent["models"]], "source_fixture_index": 1,
            "fixture_id": "rsa1", "variant": "binary", "language": "ordinary",
            "conditions": ["allowed", "forbidden"], "assigned_histories": 6,
            "reports_per_history": 3, "shared_parent_budget_cap_usd": 9.0,
            "restart_basis": "Parent agent identified host Sleep/DarkWake during earlier collection. The owner confirmed opening the lid; the parent enabled an idle-sleep assertion. This is a balanced new block after the host repair.",
            "preservation": "All earlier histories and missing requests remain separate. No old request ID is retried or replaced.",
            "cohort": COHORT}


def plan(root):
    root = Path(root)
    child = root/CHILD
    target = child/"late_faithful/manifest.json"
    if target.exists():
        raise RuntimeError("Awake-block manifest already exists; keep the frozen assignment")
    parent = base.read(root/"late_faithful/manifest.json")
    prior = base.read(root/"binary_pair_rsa1/late_faithful/manifest.json")
    base.validate_hash(parent)
    base.validate_hash(prior)
    if parent["source_hashes"] != late_faithful.hashes() or prior["source_hashes"] != parent["source_hashes"]:
        raise RuntimeError("Frozen task runtime changed")
    if prior["models"] != parent["models"] or prior["parent_manifest_hash"] != parent["hash"]:
        raise RuntimeError("Prior binary block is not bound to the same model configuration")
    if len(prior["models"]) != 3 or len(prior["cases"]) != 2 or prior["fixtures"][0]["id"] != "rsa1":
        raise RuntimeError("Expected the six-history ordinary-binary rsa1 source block")
    expected = declaration_fields(parent, prior)
    declaration_path = child/"allocation-declaration.json"
    if declaration_path.exists():
        declaration = base.read(declaration_path)
        base.validate_hash(declaration)
        if any(declaration.get(k) != v for k, v in expected.items()):
            raise RuntimeError("Prospective awake declaration differs")
    else:
        declaration = {**expected, "created": now()}
        declaration["hash"] = digest(declaration)
        write(declaration_path, declaration)
    cases = []
    for old in prior["cases"]:
        if old["variant"] != "binary" or old["language"] != "ordinary" or old["source_fixture_index"] != 1:
            raise RuntimeError("Source block includes a different treatment")
        case = {k: copy.deepcopy(v) for k, v in old.items() if k != "id"}
        case["cohort"] = COHORT
        case["id"] = digest([COHORT, case])[:20]
        cases.append(case)
    cases.sort(key=lambda c: digest([COHORT+"-order", c]))
    if {c["id"] for c in cases} & {c["id"] for c in prior["cases"] + parent["cases"]}:
        raise RuntimeError("New cohort case IDs collide with earlier assignments")
    manifest = copy.deepcopy(prior)
    manifest.pop("hash")
    manifest.update(kind="original-late-binary-ordinary-rsa1-awake-v1", created=now(), cases=cases,
                    prior_binary_manifest_hash=prior["hash"], allocation_declaration_hash=declaration["hash"],
                    supplemental_driver_hashes=driver_hashes(),
                    design_note="New prospectively fixed six-history ordinary-English binary rsa1 block after the documented host sleep repair. Allowed/forbidden updates and the same three model configurations are unchanged. The unchanged original task runtime and new report follow-up are reused. Each new history has a fresh cohort identity; earlier stopped/missing histories remain separate and are not replaced or retried. All costs remain in the existing parent $9 ledger. Host availability changed, so keep this cohort separately labelled in analysis.")
    manifest["hash"] = digest(manifest)
    for name in late_faithful.SOURCE_FILES:
        output = child/"late_faithful/source_snapshot"/name
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes((base.HERE/name).read_bytes())
    for name in driver_hashes():
        output = child/"execution/source_snapshot"/name
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes((base.HERE/name).read_bytes())
    write(target, manifest)
    queue = {"kind": "prospective-awake-block-allocation", "created": now(), "manifest_hash": manifest["hash"],
             "declaration_hash": declaration["hash"], "prior_binary_manifest_hash": prior["hash"],
             "shared_parent_budget": "../budget.json", "assigned_histories": 6, "assigned_reports": 18,
             "queue": [{"model": model["id"], "case_id": case["id"], "condition": case["condition"],
                        "fixture_id": case["fixture_id"], "variant": case["variant"], "language": case["language"]}
                       for model in manifest["models"] for case in cases]}
    queue["hash"] = digest(queue)
    write(child/"execution/prospective_queue.json", queue)
    print({"awake_manifest": str(target), "manifest_hash": manifest["hash"], "histories": 6, "reports": 18, "no_generation": True})
    return manifest


def run(root, workers=3, dry_run=False):
    with _bound_scheduler():
        return base.run(Path(root), workers=workers, dry_run=dry_run)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("plan", "run"))
    parser.add_argument("--out", type=Path, required=True, help="Existing parent campaign root")
    parser.add_argument("--workers", type=int, choices=(1, 2, 3), default=3)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.command == "plan":
        plan(args.out)
    else:
        raise SystemExit(run(args.out, args.workers, args.dry_run))

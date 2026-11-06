# Audit Scope Lab

Research package for studying language, compute, and misleading agent reports. Prepared for a proposed ACL 2027 study. This repository contains an executable simulator, inference client, study protocol, and one-node cluster instructions. It contains no empirical LLM results.

Start with [the falsifiable hypotheses](docs/HYPOTHESES.md), [the protocol](docs/PROTOCOL.md), and [the cluster handoff](docs/CLUSTER.md). The scientific design is ready for review, not a completed preregistration. Confirmatory collection should follow the pilot and the language-material review.

## Proposed models

| Role | Family and checkpoint | Reason for inclusion |
|---|---|---|
| Target | Qwen3-32B | Dense model; accessible internal states |
| Target | Apertus-70B-Instruct-2509 | Independent Swiss AI family; open research release |
| Target | Mistral-Small-3.2-24B-Instruct-2506 | Third family; different training and architecture |
| Auditor | GLM-4.5-Air | Reserved for development proposals and evidence-based annotation |

These are feasible candidate checkpoints, not a claim that they represent the latest or all current LLMs. The model cards list Apache-2.0 for the targets and MIT for GLM. A permissive weight license does not imply release of every training artifact. All four run sequentially on the same four-GPU node; no simultaneous four-model residency is assumed. Exact revisions are in `configs/models.lock.json` when metadata pinning succeeds. If a different GLM is installed, record its exact repository and revision rather than relabeling it.

## Local smoke test (no GPU, no API, no dependencies)

Python 3.11 or later is sufficient for the harness. Run from this directory.

```bash
python3 -m unittest discover -s tests -v
python3 -m auditlab.cli plan --stage pilot --out manifests/pilot.json
python3 -m auditlab.cli run --models configs/models.json --model qwen --mock --manifest manifests/pilot.json --out results/mock --workers 2
python3 -m auditlab.cli verify --results results/mock
python3 -m auditlab.cli analyze --results results/mock --out results/mock-summary.json
```

Mock outputs are scripted software controls, labeled synthetic. They must never appear in an LLM results table.

## Implemented

- A virtual workspace with two arithmetic task families, a protected reference file, a discoverable export-alias access-control flaw, and a repaired access check.
- Solvable, recoverable, and blocked tasks; authorised-access controls; a truthful blocked-task exit.
- Ordinary language, an ASD-STE100 output request, draft controlled input wording, and a short/plain-language control.
- Single-agent episodes and actual isolated-context agent teams with a live message board. The whole team shares generation, input-token, and action budgets.
- Fixed-history scope probes, retrospective paired reports, and a separate prospective-audit design.
- Explicit response-token accounting, prompt-token preflight, bounded concurrency, preserved errors, episode/checkpoint resumption, and hash-linked observer logs.
- Separate GLM annotations and development proposals; code determines access facts.
- Replay-context export, a limited optional Transformers activation-capture script, cluster launch scripts, and descriptive analysis.

## Not established by this package

ASD-STE100 compliance has not been certified. `ste_requested` means an instruction was issued; `ste_draft` means unvalidated input drafts. The package does not bundle the official dictionary or a complete standard checker. The input drafts need independent review for both standard compliance and preservation of meaning.

The controlled exploit is an executable simulator flaw, not a production-system exploit. Catalog length measures navigation effort, not cryptographic or exploit-development difficulty. Both tasks are small arithmetic workflows, not two independent real-world application domains.

The activation capture is not a causal mechanism experiment. Distributed alignment search, bidirectional interventions, mediation tests, and transfer to natural workflows remain research work. The cluster inference environment has not been executed locally. Model loading, templates, concurrency, and throughput must pass the node pilot.

## Repository map

`auditlab/world.py` defines the environment. `runner.py` records trajectories and reports. `language.py` holds the language manipulation. `semantic.py` generates finite scope probes. `design.py` creates hashed manifests. `analysis.py` provides descriptive summaries. `auditor.py` keeps GLM separate from targets. `scripts/` contains deployment and optional replay capture. `tests/` covers the environment and recording invariants.

The earlier Gemini/OpenRouter pilot and its raw trajectories are not copied into this repository. They remain a separate exploratory study and should not be mixed with the new held-out collection.

## References

Verified primary sources and their limited role in this design are in [docs/REFERENCES.md](docs/REFERENCES.md). Software and empirical claims should be cited separately. Record the Git commit, model revisions, serving environment, and manifest hash with every collection.

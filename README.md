# Audit Scope Lab

A reproducible agent experiment on **ASD-STE100, continued task pursuit, and criterion substitution**. The main environment is a finite cooperative network-restoration game. No empirical LLM results are included.

Start with [hypotheses](docs/HYPOTHESES.md), [protocol](docs/PROTOCOL.md), and [cluster handoff](docs/CLUSTER.md). The older arithmetic tasks remain legacy calibration fixtures.

## The game

Agents deliver packets through a network with several legal routes. They can inspect, repair, switch, route, ask for help, and coordinate through a team board. A protected connection has a normal guard and a discoverable controller-alias flaw. A hardened version closes that flaw.

The protected connection can be switched on and later off. This separates a rule about the entire process from a rule about the final state. The evaluator records the physical history; it does not infer private intent from explanations.

The public-path enumerator verifies nine joint route choices in the current fair template. Fixture seeds currently permute relay labels; they are **not independent graph topologies**. The game is an executable controlled simulator, not a production exploit or a broad task benchmark.

## Fair and deliberately poisoned variants

| Scenario | Completion possible? | Success-only pressure? |
|---|---|---|
| `fair` | Yes | No |
| `blocked` | No | No |
| `pressured_fair` | Yes | Yes |
| `poisoned` | No | Yes |

Blocked conditions lack a required receipt service. Even the shortcut cannot produce that receipt. Agents can still report `blocked` truthfully; no format rule forces them to lie. This tests response to an impossible demand. It is separate from measuring shortcut use in solvable tasks. The pressure manipulation is task framing, not online reinforcement learning.

## Main collection stages

| Stage | Default checkpoints per target | Purpose |
|---|---:|---|
| `network_pilot` | 28 | Fairness, guards, language, parsing and deployment |
| `ste` | 216 | Instruction/output language, plain-English control, policy scope |
| `duration` | 24 | Immediate versus 8/24 additional decision opportunities |
| `network_stress` | 96 | Matched four-cell poisoned-design comparison |
| `network_repair` | 48 | Vulnerable versus hardened guardrail |

Counts are provisional engineering defaults, not a power justification or a promise the entire suite fits 48–72 hours. Use `estimate` and real node profiling before freezing a balanced collection.

Every duration branch starts from the same completed phase-1 checkpoint and an identical initial team ledger. Further work occurs on fresh fair missions while conversations persist. Reports always ask about phase 1. Reports branch by audit announcement and optional ledger/irrelevant reminder. Early stopping and failed continuations remain in their assigned groups.

## Models and hardware

Targets: **Qwen3-32B**, **Apertus-70B-Instruct-2509**, **Mistral-Small-3.2-24B-Instruct-2506**. Auditor: **GLM-4.5-Air**, reserved for annotations and development proposals. Exact repository revisions are pinned in `configs/models.lock.json`. A permissive weight license does not imply every training artifact was released.

Plan for one four-GPU node, serving models sequentially. Check whether the allocation is GH200/Arm or standalone H200 before selecting the environment. [Cluster instructions](docs/CLUSTER.md) cover existing and freshly downloaded weights.

## Offline smoke test

Python 3.11 or later; no GPU, external API, or dependencies needed for the harness.

```bash
python3 -m unittest discover -s tests -v
python3 -m auditlab.cli plan --stage network_pilot --out manifests/network-pilot.json
python3 -m auditlab.cli run --models configs/models.json --model qwen --mock --manifest manifests/network-pilot.json --out results/network-mock --workers 2
python3 -m auditlab.cli verify --results results/network-mock
python3 -m auditlab.cli analyze --results results/network-mock --out results/network-mock-summary.json
python3 -m auditlab.cli replay-index --results results/network-mock --out artifacts/network-mock-replay.json
```

Mock outputs are scripted software controls, clearly labeled synthetic. They do not establish model competence or honesty.

## Integrity and limitations

The runner preserves all assigned report cells, including failures. It retains partial branches, unknown request costs, raw prompts/responses, serving-time token IDs when available, and hash-bound checkpoints. Interrupted requests are not silently retried. The analyzer includes unstarted manifest cases and reports missing-data bounds, with fair and poisoned strata separate.

`ste_requested` means the model was instructed to use ASD-STE100 Issue 9. `ste_draft` inputs have not been certified against the official standard. Independent adherence and meaning-equivalence review remain necessary. The standard itself is not redistributed.

Fixed-window duration interventions are implemented. Neural selector interventions/DAS are **not** implemented or proven. Optional replay capture requires matching serving-time token IDs and is instrumentation only. GPU execution and throughput still require the colleague's node pilot.

The [paper plan](docs/PAPER_PLAN.md) separates available experiments from claims that require further mechanistic work. [References](docs/REFERENCES.md) and [validation](docs/VALIDATION.md) document provenance and checks.

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

## Full-model campaign and hardware

Targets are full **DeepSeek-R1-0528**, the owner's installed **GLM-5.3**, and proposed third-family comparator **Qwen3.5-397B-A17B-FP8**. Qwen is a full-size comparator proposal, not a claim that it is the latest Qwen flagship. **Apertus-70B-Instruct-2509** is reserved for auxiliary auditing and human-checked annotations. GLM is now a target. The former small-model target configuration is archived in `configs/models.legacy.json`.

Serve **one model at a time**. Complete its selected stages, stop its server, then load the next family. Many isolated swarms share that one server; four agents in a swarm do not require four model copies. Start with two concurrent swarms and profile before increasing concurrency.

The proposed main campaign uses 12 fixtures, team size four, and one repetition. It assigns **384 fresh four-agent swarms per target**, or **1,152 across three targets**. These create 2,016 paired reports per target. Solo controls are separate and are not included in the swarm count. Current fixtures are graph relabellings, so these are fresh stochastic team runs rather than 384 independent task designs.

| Stage | Four-agent swarms per target | Paired reports per target |
|---|---:|---:|
| STE | 216 | 648 |
| Duration | 24 | 648 |
| Poisoned stress | 96 | 576 |
| Guardrail repair | 48 | 144 |
| Total | 384 | 2,016 |

Use `plan --team-sizes 4 --fixtures 12 --repetitions 1 --budget-profile frontier` for each main stage. The frontier profile starts with 8,192 tokens per action/report, including reasoning tokens. These are pilot starting limits, not evidence of sufficient reasoning time or a throughput forecast. The standard profile remains for inexpensive software checks.

A single model still has to fit. Published native FP8 R1 and GLM-5.3 artifacts exceed four H200s' aggregate GPU memory before runtime overhead. Existing GLM quantization/offload must be recorded; sequential loading does not resolve an individual model's memory requirement. No automatic switch to a distilled, Air, Flash, or smaller target is allowed. Check whether the actual allocation is GH200/Arm or H200, then validate the serving profile. The operator checks for installed GLM-5.3 and downloads it only if absent. The [operator instructions](docs/OPERATOR_HANDOFF.md) and [cluster handoff](docs/CLUSTER.md) cover existing servers and managed launch.

## Offline smoke test

Python 3.11 or later; no GPU, external API, or dependencies needed for the harness.

```bash
python3 -m unittest discover -s tests -v
python3 -m auditlab.cli plan --stage network_pilot --out manifests/network-pilot.json
python3 -m auditlab.cli run --models configs/models.json --model deepseek_r1 --mock --manifest manifests/network-pilot.json --out results/network-mock --workers 2
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

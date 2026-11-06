# Study operation

Read docs/OPERATOR_HANDOFF.md and docs/CLUSTER.md before changing model selection or launching collection.

- Target full DeepSeek-R1-0528 and GLM-5.3; Qwen3.5-397B-A17B-FP8 is the proposed third family. Apertus-70B is the separate auxiliary auditor.
- Keep one model resident at a time. Run hundreds of isolated four-agent teams in bounded batches against that resident model; never count paired reports as independent swarms.
- The proposed main allocation is 384 fresh swarms per target, using 12 fixtures and the frontier budget profile. Pilot throughput and material validity before freezing that allocation.
- Check the node yourself for GLM-5.3. Use the installed checkpoint if present; otherwise download the pinned checkpoint. Do not ask the study owner to relay launch/configuration details. Record the artifact, precision and offload found on the node, and preserve a working installed deployment. Do not silently replace a full target with a distilled/smaller checkpoint or guess that four GPUs can hold native FP8 weights.
- Preserve all failed/missing assignments, raw responses, reasoning fields and provenance. Do not silently retry unknown-cost inference or condition selection on model misconduct.
- Do not claim that software checks establish LLM behaviour, STE adherence, deployment feasibility, or a neural mechanism.

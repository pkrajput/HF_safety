# Active no_ft branch experiment

For this branch, the user explicitly selected pretrained-only Llama 3.1 8B and optional Qwen3-30B-A3B-Base on one 80 GB GPU. Follow docs/BASE_MODEL_VAST.md and configs/base_models.json. These targets supersede the historical frontier-model allocation below for this experiment. No post-training, adapters, automatic model substitution, or competence-based selection. Keep original impossible-within-budget task, late owner update, and all failures. Push source only; preserve credentials and collected data outside Git.

# Study operation

Read docs/OPERATOR_HANDOFF.md and docs/CLUSTER.md before changing model selection or launching collection.

- Target full DeepSeek-R1-0528 and GLM-5.3; Qwen3.5-397B-A17B-FP8 is the proposed third family. Apertus-70B is the separate auxiliary auditor.
- Keep one model resident at a time. Run hundreds of isolated four-agent teams in bounded batches against that resident model; never count paired reports as independent swarms.
- The proposed main allocation is 384 fresh swarms per target, using 12 fixtures and the frontier budget profile. Pilot throughput and material validity before freezing that allocation.
- Check the node yourself for GLM-5.3. Use the installed checkpoint if present; otherwise download the pinned checkpoint. Do not ask the study owner to relay launch/configuration details. Record the artifact, precision and offload found on the node, and preserve a working installed deployment. Do not silently replace a full target with a distilled/smaller checkpoint or guess that four GPUs can hold native FP8 weights.
- Preserve all failed/missing assignments, raw responses, reasoning fields and provenance. Do not silently retry unknown-cost inference or condition selection on model misconduct.
- Do not claim that software checks establish LLM behaviour, STE adherence, deployment feasibility, or a neural mechanism.

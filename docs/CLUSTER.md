# Frontier-model cluster handoff

Revised 2026-11-06. Allocation assumption remains one node with four GPUs for 48–72 hours. The target choices now prioritize full checkpoints. Their deployment needs must be reconciled with the actual node before collection.

## Model roles and memory

| Key | Checkpoint | Role |
|---|---|---|
| `glm53` | `zai-org/GLM-5.3` | Target; owner reports an existing installation |
| `deepseek_r1` | `deepseek-ai/DeepSeek-R1-0528` | Full R1 target |
| `qwen_full` | `Qwen/Qwen3.5-397B-A17B-FP8` | Proposed third full-size target family |
| `apertus_auditor` | `swiss-ai/Apertus-70B-Instruct-2509` | Reserved auxiliary auditor; human review required |

Qwen is a proposed comparator, not a claim that it is the latest flagship. Do not replace a full target with Distill, Air, Flash or a smaller model to make a run start. The prior targets are archived in `configs/models.legacy.json` and are not the main campaign.

Four H200 GPUs have 564 GB nominal aggregate HBM. Published FP8 safetensor shards occupy about 688.6 GB for R1-0528 and 755.6 GB for GLM-5.3. These are file sizes, not a full runtime memory model, but they already exceed that capacity. GLM's official vLLM recipe uses eight H200s for native FP8. Sequential loading prevents models from competing for memory; it does not make one oversized checkpoint fit. [H200 specifications](https://www.nvidia.com/en-us/data-center/h200/), [R1 files](https://huggingface.co/deepseek-ai/DeepSeek-R1-0528/tree/main), [GLM serving recipe](https://recipes.vllm.ai/zai-org/GLM-5.3).

The operator checks for GLM-5.3 on the node and uses it if present, or downloads the pinned checkpoint if absent. Obtain launch details from the node rather than asking the study owner to relay them. Reuse the installed GLM deployment after recording its actual precision, quantized artifact if any, CPU offload, and server command. Check `nvidia-smi` and CPU architecture: the supplied CSCS GH200 link is not a description of a conventional H200 node. Host RAM is not additional HBM at the same speed. A four-GPU quantized/offloaded deployment may work, but its throughput and behaviour must be measured. Precision is part of the evaluated system.

## 1. Check the software without GPUs

```bash
git clone https://github.com/pkrajput/HF_safety.git
cd HF_safety
python3 -m unittest discover -s tests -v
python3 -m auditlab.cli plan --stage network_pilot --out manifests/network-pilot.json
python3 -m auditlab.cli run --models configs/models.json --model deepseek_r1 --mock --manifest manifests/network-pilot.json --out results/mock --workers 2
```

Python 3.11 or later is required. The harness uses the standard library. Mock output is not a model observation.

## 2. Record the actual deployment before the GPU window

`configs/models.lock.json` pins the reference artifacts by repository commit. No weights were downloaded during preparation. Preserve those pins rather than re-pinning automatically. For a deliberately changed artifact, use `pin` to create a new lock file and preserve its base checkpoint identity in the deployment record.

All three target configs initially have `deployment_status: requires_site_profile`. This means there is no validated four-GPU launch configuration in this repository. It does not mean the owner's installation is absent. Managed launch stops before loading an unprofiled target; attach to a working endpoint with an explicit deployment record instead.

Copy the lock file to a site configuration, then set the real served alias, context, precision, reasoning settings and request timeout. Preserve repository and revision as the base checkpoint identity when recording a derived installed artifact. Keep the site configuration fixed within a collection.

```bash
cp configs/models.lock.json configs/models.site.json
```

An installed endpoint needs a deployment JSON with these fields:

```json
{
  "base_repository": "zai-org/GLM-5.3",
  "base_revision": "<40-character base commit from your verified installation>",
  "precision": "<same exact precision description as models.site.json>",
  "artifact": {
    "repository": "<actual artifact repository>",
    "revision": "<40-character artifact commit>"
  },
  "offload": "<none, or the actual offload configuration>",
  "launch_command": "<actual server launch command>",
  "operator_verified": true
}
```

For locally converted weights, `artifact` can instead contain `local_manifest_sha256`, the SHA-256 of a retained manifest of the actual files and their checksums. Placeholders are not valid records. `operator_verified` records the colleague's verification; it cannot establish remote weight identity by itself. The wrapper binds the full deployment-record hash into episode identity so that a changed deployment cannot silently resume old results.

Use the site's working serving environment. For GH200, its image must support Arm; a conventional H200 host may be x86. Prefer an existing validated vLLM/SGLang installation to an untested reinstall. Record package versions, image digest, GPU details and the full launch command. The harness requires an OpenAI-compatible chat endpoint **and exact chat tokenization at `/tokenize`**. Chat compatibility alone is insufficient. An existing server with a different tokenization API needs a validated adapter before collection; do not estimate token counts.

For new weight downloads, run on a permitted transfer service before the allocation:

```bash
python3 scripts/download_models.py --models configs/models.lock.json --root /absolute/scratch/models --only deepseek_r1
```

For GLM, first inspect the running server, model directories and local Hugging Face cache. If it is absent:

```bash
python3 scripts/download_models.py --models configs/models.lock.json --root /absolute/scratch/models --only glm53
```

Avoid downloading GLM again when its verified weights already exist. The operator or executing agent prepares the deployment record from this inspection; the study owner does not need to supply it or approve it separately. Allow storage based on the chosen artifacts; the former 1 TB allowance for all models is no longer appropriate.

## 3. Pilot the existing GLM server first

Configure its alias to match `served_name` in the site config. The preflight checks that alias, token accounting and a complete JSON answer. The name reported by `/v1/models` is not proof of the weights; use the deployment record as well.

```bash
python3 -m auditlab.cli plan --stage network_pilot --team-sizes 4 --budget-profile frontier --out manifests/frontier-pilot.json
python3 scripts/serve_and_run.py --models configs/models.site.json --model glm53 --endpoint http://127.0.0.1:8000 --deployment-record /absolute/path/glm53-deployment.json --manifest manifests/frontier-pilot.json --results results/frontier-pilot --workers 2 --limit 4 --wall-seconds 3600
```

The wrapper attaches without starting or stopping the existing server. A `--limit 4` run is an engineering check only; it does not cover the full pilot. Run all pilot conditions before freezing the design. The explicit four-agent pilot preserves all policy, guard, pressure and language controls.

The frontier profile allows 8,192 generated tokens per action and per report, counting reasoning and final output together. Its phase-1 generation allowance is 131,072 tokens and continuation allowance is 196,608 tokens. These are initial caps, not an assertion that every model needs that much or can finish under them. Review truncation, incomplete answers, task success and context exhaustion. Change the profile before confirmation if it clips reasoning. Do not disable reasoning to improve throughput without treating that as a different configuration.

Raw `reasoning`/`reasoning_content` fields remain in response journals; action parsing uses final content. Chat-template handling of previous reasoning is part of the model configuration. The default 65,536-token serving context also needs a pilot. An input-ID match is necessary for replay, but does not prove numerical equivalence across engines.

## 4. Generate hundreds of swarm runs

After capability, language and throughput checks, create balanced manifests:

```bash
for stage in ste duration network_stress network_repair
do
  python3 -m auditlab.cli plan --stage "$stage" --fixtures 12 --team-sizes 4 --repetitions 1 --budget-profile frontier --out "manifests/frontier-$stage.json"
done
python3 -m auditlab.cli estimate --manifest manifests/frontier-ste.json --model-count 3
```

| Stage | Fresh swarms per target | Paired reports per target |
|---|---:|---:|
| STE | 216 | 648 |
| Duration | 24 | 648 |
| Poisoned stress | 96 | 576 |
| Guardrail repair | 48 | 144 |
| Total | 384 | 2,016 |

Three targets therefore receive 1,152 fresh four-agent swarms and 6,048 paired reports. The main runs initialize 4,608 agent contexts. These are planned counts, not completed observations. Current fixtures only permute relay labels; do not describe the count as independent task topologies.

`--workers 2` means two concurrent swarms sharing one loaded model. `--team-sizes 4` means four separate agent contexts within each team. Agents currently take turns. Hundreds of swarms run as queued batches, not hundreds of weight copies. Add solo controls using separate manifests with `--team-sizes 1`, and budget/count them separately. Repetitions change sampling seeds; they do not create new linguistic or network structures.

If measured throughput requires a smaller balanced campaign, eight fixtures give 256 swarms per target. Choose the number prospectively. The 48–72-hour allocation does not guarantee either count; include model loading, prompt processing, reasoning, reports, audits and failures in profiling. Do not stop collection selectively after interesting cases.

## 5. Finish one model before the next

For the already running GLM endpoint:

```bash
python3 scripts/serve_and_run.py --models configs/models.site.json --model glm53 --endpoint http://127.0.0.1:8000 --deployment-record /absolute/path/glm53-deployment.json --manifests manifests/frontier-ste.json manifests/frontier-duration.json manifests/frontier-network_stress.json manifests/frontier-network_repair.json --results results/frontier --workers 2 --wall-seconds 28800
```

`--manifests` keeps the same model resident while running the stages in order. Outputs use `results/frontier/<stage>/<model-id>/`. The wall allowance is shared across these stages. Safe-boundary pauses and missing observations are preserved. Review stage completion before proceeding; rerun unchanged configurations to resume. Remaining stage assignments can be summarized once their manifests/model registrations exist.

After GLM's selected collection, the operator stops that externally managed server. Load the full R1 deployment, run the same manifests, stop it, then run the proposed third family. Do not leave the old externally managed server resident when loading another model.

For a validated managed vLLM profile, set `deployment_status` to `site_validated`, record all launch/offload options in `serve_extra`, and provide `local_snapshot_path` or the standard model-root layout. The snapshot's `auditlab_snapshot.json` must match repository, revision and precision. This is a record of a verified installation, not a way to relabel unknown weights.

```bash
python3 scripts/serve_and_run.py --models configs/models.site.json --model deepseek_r1 --model-root /absolute/scratch/models --manifests manifests/frontier-ste.json manifests/frontier-duration.json manifests/frontier-network_stress.json manifests/frontier-network_repair.json --results results/frontier --workers 2 --wall-seconds 28800
```

Managed mode waits for and then stops its own server. It rejects obvious all-GPU memory shortfalls before starting when local safetensor sizes and GPU memory are available. Passing this coarse check is not a fit guarantee. It does not select quantization, add offload, or substitute a different model automatically.

For CSCS Slurm, `scripts/run_cscs.sbatch` accepts `AUDITLAB_MODELS`, `AUDITLAB_MODEL`, `AUDITLAB_RESULTS`, `AUDITLAB_MANIFEST`, and optional `AUDITLAB_ENDPOINT`/`AUDITLAB_DEPLOYMENT_RECORD`. Managed mode also needs `AUDITLAB_MODEL_ROOT`. Set the actual account, partition, EDF/container and interpreter paths. The four-GPU request is an allocation placeholder, not proof that native FP8 fits.

## 6. Audit and preserve the collection

Run Apertus only after unloading the target, with `--mode audit`. Its family is distinct from every target. Human review must include condition-balanced negatives as well as flagged reports. Auditor failure or disagreement is not ground truth.

```bash
python3 scripts/serve_and_run.py --models configs/models.site.json --model apertus_auditor --model-root /absolute/scratch/models --mode audit --results results/frontier/duration --out results/audit-duration --limit 200
python3 -m auditlab.cli verify --results results/frontier/duration
python3 -m auditlab.cli analyze --results results/frontier/duration --out results/frontier-duration-summary.json
python3 -m auditlab.cli replay-index --results results/frontier/duration --out artifacts/frontier-replay-index.json
```

Retain logs, raw responses, failures, source/manifest hashes, model and deployment identities, and serving-time token IDs. Back up outside scratch. Do not commit weights or generated trajectories to the source repo. A stale writer lock or unresolved remote request needs inspection; no automatic retry is allowed when outcome/cost is unknown.

The generic Transformers activation-capture script is disabled for these configurations until `capture_supported` is explicitly validated. It must not expand a quantized frontier model into BF16 and hope that it fits. A faithful frontier replay/intervention adapter remains separate work. Reserve node time for that validation rather than spending the entire window on trajectories.

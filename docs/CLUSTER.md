# One-node handoff

Allocation assumption: one node, four GPUs, available for roughly 48–72 hours. That is 192–288 allocated GPU-hours before setup overhead. This is an allocation budget, not a throughput measurement.

The supplied CSCS link describes four Grace-Hopper modules per GH200 node. The owner also mentioned H200 GPUs. Do not treat these as identical. GH200 has a Grace Arm CPU; a standalone H200 node may use an x86 CPU and different GPU memory. Determine the actual hardware before selecting an image or estimating model capacity.

## 1. Get the package and check it without GPUs

```bash
git clone https://github.com/pkrajput/HF_safety.git
cd HF_safety
python3 --version
python3 -m unittest discover -s tests -v
python3 -m auditlab.cli plan --stage network_pilot --out manifests/network-pilot.json
python3 -m auditlab.cli run --models configs/models.json --model qwen --mock --manifest manifests/network-pilot.json --out results/mock
```

Python must be 3.11 or later. The harness itself uses only the standard library. No credentials or paid endpoint are required for this smoke test. Keep mock results separate from all real results.

## 2. Establish the serving environment

Prefer your site's existing working vLLM environment or an administrator-provided container. Check its CPU architecture and GPU support. Do not use an x86-only image on a GH200 Arm node.

On CSCS, Container Engine supports `srun --environment=<EDF-name> ...`. Create an EDF from the site's working image and mount the project, model cache, and result directories. A structural example follows; replace every placeholder with a real path/image available to the allocation.

```toml
image = "<site-validated-vllm-image-for-this-architecture>"
mounts = ["<absolute-project-root>:<absolute-project-root>", "<absolute-scratch-root>:<absolute-scratch-root>"]
workdir = "<absolute-project-root>/HF_safety"
```

Save the EDF in the location used by your CSCS account, commonly `$HOME/.edf/`. Record the immutable image digest in `AUDITLAB_IMAGE_DIGEST`. The repository does not pretend to supply a validated CSCS image; it must be chosen for the actual node.

For a conventional H200 node with a compatible Python/CUDA stack, an isolated environment is another option:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install vllm huggingface_hub
.venv/bin/python -m pip install -e .
```

This installs the current packages and is a bootstrap procedure, not a reproducible version lock. Once the server passes its pilot, save `pip freeze`, the image digest if used, CUDA/driver details, and the launch command. Keep those versions unchanged for confirmation. Optional replay capture additionally needs Transformers, PyTorch, Accelerate, and Safetensors compatible with the chosen checkpoints. Do not replace a working site environment merely to follow this example.

## 3. Pin weights and prepare storage before the GPU window

```bash
python3 -m auditlab.cli pin --models configs/models.json --out configs/models.lock.json
```

This makes small metadata requests and pins exact repository commits. It does not download weights. Keep the resulting lock file with the paper artifacts. Re-pinning later creates a different experimental configuration.

Allow approximately 1 TB of scratch capacity for these four unquantized model snapshots plus room for logs and activations. This is a conservative storage planning allowance, not a measured download size. The candidate models' approximate BF16 weight sizes are 64 GB (Qwen), 140 GB (Apertus), 48 GB (Mistral), and over 200 GB (GLM-Air), before framework/KV overhead. The full GLM-4.5 is much larger than GLM-4.5-Air and is not interchangeable with it.

Set task-specific paths rather than repurposing system variables:

```bash
export AUDITLAB_ROOT=/absolute/path/HF_safety
export AUDITLAB_MODEL_ROOT=/absolute/scratch/path/audit-models
python3 scripts/download_models.py --root "$AUDITLAB_MODEL_ROOT"
```

Download only selected models with `--only qwen apertus mistral` or `--only glm_auditor`. Do downloads on a permitted transfer/login service before the allocation where possible. Check site policy and network availability. Do not put an access token in a script or Git; use the Hugging Face client's normal local authentication if required.

### Existing local weights

Check the installed checkpoint's repository, exact commit, dtype and tokenizer. The expected layout is:

```text
<AUDITLAB_MODEL_ROOT>/<model-id>/<40-character-revision>/config.json
<AUDITLAB_MODEL_ROOT>/<model-id>/<40-character-revision>/...weight files...
<AUDITLAB_MODEL_ROOT>/<model-id>/<40-character-revision>/auditlab_snapshot.json
```

You can symlink that revision directory to an already complete snapshot. The `auditlab_snapshot.json` file must contain the corresponding configuration object from `configs/models.lock.json`. Create it only after independently confirming the installed revision; the file is a provenance record, not a way to make unknown weights correct. If the installed GLM is another release, edit `configs/models.json`, pin it, and calibrate that release. The auditor family must remain distinct from the targets.

## 4. Pilot one model inside the allocation

The wrapper starts a local-only inference server and the harness in the same job. Tensor parallelism defaults to four GPUs for all models to avoid model-specific resource assumptions initially. It can be reduced after profiling, before freezing. Inference runs one family at a time.

```bash
python3 scripts/collect_hardware.py artifacts/hardware.json
python3 scripts/serve_and_run.py --model qwen --model-root "$AUDITLAB_MODEL_ROOT" --manifest manifests/network-pilot.json --results results/pilot --workers 2 --limit 4 --wall-seconds 3600
```

Start with low concurrency, then test 4 or 8 independent episodes after measuring memory and prefill load. Concurrency is serving throughput; the `agents` field is the number of experimental agents in one team. They are different concepts.

The wrapper records GPU names/memory, architecture, package versions, launch parameters, server logs, and model identity. It verifies `/health`, `/tokenize`, and chat completion. Its memory setting starts at 0.85 and context length at 16,384. It does not silently quantize, truncate histories, or reduce model size. If a model does not load, retain the failure log and change the engineering configuration before generating a new manifest.

Before the main runs, verify:

1. JSON format works without a substantial invalid/truncation rate.
2. Each model can solve the public task and discover the authorised reference path.
3. Output-language instructions are understood and do not merely suppress useful output.
4. The vulnerable and hardened environments have the expected action-level behaviour.
5. Measured total node throughput, including prompt processing, supports the chosen collection size.

The temperature/template settings need not be numerically identical across model families; preserve recommended stable settings and report them. Within each model, keep them fixed across treatments. The default Qwen configuration turns off its explicit thinking mode. If choosing thinking mode, give it an adequate per-call budget and treat it as a distinct configuration.

## 5. Submit through Slurm

Use the account and partition actually granted to your colleague. The script intentionally does not invent them. Check the queue's time, CPU, and GPU request conventions; `#SBATCH` settings are starting values and can be overridden on submission.

```bash
mkdir -p logs
export AUDITLAB_ROOT=/absolute/path/HF_safety
export AUDITLAB_MODEL_ROOT=/absolute/scratch/path/audit-models
export AUDITLAB_MODEL=qwen
export AUDITLAB_MANIFEST=manifests/network-pilot.json
export AUDITLAB_RESULTS=/absolute/scratch/path/audit-results/pilot
export AUDITLAB_WORKERS=4
export AUDITLAB_MODE=run
export AUDITLAB_EDF=<your-working-edf-name>
sbatch --account=<your-allocation> --partition=<your-gpu-partition> scripts/run_cscs.sbatch
```

On a conventional environment without CSCS Container Engine, leave `AUDITLAB_EDF` unset and set `AUDITLAB_PYTHON` to the environment's absolute Python executable. The standard Slurm path uses `srun` without `--environment`. Do not set both paths unnecessarily. The wrapper's `vllm` executable must be on that environment's `PATH`.

The example job limit is 8 hours, with a 6-hour request-start budget. Model loading and shutdown need headroom. Submit sequential chunks or use the site's allowed longer duration. An interrupted in-flight request is preserved as unresolved and will not be silently repeated. A stale `writer.lock` must be inspected against running jobs before removal.

## 6. Freeze and collect

After the pilot and material review, choose the confirmatory sample size and save it in the protocol. Regenerate manifests after the last code change because they include the source hash.

```bash
python3 -m auditlab.cli plan --stage ste --fixtures 6 --out manifests/ste.json
python3 -m auditlab.cli plan --stage duration --fixtures 6 --out manifests/duration.json
python3 -m auditlab.cli plan --stage network_stress --fixtures 6 --out manifests/network-stress.json
python3 -m auditlab.cli plan --stage network_repair --fixtures 6 --out manifests/network-repair.json
python3 -m auditlab.cli estimate --manifest manifests/duration.json
```

Run the same frozen manifests for qwen, apertus and mistral. Use separate output roots for each stage. Within a stage, model IDs have separate subdirectories. Keep all condition cells for the selected task fixtures; do not stop after a promising set of failures. The CLI's `--limit` is for engineering pilots, not a substitute for balanced confirmatory sampling.

For inexpensive scope probes while each target is resident:

```bash
python3 -m auditlab.cli semantic --model qwen --endpoint http://127.0.0.1:8000 --out results/semantic/qwen --fixtures 3
```

Here `fixtures` controls sampling repetitions of the finite probe bank. It is not the number of independent language templates. The wrapper also accepts `--mode semantic`.

## 7. Use GLM as the auditor

When GLM is resident, use `--mode audit` in the wrapper or the following command against its endpoint:

```bash
python3 -m auditlab.cli audit --model glm_auditor --results results/duration --out results/audit-duration --limit 200
python3 -m auditlab.cli propose --model glm_auditor --out artifacts/development-proposal.json
```

Annotation cost is separate from target inference. Select a condition-balanced sample and verify labels with humans; the default file ordering is an engineering convenience, not a valid sampling scheme for estimating prevalence. The development proposal is saved for review and never changes a confirmatory case. This is not a complete implementation of adaptive auditor RL.

## 8. Preserve the data needed after the allocation

```bash
python3 -m auditlab.cli verify --results results/duration
python3 -m auditlab.cli analyze --results results/duration --out results/duration-summary.json
python3 -m auditlab.cli replay-index --results results/duration --out artifacts/replay-index.json
```

Retain full raw results, completed and failed episodes, hashes, scripts, server environment, and model snapshot locations. Store a backup outside ephemeral scratch. Do not put weights, credentials, or large generated trajectories into the source Git repository. Archive data separately with a manifest.

For a small optional activation capture while GPUs remain available:

```bash
python3 scripts/capture_replay.py --index artifacts/replay-index.json --model qwen --model-root "$AUDITLAB_MODEL_ROOT" --out artifacts/replay-qwen --limit 24
```

Stop the serving model before loading a second model for capture. The script saves full input token IDs, a few reporting-boundary hidden states, and next-token logits/entropy. It is deliberately limited and has not been run on these GPUs. Validate exact chat-template rendering and token/logit agreement with the serving engine. Mistral's native rendering needs its own validated adapter. The capture script now requires exact serving-time token IDs and refuses absent or mismatched IDs. Matching input IDs still does not prove numerical equivalence across inference engines.

Selected boundary states may miss the causal representation. They do not replace planned intervention runs or full replay access. Reserve actual GPU time for mechanistic discovery and counterfactual tests, even if that means collecting fewer secondary trajectories.

## Suggested time allocation

For a 48-hour window, a starting plan is 4 hours for load/pilot checks, 24 hours for target trajectories and probes, 6 hours for secondary controls, 4 hours for GLM auditing, 6 hours for mechanistic replay, and 4 hours for failures and backup. These are scheduling proposals. For 72 hours, expand independent fixtures and mechanistic tests after profiling rather than increasing all factorial dimensions.

Use measured campaign wall time to revise this plan before confirmation. Do not promise that the entire default suite fits the allocation. Each network design has a finite token upper bound; actual runtime depends heavily on model, prompt lengths, stop behaviour, serving software and concurrency.

## Network-v2 collection details

The runner recognises network-v2 manifests automatically; the server/Slurm launch commands do not change. Use separate result roots for `ste`, `duration`, `network_stress`, and `network_repair`. The old `core`/`compute` names still run legacy arithmetic fixtures and are not the revised main study.

For duration, each checkpoint creates 0/8/24-opportunity continuation branches. Each receives fresh fair missions and keeps its conversations. Reports always concern the closed phase-1 period. The original phase-1 ledger is given once before branching, and the ledger-reminder condition repeats it later. Reporting is independent of unused task budget.

The stress stage includes all four solvability-by-pressure cells. Blocked and poisoned cases cannot obtain a required receipt through any available action. They remain separate from fair tasks in the analyzer. No truthful blocked response is removed.

Before confirmation, test whether 24-opportunity continuations fit the selected model context length. Context exhaustion is retained as missing data, never as honesty. If limits are unsuitable, adjust the configuration before freezing and regenerate manifests. The default 16k context and generation settings are engineering starting points.

The result skeleton records every assigned report before collection. A later branch failure cannot delete earlier observations. Registered model configs under `results/<stage>/models/` let the analyzer count unstarted cases in the manifest. A collection interrupted at a safe request boundary can resume using the same command and code. Pending remote requests are never automatically regenerated. Request artifacts and checkpoints are bound to the observer journal.

The default full stage counts per target are 28 pilot checkpoints, 216 STE checkpoints, 24 duration checkpoints, 96 stress checkpoints, and 48 repair checkpoints. These are not all independent task templates: the initial network template currently varies only relay labels. Sample size and broader task variation require research review.

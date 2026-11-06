#!/bin/bash
#SBATCH --job-name=audit-scope
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gpus-per-task=4
#SBATCH --cpus-per-task=72
#SBATCH --time=08:00:00
#SBATCH --output=logs/%x-%j.out
#SBATCH --error=logs/%x-%j.err

set -euo pipefail
: "${AUDITLAB_ROOT:?Set the absolute repository path}"
: "${AUDITLAB_MODEL_ROOT:?Set the model snapshot root}"
: "${AUDITLAB_MODEL:?Choose qwen, apertus, mistral, or glm_auditor}"
: "${AUDITLAB_RESULTS:?Set an output directory}"
cd "$AUDITLAB_ROOT"
args=(scripts/serve_and_run.py --model "$AUDITLAB_MODEL" --model-root "$AUDITLAB_MODEL_ROOT"
      --results "$AUDITLAB_RESULTS" --mode "${AUDITLAB_MODE:-run}"
      --wall-seconds "${AUDITLAB_WALL_SECONDS:-21600}" --workers "${AUDITLAB_WORKERS:-4}")
if [[ "${AUDITLAB_MODE:-run}" == "run" ]]; then
    : "${AUDITLAB_MANIFEST:?Set the manifest path}"
    args+=(--manifest "$AUDITLAB_MANIFEST")
fi
if [[ -n "${AUDITLAB_LIMIT:-}" ]]; then args+=(--limit "$AUDITLAB_LIMIT"); fi
if [[ -n "${AUDITLAB_EDF:-}" ]]; then
    srun --environment="$AUDITLAB_EDF" python3 "${args[@]}"
else
    srun "${AUDITLAB_PYTHON:-python3}" "${args[@]}"
fi

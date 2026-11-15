#!/usr/bin/env bash
# Run inside tmux/supervisor. One resident model; archive results before exit.
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv-base/bin/activate
base_model_key="${1:-llama8b}"
base_run_root="${2:-results/base-${base_model_key}-v1}"
base_deployment_root="results/deployment-${base_model_key}"
if curl --silent --fail --max-time 3 http://127.0.0.1:8000/health >/dev/null; then
  echo 'Port 8000 already serves a model. Stop it deliberately before this wrapper.' >&2
  exit 1
fi
python -m base_prime.host prepare --model "$base_model_key" --record-dir "$base_deployment_root"
python -m base_prime.host serve --model "$base_model_key" --record-dir "$base_deployment_root" >> "$base_deployment_root/server.log" 2>&1 &
base_server_pid=$!
trap 'kill -TERM "$base_server_pid" 2>/dev/null || true; wait "$base_server_pid" 2>/dev/null || true' EXIT
base_server_ready=0
for base_wait_step in $(seq 1 180); do
  if ! kill -0 "$base_server_pid" 2>/dev/null; then
    echo "Server stopped. Inspect $base_deployment_root/server.log" >&2
    exit 1
  fi
  if curl --silent --fail --max-time 3 http://127.0.0.1:8000/health >/dev/null; then
    base_server_ready=1
    break
  fi
  sleep 2
done
if [[ "$base_server_ready" != 1 ]]; then
  echo 'Server did not become ready within six minutes.' >&2
  exit 1
fi
if [[ ! -f "$base_run_root/manifest.json" ]]; then
  python -m base_prime.run plan --model "$base_model_key" --out "$base_run_root"
fi
python -m base_prime.run run --out "$base_run_root" --deployment "$base_deployment_root/deployment.json" \
  --workers 2 --wall-seconds 3600 2>&1 | tee -a "$base_run_root/collection.log"
python -m base_prime.run analyze --out "$base_run_root"
tar -czf "${base_run_root}.tar.gz" "$base_run_root" "$base_deployment_root"
printf '%s\n' 'QUEUE_PROCESSED: inspect summary.json for failures and missing cases.' > "$base_run_root/QUEUE_PROCESSED.txt"
echo "Archive ready at ${base_run_root}.tar.gz; copy it off this instance before deletion."

#!/usr/bin/env python3
"""Run inside the allocation and the selected serving environment."""
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
from pathlib import Path


def command(args):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=30)
        return {'returncode': p.returncode, 'stdout': p.stdout, 'stderr': p.stderr}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'error': str(exc)}


out = Path(sys.argv[1] if len(sys.argv)>1 else 'artifacts/hardware.json')
out.parent.mkdir(parents=True, exist_ok=True)
packages = {}
for name in ('torch', 'transformers', 'vllm', 'huggingface-hub', 'mistral-common', 'safetensors'):
    try:
        packages[name] = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        packages[name] = None
info = {'machine': platform.machine(), 'platform': platform.platform(), 'python': sys.version,
        'packages': packages, 'gpu': command(['nvidia-smi', '--query-gpu=name,memory.total,uuid,driver_version',
                                             '--format=csv']),
        'topology': command(['nvidia-smi', 'topo', '-m']),
        'slurm': {k: os.environ.get(k) for k in ('SLURM_JOB_ID', 'SLURM_JOB_NODELIST',
                   'SLURM_JOB_ACCOUNT', 'SLURM_JOB_PARTITION', 'SLURM_CPUS_PER_TASK')},
        'container_image': os.environ.get('AUDITLAB_IMAGE_DIGEST', 'NOT_RECORDED')}
out.write_text(json.dumps(info, indent=2)+'\n')
print(json.dumps(info, indent=2))

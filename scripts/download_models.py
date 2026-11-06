#!/usr/bin/env python3
"""Optional weight download. Run where large downloads are permitted, before GPU allocation."""
import argparse
import json
import re
from pathlib import Path

from huggingface_hub import snapshot_download

parser = argparse.ArgumentParser()
parser.add_argument('--models', default='configs/models.lock.json')
parser.add_argument('--root', required=True)
parser.add_argument('--only', nargs='*')
args = parser.parse_args()
models = json.loads(Path(args.models).read_text())
for name, config in models.items():
    if args.only and name not in args.only:
        continue
    if not re.fullmatch('[a-f0-9]{40}', config['revision']):
        raise ValueError('Pin revisions first')
    dest = Path(args.root)/name/config['revision']
    snapshot_download(repo_id=config['repository'], revision=config['revision'], local_dir=dest,
                      ignore_patterns=['*.gguf', '*.bin', '*.onnx', '*.pt', '*.pth'])
    (dest/'auditlab_snapshot.json').write_text(json.dumps(config, indent=2)+'\n')
    print(name, dest)

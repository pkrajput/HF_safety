import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from .protocol import encode

ROOT = Path(__file__).resolve().parents[1]


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w') as f:
        json.dump(value, f, indent=2, ensure_ascii=False)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    temporary.replace(path)


def config():
    return read(ROOT / 'configs/base_models.json')


def sources():
    paths = sorted((ROOT / 'base_prime').glob('*.py')) + sorted((ROOT / 'local_prime').glob('*.py'))
    paths += [ROOT / 'configs/base_models.json', ROOT / 'local_prime/fixtures.json',
              ROOT / 'requirements/base-gpu.txt', ROOT / 'scripts/setup_base_gpu.sh',
              ROOT / 'scripts/run_base_node.sh']
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}

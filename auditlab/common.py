import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f".{os.getpid()}.tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    temp.replace(path)


def source_hash():
    root = Path(__file__).resolve().parent
    return digest({str(p.relative_to(root)): p.read_text() for p in sorted(root.glob('*.py'))})


class Journal:
    """Hash-linked observer log; integrity is relative to a separately retained root.

    Hash chaining is not protection against a host administrator rewriting the log.
    The model cannot access this host file through its virtual tools.
    """
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.previous = "0" * 64
        if self.path.exists():
            rows = self.verify(self.path)
            self.previous = rows[-1]['hash'] if rows else self.previous

    def append(self, kind, data):
        row = {'time': now(), 'kind': kind, 'previous': self.previous, 'data': data}
        row['hash'] = digest(row)
        with self.path.open('a') as stream:
            stream.write(canonical(row) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        self.previous = row['hash']

    @staticmethod
    def verify(path):
        previous, rows = "0" * 64, []
        for line in Path(path).read_text().splitlines():
            row = json.loads(line)
            claimed = row.pop('hash')
            if row['previous'] != previous or digest(row) != claimed:
                raise ValueError('Observer journal integrity check failed')
            row['hash'] = claimed
            rows.append(row)
            previous = claimed
        return rows

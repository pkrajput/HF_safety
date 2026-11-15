#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11+ required"'
python3 -m venv .venv-base
.venv-base/bin/python -m pip install --upgrade pip
.venv-base/bin/python -m pip install -r requirements/base-gpu.txt
.venv-base/bin/python -m unittest discover -s tests -p 'test_base_prime.py' -v

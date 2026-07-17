#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

python_bin="${PYTHON_BIN:-python3.12}"
if ! command -v "$python_bin" >/dev/null 2>&1; then
  python_bin="python3"
fi

if test ! -d .venv; then
  "$python_bin" -m venv .venv
fi

. .venv/bin/activate
python -m pip install --upgrade pip
if test -f requirements-dev.lock; then
  python -m pip install --require-hashes -r requirements-dev.lock
  python -m pip install --no-deps --no-build-isolation -e .
else
  python -m pip install -e '.[dev]'
fi

if test ! -d .git; then
  git init
  git add .
  git commit -m "chore: import codex-ready han alpha baseline"
fi

./scripts/preflight.sh
./scripts/verify_all.sh

cat <<'MSG'

Codex handoff is ready.
Open this folder in the Codex desktop app and paste:
  docs/codex/CODEX_PROMPT_ZH.md

For a stopped task use:
  docs/codex/CODEX_RESUME_PROMPT_ZH.md
MSG

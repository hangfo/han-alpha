#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

python --version
python -m pip --version

required=(README.md AGENTS.md CODEX_START_HERE.md pyproject.toml docs/codex/ACCEPTANCE_CRITERIA.md)
for path in "${required[@]}"; do
  test -f "$path" || { echo "missing required file: $path" >&2; exit 1; }
done

if grep -RInE '(API_KEY|TOKEN|PASSWORD|SECRET)[[:space:]]*=[[:space:]]*[^[:space:]#]{8,}' . \
  --exclude-dir=.git --exclude-dir=.venv --exclude-dir=node_modules --exclude-dir=dist \
  --exclude='.env.example' --exclude='*.md'; then
  echo "possible embedded secret found" >&2
  exit 1
fi

python -m compileall -q src
printf 'preflight: OK\n'

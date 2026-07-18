#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

ruff check src tests
mypy src
pytest --cov=hanalpha --cov-branch --cov-report=term-missing --cov-fail-under=85
python -m build --no-isolation
hanalpha doctor
hanalpha demo --cycles 3
hanalpha backtest --symbol NVDA --bars 400

if test -f web/package.json; then
  (cd web && npm ci && npm run lint && npm run typecheck && npm test -- --run && npm run build)
fi

printf 'verify_all: OK\n'

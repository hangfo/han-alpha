# Han Alpha operations runbook

## Start and verify

```bash
source .venv/bin/activate
./scripts/preflight.sh
./scripts/verify_all.sh
uvicorn hanalpha.api.main:app --host 127.0.0.1 --port 8000
```

In another shell:

```bash
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/ready
curl -fsS http://127.0.0.1:8000/ready/service
curl -fsS http://127.0.0.1:8000/ready/observer
curl -fsS http://127.0.0.1:8000/ready/paper-canary
curl -fsS http://127.0.0.1:8000/ops/overview
curl -fsS http://127.0.0.1:8000/metrics
```

`/health` proves only that the API process is alive. `/ready` uses the strict Paper Canary gate; the three scoped endpoints distinguish service, Observer and Canary readiness. Never route execution traffic based only on liveness or API response freshness.

For the dashboard:

```bash
cd web
npm ci
npm run dev
```

The UI is read-only. It intentionally reports unavailable/empty/stale states and does not estimate missing Broker P&L.

## IBKR Paper observation

No order is sent by this command:

```bash
HANALPHA_ENV=paper hanalpha ibkr-observe \
  --state .state/ibkr-observer.sqlite3 \
  --control .state/execution-control.sqlite3 \
  --snapshots 2 --timeout 15
```

Prerequisites: official TWS API, Paper login, explicit allowlisted account, API read-only mode. Real connection/burn-in remains an external acceptance task.

## Backup

Choose a new, timestamped destination. Never point it at the source directory.

```bash
python scripts/backup_state.py \
  --source .state/ledger.sqlite3 \
  --source .state/execution-control.sqlite3 \
  --source .state/ibkr-observer.sqlite3 \
  --destination backups/han-alpha-YYYYMMDDTHHMMSSZ
```

The command uses SQLite online backup, runs `integrity_check`, and writes a cross-store SHA-256 manifest. Source databases must have unique names. Quiesce writers, or use an application-coordinated epoch, when a cross-database point-in-time snapshot is required.

## Restore drill

Stop all Han Alpha writers first. Restore to a new drill directory before considering an overwrite:

```bash
python scripts/restore_state.py \
  --manifest backups/han-alpha-YYYYMMDDTHHMMSSZ/manifest.json \
  --destination .state/restore-drill
```

Restore writes `generations/<generation_id>`, fsyncs every file and directory, then atomically switches `CURRENT`. Run `PRAGMA integrity_check`, start every service from the resolved `CURRENT` generation, and require startup reconciliation. `--overwrite` is reserved for an explicitly approved generation switch after independent backup verification.

## Restart and upgrade

1. Freeze new risk and confirm the durable freeze ticket.
2. Drain the execution writer; uncertain claimed commands must become Unknown.
3. Stop API/worker, create a verified backup, then upgrade.
4. Start in frozen state. Do not manually clear startup reconciliation.
5. Capture two semantically identical Broker snapshots separated in time.
6. Resume only when reconciliation converges and no other blocking ticket remains.

## Incident priorities

- Any broker-only order, unexplained cash bridge, Unknown submit/cancel or naked exposure: freeze new risk immediately.
- Cancel is risk-reducing and remains claimable while new risk is frozen.
- Never retry an uncertain submission until a complete, later Broker snapshot proves absence.
- Preserve the fact tape, control database, logs and manifest; do not edit economic events in place.

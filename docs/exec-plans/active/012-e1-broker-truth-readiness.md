# E1 execution plan: Broker Truth Readiness

Status: LOCAL TOOLING COMPLETE; authenticated Paper evidence BLOCKED
Owner: Codex and operator
Started: 2026-07-26

## Objective

Establish that an official IBKR Paper session can produce complete, independently
replayable and scope-explicit Broker facts without giving Han Alpha any write
capability.

## Implemented local entry slice

- `hanalpha ibkr-preflight` creates a redacted immutable environment artifact.
- `ibkr-observe` and `ibkr-burn-in` accept `--completed-orders-scope api|all`.
- Every completed session exports its own tape, certificate and canonical manifest.
- Session manifests bind commit, config, account hash, client, Paper port,
  normalization policy, Scope Policy, fact-delivery counters and reconciliation.
- Burn-in Ops counts are restricted to the current Scope.
- Arm expiry propagates the earliest upstream evidence deadline and Claim rechecks
  the current Authority and quote evidence.
- Safety Case Booleans are not trusted; integrity, signature, validity, revocation,
  current Scope and evidence hashes must verify.

## External sequence

1. Install matching official stable TWS/IB Gateway and TWS API.
2. Set Paper account, port, client ID and base currency locally.
3. Keep API Read-Only enabled and record the operator attestation.
4. Pass `ibkr-preflight`.
5. Run 30 `api` Scope observations on a controlled Paper account.
6. Run at least 10 `all` Scope observations including manual TWS orders.
7. Capture restart, nightly-reset, late-commission, correction, partial-fill,
   cancel and Bracket tapes.
8. Replay callback permutation/duplication/delay cases deterministically.

## Exit gate

- complete observations at preregistered thresholds for the current Scope;
- accepted facts equal written facts, with zero drops and zero writer errors;
- API/manual Completed Orders visibility demonstrated separately;
- at least one process restart, two TWS/Gateway restarts and one nightly reset;
- Golden Tape corpus passes order-independent replay;
- no Broker write was available to the observation process.

Until this gate passes, E2 and every real Writer remain BLOCKED.

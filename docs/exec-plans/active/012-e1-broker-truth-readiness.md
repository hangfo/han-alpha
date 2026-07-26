# E1 execution plan: Broker Truth Readiness

Status: E1-A COMPLETE; E1-B AUTHENTICATED EMPTY-ACCOUNT SLICE VERIFIED, MATRIX BLOCKED
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
- Session Manifest v2 self-verifies its canonical ID, Tape, Certificate and all
  Broker/Scope bindings; incomplete captures are retained but ineligible.
- Artifact Registry/Resolver checks existence, hash, type, schema and policy.
- `ibkr-burn-in-evaluate` emits a homogeneous Corpus and exits 2 unless its
  Scope-specific session and scenario matrix passes.
- Runtime holds Ed25519 public keys only; Risk and Execution reviewer receipts
  must be independent and bind the exact Safety Case.
- The Observer uses a dedicated client that rejects `placeOrder`, `cancelOrder`,
  `reqGlobalCancel` and `exerciseOptions`, even if TWS Read-Only must be disabled
  for the separately attested ALL-Scope order-visibility phase.
- Preflight and Session Manifests register automatically. Golden Tape evaluation
  executes metamorphic callback transforms and emits a machine-readable Callback
  Truth Map plus a content-addressed corpus.
- Ops and the read-only Dashboard use Artifact Registry and Corpus evidence rather
  than hard-coded restart/Golden Tape counters.
- `hanalpha local-onboard ibkr` reports exact installation/account/socket gates
  without exposing account identifiers, polls only a bounded local socket and
  registers Preflight after explicit Read-Only attestation. `hanalpha e1 run`
  resumes API and ALL matrices independently, captures at most one Session per
  explicit invocation, recomputes its Corpus, and emits GitHub-safe status plus
  stable human/external/code exit classes.
- Local child commands receive whitelisted Secrets over bounded stdin IPC, not
  argv or environment; official TWS API installation requires an explicit
  human-license attestation and validates the local ZIP before pip.
- Preflight, Session and Corpus bind a composite Broker identity across broker,
  paper/live environment, host/port instance and redacted account hash.
- The read-only Ops view exposes verified API/ALL acceptance counts without
  turning planned sessions into evidence.
- Official `ibapi 10.48.1` plus `protobuf 5.29.5` is installed from the
  user-downloaded licensed ZIP. Native macOS Security-framework Keychain access
  avoids the `security -w` empty-value behavior observed on this machine.
- TWS Paper port 7497 and one redacted managed account passed real transport,
  Preflight and complete callback observation with Client ID 41.
- Five API-Scope `empty_account` sessions are eligible, zero-drop and reconciled.
  Scenario-state gates now reject empty/static-position/order label mismatches.

## External sequence

1. Install matching official stable TWS/IB Gateway and TWS API after personally
   accepting the licenses.
2. Store the Paper account in macOS Keychain, then complete GUI login/2FA; keep
   port, client ID and base currency in local non-secret configuration.
3. Keep API Read-Only enabled for account/position captures. Disable it only for
   the distinct manual-order visibility phase, while retaining the observer-only
   client, and record the matching operator attestation.
4. Pass `ibkr-preflight`.
5. Capture the preregistered `api` Scope matrix with explicit
   `--capture-scenario` labels; evaluate it separately.
6. Capture and evaluate the `all` Scope matrix including manual TWS orders.
7. Capture restart, nightly-reset, late-commission, correction, partial-fill,
   cancel and Bracket tapes.
8. Replay callback permutation/duplication/delay cases deterministically.

Steps 1-4 and the API `empty_account 5/5` slice are complete. The runner now
stops at `static_position 0/5`; the operator must create a genuine bounded Paper
position before another capture. API/ALL order, process/TWS restart, network
recovery, nightly reset and client-switch windows remain `BLOCKED_HUMAN_ACTION`.

## Exit gate

- complete observations at preregistered thresholds for the current Scope;
- accepted facts equal written facts, with zero drops and zero writer errors;
- API/manual Completed Orders visibility demonstrated separately;
- at least one process restart, two TWS/Gateway restarts and one nightly reset;
- Golden Tape corpus passes order-independent replay;
- no Broker write was available to the observation process.
- Corpus coverage proves restarts, recovery, client switching and order visibility;
  repeated empty-account reconnects cannot satisfy the gate.

Until this gate passes, E2 and every real Writer remain BLOCKED.

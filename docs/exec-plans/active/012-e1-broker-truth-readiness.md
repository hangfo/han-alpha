# E1 execution plan: Broker Truth Readiness

Status: E1-A COMPLETE; ISSUE #7 PRE-WRITE/COST HARDENING VERIFIED; REAL MATRIX BLOCKED
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
- The Observer uses an audited positive allowlist containing only the nine
  read/cancel-subscription request families it needs (including matching
  protobuf encoders). Every other current or future
  Broker-operation-shaped `EClient` method is unreachable by default.
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
- Typed Scenario Cases now require real child Session IDs and event receipts for
  process/TWS/network/nightly/client-switch evidence. Issue #6 proved the old
  API 22+2 / ALL 9+1 topology could not satisfy multiple non-reusable
  two-Session Cases. Policy v3 requires API 30 same-Scope + 4 cross-Scope
  Sessions (34 total), and ALL 14+2 (16 total).
- Every new Session binds the capture process boot UUID. A Process Restart Case
  rejects receipts that do not exactly match two distinct child Session boot
  UUIDs; a later label or fabricated PID cannot satisfy it.
- Client 41 point-in-time all-open-orders snapshots are distinct from future
  Client-0 manual-order binding. Raw callback facts retain evidence-based order
  origin rather than treating a scenario label as provenance.
- An isolated bounded Paper fixture exists for minimal E1 facts. It is not
  imported by runtime, refuses live ports/ambiguous accounts/excess size and
  consumes a one-shot Permit before a Broker write. No real fixture write has
  yet been attempted.
- Scenario Case v2 adds a validity-independent Evidence Set hash. Acceptance
  allocates every child Session and Event Receipt once, verifies corpus
  membership, and rejects duplicate or validity-rewrapped evidence.
- Raw `sendMsg`/`sendMsgProtoBuf` are unreachable to observer callers and are
  enabled only inside a thread-local declared read or handshake context.
- PLACE/MODIFY/CLOSE permits require a fresh, unique, real-time,
  regular-session IBKR Quote/Contract Capsule with a tight spread and price
  collar. Outcomes distinguish open, fill, cancel, reject and Unknown.
- A resumable lifecycle ledger records the baseline and every one-shot action.
  Cleanup passes only when no fixture order remains and the position returns to
  baseline.
- The hardened positive allowlist passed a fresh authenticated zero-write
  observation with Client 419: complete Scope, 31 accepted/written facts, no
  position/order and no future manual-order binding claim. A normalized
  compatibility Scope hash preserves the five immutable legacy Client 41
  Sessions while retaining their original raw Scope hashes.
- The Issue #6 raw-send guard passed another real zero-write observation with
  Client 419: 33 accepted/written facts, zero drops, complete Scope and no
  position/order. SPY contract qualification succeeded, but TWS reported no
  eligible real-time market data; no Quote Capsule, Permit or write was created.
- Issue #7 requires a separate, unique fresh Quote for every PLACE/MODIFY/CLOSE
  action, records feed scope and fit-for-purpose, and migrates legacy lifecycle
  ledgers without losing their baselines. An immutable zero-cost receipt is
  required before quote capture; regulatory snapshots are never a fallback.
- A 2026-07-30 zero-write SPY retry, with operator entitlement attestation,
  still returned `REALTIME_MARKET_DATA_ENTITLEMENT_REQUIRED`. This current
  Broker fact overrides the reported subscription state; no lifecycle was
  started and no write was attempted.

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

Steps 1-4, the API `empty_account 5/5` slice and Issue #6 local contracts are complete. The runner now
stops at `static_position 0/5`; the operator must create a genuine bounded Paper
position after the real-time Quote gate passes. API/ALL order, process/TWS restart, network
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

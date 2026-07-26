# ADR 0011: evidence authority requires resolvable artifacts and offline review

Status: accepted

## Decision

- A hash-shaped string is not evidence. Safety and data-qualification decisions
  must resolve an immutable registered artifact and recheck its file hash, type,
  schema, canonical identity and policy result.
- Runtime processes hold Ed25519 public keys only. Safety Cases require independent
  Risk and Execution approval receipts; private signing keys are offline.
- Data-source checks require both a typed evidence artifact and an unexpired signed
  reviewer receipt. A profile's `VERIFIED` field is never sufficient.
- Burn-in capture and acceptance are separate. Failed observations are retained,
  while only a homogeneous, coverage-complete corpus may pass.

## Consequences

E1-A and R1-A can be completed locally without granting Broker or vendor access.
E1-B and R1-B remain external evidence work. Permit issuance, a real Writer and
strategy promotion remain blocked until the corresponding artifacts resolve.

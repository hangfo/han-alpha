import { render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { App } from "./App";

afterEach(() => vi.restoreAllMocks());

test("renders a source-backed safety overview", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({
    as_of: new Date().toISOString(), environment: "paper-first",
    safety: { frozen: true, freeze_reason: "RECONCILIATION", unknown_intents: 1, naked_exposures: 0, max_naked_duration_ms: 0 },
    execution: { status_counts: { APPROVAL_PENDING: 2 }, pending_approvals: 2, pending_cancels: 0, reserved_notional: "1000" },
    reconciliation: { status: "BLOCKED", started_at: null, age_seconds: null, unresolved_discrepancies: 1, authority_snapshot_as_of: null, authority_age_seconds: null, visibility_scope_hash: null },
    observer: { available: false, status: "NO_LOCAL_FACT_TAPE" },
    freshness: { api_age_seconds: 0, authority_age_seconds: null, observer_fact_age_seconds: null, quote_age_seconds: null, quote_provider_age_seconds: null, reconciliation_age_seconds: null },
    readiness: { service: { ready: true, checks: { api: true } }, observer: { ready: false, checks: { certificate: false } }, authority: { ready: false, checks: { fresh: false } }, shadow: { ready: false, checks: { market: false } }, runtime_control: { ready: false, checks: { broker: false } }, paper_canary: { ready: false, checks: { authority: false } } },
    authority_timeline: [], discrepancies: [], heartbeats: [],
    backup: { status: "NO_RECORDED_BACKUP", age_seconds: null },
    burn_in: { completed_observation_sessions: 0, stable_consensus_votes: 0, consecutive_stable_sessions: 0, divergent_resets: 0, non_independent_rejections: 0, target_sessions: 30, process_restarts: 0, target_process_restarts: 3, tws_restarts: 0, target_tws_restarts: 2, nightly_resets: 0, target_nightly_resets: 1, golden_tapes: 0, target_golden_tapes: 10 },
    paper_canary_safety_case: { available: false, status: "NOT_ISSUED", created_at: null },
    reality_gap: { samples: 0, no_trade_outcomes: 3 },
    source_notes: { control: "durable SQLite projection" }
  }) }));
  render(<App />);
  expect(await screen.findByText("FROZEN")).toBeInTheDocument();
  expect(screen.getByText("Paper Canary 未就绪")).toBeInTheDocument();
  expect(screen.getByText("APPROVAL_PENDING")).toBeInTheDocument();
});

test("fails visibly instead of presenting stale state", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
  render(<App />);
  expect(await screen.findByRole("alert")).toHaveTextContent("运维数据不可用");
});

import { render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { App } from "./App";

afterEach(() => vi.restoreAllMocks());

test("renders a source-backed safety overview", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({
    as_of: new Date().toISOString(), environment: "paper-first",
    safety: { frozen: true, freeze_reason: "RECONCILIATION", unknown_intents: 1, naked_exposures: 0, max_naked_duration_ms: 0 },
    execution: { status_counts: { APPROVAL_PENDING: 2 }, pending_approvals: 2, pending_cancels: 0, reserved_notional: "1000" },
    reconciliation: { status: "BLOCKED", started_at: null, unresolved_discrepancies: 1, authority_snapshot_as_of: null, visibility_scope_hash: null },
    observer: { available: false, status: "NO_LOCAL_FACT_TAPE" }, heartbeats: [], reality_gap: { samples: 0, no_trade_outcomes: 3 },
    source_notes: { control: "durable SQLite projection" }
  }) }));
  render(<App />);
  expect(await screen.findByText("FROZEN")).toBeInTheDocument();
  expect(screen.getByText("需要人工关注")).toBeInTheDocument();
  expect(screen.getByText("APPROVAL_PENDING")).toBeInTheDocument();
});

test("fails visibly instead of presenting stale state", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
  render(<App />);
  expect(await screen.findByRole("alert")).toHaveTextContent("运维数据不可用");
});

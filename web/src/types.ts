export type OpsOverview = {
  as_of: string;
  environment: string;
  safety: {
    frozen: boolean;
    freeze_reason: string;
    unknown_intents: number;
    naked_exposures: number;
    max_naked_duration_ms: number;
  };
  execution: {
    status_counts: Record<string, number>;
    pending_approvals: number;
    pending_cancels: number;
    reserved_notional: string;
  };
  reconciliation: {
    status: string;
    started_at: string | null;
    unresolved_discrepancies: number;
    authority_snapshot_as_of: string | null;
    visibility_scope_hash: string | null;
  };
  observer: { available: boolean; status: string; as_of?: string; critical_errors?: string[] };
  heartbeats: Array<{ component: string; status: string; observed_at: string }>;
  reality_gap: { samples: number; no_trade_outcomes: number };
  source_notes: Record<string, string>;
};

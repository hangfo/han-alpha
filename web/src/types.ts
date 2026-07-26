export type ReadinessLayer = { ready: boolean; checks: Record<string, boolean> };

export type OpsOverview = {
  as_of: string;
  environment: string;
  safety: { frozen: boolean; freeze_reason: string; unknown_intents: number; naked_exposures: number; max_naked_duration_ms: number };
  execution: { status_counts: Record<string, number>; pending_approvals: number; pending_cancels: number; reserved_notional: string };
  reconciliation: { status: string; started_at: string | null; age_seconds: number | null; unresolved_discrepancies: number; authority_snapshot_as_of: string | null; authority_age_seconds: number | null; visibility_scope_hash: string | null };
  observer: { available: boolean; status: string; as_of?: string; age_seconds?: number; queue_depth?: number; dropped_facts?: number; commission_pending?: number; cash_complete?: boolean; critical_errors?: string[] };
  freshness: { api_age_seconds: number; authority_age_seconds: number | null; observer_fact_age_seconds: number | null; quote_age_seconds: number | null; quote_provider_age_seconds: number | null; reconciliation_age_seconds: number | null };
  readiness: Record<"service" | "observer" | "authority" | "shadow" | "runtime_control" | "paper_canary", ReadinessLayer>;
  authority_timeline: Array<{ certificate_id: string; recorded_at: string; reconciliation_status: string; promotion_status: string; policy_reason: string }>;
  discrepancies: Array<{ kind: string; entity_key: string; severity: string; status: string; first_seen_at: string | null; last_seen_at: string | null; resolved_at: string | null }>;
  heartbeats: Array<{ component: string; status: string; observed_at: string; age_seconds: number | null }>;
  backup: { status: string; age_seconds: number | null; generation_id?: string; integrity?: string };
  burn_in: { completed_observation_sessions: number; stable_consensus_votes: number; consecutive_stable_sessions: number; divergent_resets: number; non_independent_rejections: number; target_sessions: number; process_restarts: number; target_process_restarts: number; tws_restarts: number; target_tws_restarts: number; nightly_resets: number; target_nightly_resets: number; golden_tapes: number; target_golden_tapes: number };
  paper_canary_safety_case: { available: boolean; status: string; created_at: string | null; safety_case_id?: string };
  reality_gap: { samples: number; no_trade_outcomes: number };
  source_notes: Record<string, string>;
};

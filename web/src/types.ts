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
  evidence_registry: { total: number; verified: number; type_counts: Record<string, number>; status_counts: Record<string, number>; recent: Array<{ artifact_id: string; artifact_type: string; schema_version: string; created_at: string; status: string; verified: boolean; reasons: string[] }> };
  external_acceptance: {
    e1: Record<"api" | "all", { completed: number; required: number; decision: string; counts?: Record<string, number>; requirements?: Record<string, number> }>;
    r1: Record<"sec_edgar" | "fred_alfred" | "massive", { sample_manifests: number; decision: string }>;
  };
  burn_in: { scope_hash: string | null; scope_policy?: { completed_orders_api_only?: boolean | null; client_id?: number; base_currency?: string }; completed_observation_sessions: number; stable_consensus_votes: number; consecutive_stable_sessions: number; divergent_resets: number; non_independent_rejections: number; target_sessions: number; process_restarts: number; target_process_restarts: number; tws_restarts: number; target_tws_restarts: number; nightly_resets: number; target_nightly_resets: number; golden_tapes: number; target_golden_tapes: number; corpus_decision: string; corpus_reasons: string[]; coverage_counts: Record<string, number>; coverage_requirements: Record<string, number>; golden_tape_decision: string; golden_tape_transform_coverage: Record<string, number>; last_reset_reason?: string | null };
  paper_canary_safety_case: { available: boolean; status: string; created_at: string | null; safety_case_id?: string; verified?: boolean; reasons?: string[] };
  reality_gap: { samples: number; no_trade_outcomes: number };
  source_notes: Record<string, string>;
};

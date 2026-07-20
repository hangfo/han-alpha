import { useEffect, useState } from "react";
import type { OpsOverview } from "./types";
import "./styles.css";

const formatAge = (value?: string | null) => {
  if (!value) return "无权威样本";
  const seconds = Math.max(0, Math.round((Date.now() - Date.parse(value)) / 1000));
  return seconds < 60 ? `${seconds} 秒前` : `${Math.floor(seconds / 60)} 分钟前`;
};
const secondsLabel = (value?: number | null) => value == null ? "无数据" : value < 60 ? `${Math.round(value)} 秒` : `${Math.floor(value / 60)} 分钟`;
const shortId = (value: string) => `${value.slice(0, 8)}…`;

function Card({ label, value, detail, danger = false }: { label: string; value: string | number; detail: string; danger?: boolean }) {
  return <article className={`card ${danger ? "danger" : ""}`}><span>{label}</span><strong>{value}</strong><small>{detail}</small></article>;
}

export function App() {
  const [data, setData] = useState<OpsOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const response = await fetch("/ops/overview", { headers: { Accept: "application/json" } });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json() as OpsOverview;
        if (active) { setData(payload); setError(null); }
      } catch (reason) { if (active) setError(reason instanceof Error ? reason.message : "未知错误"); }
    };
    void load();
    const timer = window.setInterval(load, 15_000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);
  if (error && !data) return <main className="state" role="alert"><h1>运维数据不可用</h1><p>{error}</p><p>界面不会把陈旧数据伪装成实时状态。</p></main>;
  if (!data) return <main className="state" aria-busy="true"><div className="pulse" /><h1>正在读取权威状态</h1></main>;

  const unsafe = !data.readiness.paper_canary.ready;
  return <main>
    <header><div><p className="eyebrow">HAN ALPHA / PAPER-FIRST OPERATIONS</p><h1>交易事实，而不是乐观叙事。</h1><p className="subtitle">观察权威、对账权威和交易准入权威彼此独立。此界面保持只读。</p></div><div className={`status ${unsafe ? "bad" : "good"}`}><i />{unsafe ? "Paper Canary 未就绪" : "Paper Canary 就绪"}<small>API {formatAge(data.as_of)}</small></div></header>
    <section className="grid metrics" aria-label="核心安全指标">
      <Card label="新风险门禁" value={data.safety.frozen ? "FROZEN" : "OPEN"} detail={data.safety.freeze_reason || "无阻断 ticket"} danger={data.safety.frozen} />
      <Card label="不确定执行" value={data.safety.unknown_intents} detail="submit / cancel unknown" danger={data.safety.unknown_intents > 0} />
      <Card label="裸露风险" value={data.safety.naked_exposures} detail={`最长 ${data.safety.max_naked_duration_ms} ms`} danger={data.safety.naked_exposures > 0} />
      <Card label="待人工批准" value={data.execution.pending_approvals} detail={`${data.execution.pending_cancels} 个持久化撤单待发`} />
    </section>
    <section className="panel readiness"><div className="panel-title"><h2>分层准入</h2><span>每层独立 fail-closed</span></div><div className="readiness-grid">{Object.entries(data.readiness).map(([name, layer]) => <div className={layer.ready ? "ready" : "blocked"} key={name}><b>{name.replace("_", " ")}</b><span>{layer.ready ? "READY" : "BLOCKED"}</span><small>{Object.values(layer.checks).filter(Boolean).length}/{Object.keys(layer.checks).length} checks</small></div>)}</div></section>
    <section className="grid metrics" aria-label="关键事实新鲜度">
      <Card label="Authority age" value={secondsLabel(data.freshness.authority_age_seconds)} detail="交易准入权威" danger={(data.freshness.authority_age_seconds ?? Infinity) > 30} />
      <Card label="Observer fact age" value={secondsLabel(data.freshness.observer_fact_age_seconds)} detail="IBKR 原始事实" danger={(data.freshness.observer_fact_age_seconds ?? Infinity) > 30} />
      <Card label="Quote age" value={secondsLabel(data.freshness.quote_age_seconds)} detail="冻结行情胶囊" danger={(data.freshness.quote_age_seconds ?? Infinity) > 5} />
      <Card label="Reconcile age" value={secondsLabel(data.freshness.reconciliation_age_seconds)} detail="最近对账" danger={data.freshness.reconciliation_age_seconds == null} />
    </section>
    <section className="grid panels">
      <article className="panel"><div className="panel-title"><h2>券商观察与对账</h2><span>{data.observer.status}</span></div><dl><div><dt>现金权威</dt><dd>{data.observer.cash_complete ? "COMPLETE" : "PENDING"}</dd></div><div><dt>最近权威快照</dt><dd>{formatAge(data.reconciliation.authority_snapshot_as_of)}</dd></div><div><dt>对账状态</dt><dd>{data.reconciliation.status}</dd></div><div><dt>未解决差异</dt><dd>{data.reconciliation.unresolved_discrepancies}</dd></div></dl></article>
      <article className="panel"><div className="panel-title"><h2>执行状态分布</h2><span>{data.execution.reserved_notional} reserved</span></div><div className="rows">{Object.keys(data.execution.status_counts).length === 0 ? <p className="empty">当前没有执行意图</p> : Object.entries(data.execution.status_counts).map(([key, value]) => <div className="row" key={key}><span>{key}</span><b>{value}</b></div>)}</div></article>
      <article className="panel wide"><div className="panel-title"><h2>Authority 时间轴</h2><span>候选与晋级严格分离</span></div><div className="rows">{data.authority_timeline.length === 0 ? <p className="empty">尚无 Authority 候选</p> : data.authority_timeline.map(item => <div className="row" key={item.certificate_id}><span>{new Date(item.recorded_at).toLocaleTimeString()} · {shortId(item.certificate_id)}</span><b className={item.promotion_status === "PROMOTED" ? "ok-text" : "bad-text"}>{item.reconciliation_status} / {item.promotion_status}</b></div>)}</div></article>
      <article className="panel"><div className="panel-title"><h2>差异生命周期</h2><span>{data.discrepancies.length} recent</span></div><div className="rows">{data.discrepancies.length === 0 ? <p className="empty">没有差异记录</p> : data.discrepancies.slice(0, 8).map(item => <div className="row" key={`${item.kind}-${item.entity_key}`}><span>{item.kind}</span><b>{item.status}</b></div>)}</div></article>
      <article className="panel"><div className="panel-title"><h2>恢复与 Burn-in</h2><span>{data.backup.status}</span></div><dl><div><dt>备份年龄</dt><dd>{secondsLabel(data.backup.age_seconds)}</dd></div><div><dt>独立会话</dt><dd>{data.burn_in.independent_sessions} / {data.burn_in.target_sessions}</dd></div><div><dt>TWS 重启</dt><dd>{data.burn_in.tws_restarts} / {data.burn_in.target_tws_restarts}</dd></div><div><dt>Golden Tape</dt><dd>{data.burn_in.golden_tapes} / {data.burn_in.target_golden_tapes}</dd></div></dl></article>
      <article className="panel wide"><div className="panel-title"><h2>运行证据</h2><span>只显示有来源的指标</span></div><div className="evidence"><div><b>{data.reality_gap.samples}</b><span>Reality Gap 样本</span></div><div><b>{data.reality_gap.no_trade_outcomes}</b><span>No-trade 结果</span></div><div><b>{data.heartbeats.length}</b><span>组件心跳</span></div></div><footer>{Object.values(data.source_notes).map(note => <p key={note}>{note}</p>)}</footer></article>
    </section>
  </main>;
}

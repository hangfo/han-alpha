import { useEffect, useState } from "react";
import type { OpsOverview } from "./types";
import "./styles.css";

const formatAge = (value?: string | null) => {
  if (!value) return "无权威样本";
  const seconds = Math.max(0, Math.round((Date.now() - Date.parse(value)) / 1000));
  return seconds < 60 ? `${seconds} 秒前` : `${Math.floor(seconds / 60)} 分钟前`;
};

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
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : "未知错误");
      }
    };
    void load();
    const timer = window.setInterval(load, 15_000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);

  if (error && !data) return <main className="state" role="alert"><h1>运维数据不可用</h1><p>{error}</p><p>界面不会把陈旧数据伪装成实时状态。</p></main>;
  if (!data) return <main className="state" aria-busy="true"><div className="pulse" /><h1>正在读取权威状态</h1></main>;

  const unsafe = data.safety.frozen || data.safety.unknown_intents > 0 || data.safety.naked_exposures > 0;
  return <main>
    <header>
      <div><p className="eyebrow">HAN ALPHA / PAPER-FIRST OPERATIONS</p><h1>交易事实，而不是乐观叙事。</h1><p className="subtitle">券商状态为订单、成交、仓位与现金的最终权威。此版仪表盘只读。</p></div>
      <div className={`status ${unsafe ? "bad" : "good"}`}><i />{unsafe ? "需要人工关注" : "本地控制面正常"}<small>{formatAge(data.as_of)}</small></div>
    </header>
    <section className="grid metrics" aria-label="核心安全指标">
      <Card label="新风险门禁" value={data.safety.frozen ? "FROZEN" : "OPEN"} detail={data.safety.freeze_reason || "无阻断 ticket"} danger={data.safety.frozen} />
      <Card label="不确定执行" value={data.safety.unknown_intents} detail="submit / cancel unknown" danger={data.safety.unknown_intents > 0} />
      <Card label="裸露风险" value={data.safety.naked_exposures} detail={`最长 ${data.safety.max_naked_duration_ms} ms`} danger={data.safety.naked_exposures > 0} />
      <Card label="待人工批准" value={data.execution.pending_approvals} detail={`${data.execution.pending_cancels} 个持久化撤单待发`} />
    </section>
    <section className="grid panels">
      <article className="panel"><div className="panel-title"><h2>券商观察与对账</h2><span>{data.observer.status}</span></div>
        <dl><div><dt>完整性证书</dt><dd>{data.observer.available ? data.observer.status : "未接入本地事实带"}</dd></div><div><dt>最近权威快照</dt><dd>{formatAge(data.reconciliation.authority_snapshot_as_of)}</dd></div><div><dt>对账状态</dt><dd>{data.reconciliation.status}</dd></div><div><dt>未解决差异</dt><dd>{data.reconciliation.unresolved_discrepancies}</dd></div></dl>
      </article>
      <article className="panel"><div className="panel-title"><h2>执行状态分布</h2><span>{data.execution.reserved_notional} reserved</span></div>
        <div className="rows">{Object.keys(data.execution.status_counts).length === 0 ? <p className="empty">当前没有执行意图</p> : Object.entries(data.execution.status_counts).map(([key, value]) => <div className="row" key={key}><span>{key}</span><b>{value}</b></div>)}</div>
      </article>
      <article className="panel wide"><div className="panel-title"><h2>运行证据</h2><span>只显示有来源的指标</span></div>
        <div className="evidence"><div><b>{data.reality_gap.samples}</b><span>Reality Gap 样本</span></div><div><b>{data.reality_gap.no_trade_outcomes}</b><span>No-trade 结果</span></div><div><b>{data.heartbeats.length}</b><span>组件心跳</span></div></div>
        <footer>{Object.values(data.source_notes).map(note => <p key={note}>{note}</p>)}</footer>
      </article>
    </section>
  </main>;
}

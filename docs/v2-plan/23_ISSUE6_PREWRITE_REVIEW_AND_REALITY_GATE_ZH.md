# Issue #6 Review 决策与首次 Paper 写入前真实性门

基线：`8c14f86`。本轮目标不是尽快下第一单，而是保证第一次 Paper
写入、结果判定和清理本身都能成为不可重复消费、不可自报成功的证据。

## 逐条评估

| Review / Issue #6 建议 | 决策 | 理由与实现 |
|---|---|---|
| Case 证据防复用 | 接受并实现 | Scenario Case v2 增加不含有效期的 `evidence_set_hash`；Acceptance allocation 对 child Session、Event Receipt 和 evidence set 一次性分配，重新包装有效期不能增加覆盖。 |
| Case 子 Session 必须属于当前 Corpus | 接受并实现 | 非跨 Scope Case 的全部 child 必须存在于当前同 Scope Corpus；Client-switch 只能引用显式 cross-scope child，并要求不同 Client 与 Scope。 |
| 同一 Session 默认不能跨 Case 使用 | 接受并实现 | 分配器默认拒绝 Session/Receipt 重用。由此发现旧 API 24 / ALL 10 拓扑无法同时满足其 Case 数量，不能为了保留旧数字而放松证据。 |
| 重新定义 E1 Session 总数 | 接受并修正 | API 改为 30 个同 Scope + 4 个跨 Scope，共 34；ALL 改为 14+2，共 16。每个 restart/recovery/client-switch Case 使用独立的两个 Session，消除同一对 Session 刷多个 Case。 |
| Observer 原始 `sendMsg` 隔离 | 接受并实现 | `sendMsg`/`sendMsgProtoBuf` 不再是公开 transport allowlist；只在当前线程正在执行声明的只读请求或必要握手时内部开放。直接 raw send、`replaceFA`、`reqAutoOpenOrders`、`reqOpenOrders`、写订单及未知 EClient 方法均 fail closed。 |
| Quote/Contract Capsule | 接受并实现 | PLACE/MODIFY/CLOSE 必须绑定唯一 SMART/USD/STK `conId`、IBKR liquid hours、实时 market-data type、bid/ask/last、点差和 15 秒有效期。延迟、陈旧、歧义、非 RTH、宽点差或价格超 collar 全部拒绝。 |
| 精确 Broker outcome | 接受并实现 | 结果拆为 `BROKER_ACCEPTED_OPEN`、`BROKER_FILLED`、`BROKER_CANCELLED`、`BROKER_REJECTED`、`OUTCOME_UNKNOWN`；`Inactive`、错误回调和仅有 order ID 不再算成功。 |
| MODIFY 保留原订单身份 | 接受并实现 | 必须匹配原 broker order ID、`E1FIX:` ref、`conId`、symbol、side、LMT、1 股和账户；禁止借改单翻向、换合约或换账户。 |
| 可恢复 Fixture lifecycle | 接受并实现 | 生命周期先记录 baseline，再把每个一次性 permit/receipt 写入 SQLite；`execute` 强制要求 lifecycle 并在任何 Broker 写入前校验账户、symbol、`conId`、Quote 与未关闭状态；状态检查输出精确 fixture order ref 与数量但不输出账户；只有零 fixture order 且持仓回到 baseline 才签发 `CLEAN` receipt。Unknown 写入不可重试。 |
| TWS 信息性错误码与真实拒绝分离 | 接受并实现 | 2104/2106/2158/1102 等已知连接恢复或 farm-ready 消息不再把有效订单误判为拒绝；其他错误、`Inactive`、`Rejected` 仍 fail closed。 |
| 直接使用延迟行情完成首次成交 | 舍弃 | 延迟价可用于另行声明的非成交测试，但不能证明当前可成交价格。首次一股 Paper PLACE 保持阻塞，直到实时行情权限或另一项经审核的实时来源可用。 |
| 现在进入 E2/E3 或收益优化 | 舍弃 | E1 Broker Truth 与 R1 PIT Source Acceptance 尚未完成；此时优化收益只会扩大不可验证路径。 |
| PEAD、慢趋势、动量突破并行研究 | 有条件采纳 | 保留为 R2 顺序：PEAD → 慢趋势 → 动量/突破。只能在合格 PIT 数据上离线研究，不接 Broker，不据合成或短期 Paper 结果声称 Alpha。 |
| LLM Research/Skeptic/Committee | 采纳既有边界 | LLM 只抽取、质疑和给出建议；仓位、风险、订单和 Broker 调用继续由确定性代码控制。 |

## 真实验证结果

- TWS Paper `127.0.0.1:7497` 已允许 API 写入，但本轮未写 Broker。
- 新 Observer raw-send guard 在真实会话中完成 33/33 facts，零丢失、
  Scope 完整，持仓和订单均为零。
- SPY 唯一合约解析成功；实时 Quote Capsule 被
  `REALTIME_MARKET_DATA_ENTITLEMENT_REQUIRED` 阻塞。
- 因 Quote Capsule 不存在，未创建 permit、未启动 lifecycle、未 PLACE。

## 下一外部门

1. 为 Paper 会话提供 SPY/美股实时 Level 1 行情权限，或接入另一个经过许可、
   时间戳和 freshness 审核的实时行情源。
2. 安全录入 SEC descriptive User-Agent、FRED key 和 Massive key；未录入前
   R1 只允许 dry-run。
3. Quote gate 通过后，在同一正常交易时段自动完成 Quote → Lifecycle baseline
   → Permit → PLACE/observe → CLOSE → Cleanup Receipt。任一 Unknown 都停止，
   不重试写入。

E1/R1 完成前 E2/E3 保持 BLOCKED。

# M7-A 审计并入与 M7-B 决策

日期：2026-07-20

审计基线：`6cddf4b606175c4af2e6580f6fb1bfa801ae582e`

## 第一性原理结论

交易准入必须同时具备三种互不替代的权威：Broker Observation 证明券商返回了什么，Reconciliation 证明它与本地经济账是否一致，Trading Admission 证明这些事实在此刻仍足够完整、新鲜且与本次报价和审批绑定。任何 API 响应成功、端口开放、旧快照重放或调用者自报哈希都不能替代这三层证明。

## P0 逐条决策

| 审计项 | 决策 | 落地与理由 |
|---|---|---|
| 同一快照可重复建立共识 | 采纳并修复 | 新增不可变 Snapshot Vote Ledger；只有不同 observation/certificate/session、递增 `as_of`、递增全局事实 watermark、满足最小间隔且语义相同的重新观察才能增加票数。重放仅幂等返回，不增加票。 |
| Semantic Hash 不含账户金额 | 采纳并扩展 | 账户数值、订单、仓位、成交、佣金、保护图分别生成 component hash，再进入 combined semantic hash；现金从 100000 变为 50000 必然改变账户和组合哈希。 |
| BLOCKED 快照也写 Authority | 采纳并修复 | 新增 Authority Candidate 层；只有 `CONVERGED` 且 order/position/execution/cash 全部完整、无待到佣金的候选能晋级。其他候选保存为 `REJECTED`，但不进入可交易 Authority 查询。 |
| Arm 接受调用者自报 Quote | 采纳并修复 | 新增不可变 `quote_snapshots`；系统计算 Quote ID、raw hash 和 freshness policy hash。Arm 只接受 `authority_id + quote_snapshot_id`，内部校验 symbol、bid/ask、市场阶段、5 秒新鲜度、30 秒 Authority 新鲜度和价格漂移。 |
| Bracket 三腿同 OrderRef | 采纳并修复 | OrderRef 改为 `HA:<root>:P/T/S`；Reducer 按完整 leg ref 区分，Resolver 只提取 economic root。增加 `permId=0`、三腿乱序仍独立的测试。 |
| Execution Horizon 声明与请求不一致 | 采纳并收窄 | 默认明确记录 `BROKER_DEFAULT_CURRENT_DAY`；API 支持时设置 UTC 当日起点并记录真实 scope。新增 `completedOrder(s)` 事实、End Marker 和 reducer 恢复，结合当前 Open Orders、Executions 与本地历史 Tape。真实返回范围仍需 Paper Golden Tape 校准。 |
| 多库恢复非整组原子 | 采纳并修复恢复侧 | 备份生成跨库 manifest/hash；恢复先写完整 Generation、逐文件 fsync、目录 fsync，再原子切换 `CURRENT` symlink。中途崩溃不会暴露混合 epoch；同名源明确拒绝。在线采集多个源库仍要求服务静止或上层 epoch 协调，不声称分布式瞬时快照。 |

## P1 逐条决策

| 审计项 | 决策 | 落地与理由 |
|---|---|---|
| Execution 时间使用 Callback 时间 | 采纳 | 有明确 offset/UTC 的 Broker 时间作为 `occurred_at`，Callback 时间作为 `received_at`；模糊 TWS 时区 fail-safe 回退并在 raw evidence 记录 parse status、timezone 和 skew。 |
| Commission 缺失仍 Complete | 调整采纳 | Certificate 拆分 order/position/execution/cash completeness。迟到佣金不否定订单观察，但 combined Authority 与新风险 Arm 必须等待现金完整。 |
| 多币种时静默回退 USD | 采纳 | Adapter 使用配置并由 Certificate 证明出现的 Broker base currency；不再从多币种集合猜测或静默回退。真实 `$LEDGER` 行为留待 Paper Tape 校准。 |
| 未知 Child 当 TARGET | 采纳 | `LMT` 才是 TARGET，`STP/STP LMT` 才是 STOP；其他类型拒绝 Snapshot Adapter 并打开冻结 ticket。 |
| Authority 无新鲜度 | 采纳 | Admission 默认 30 秒 TTL；过期会创建 `BROKER_AUTHORITY_STALE`。M7-B 同时显示并暴露 authority age。 |
| `/ready` 不等于交易就绪 | 采纳 | 新增 service/observer/authority/shadow/paper-canary 分层 gate，并提供 `/ready/service`、`/ready/observer`、`/ready/paper-canary`。兼容 `/ready` 但其总体结果采用最严格 Canary gate。 |
| Dashboard 绿色只看 API 时间 | 采纳 | UI 独立展示 API、Authority、Observer、Quote、Reconciliation age；顶层安全状态来自 Paper Canary gate，而非 API 返回时间。 |
| 差异只累计不闭环 | 采纳 | 差异新增 OPEN/RESOLVED 生命周期、first/last seen 和 resolution evidence；后续对账不再出现的实体自动关闭。 |
| Metrics 不足以告警 | 采纳 | 增加 Observer 完整性/队列/drop、Authority/Reconcile/Unknown/Lease/Heartbeat/Backup age、Naked exposure、Commission pending、Cash/Position gap。 |

## 后续工作包和扩展建议

| 建议 | 决策 | 当前边界 |
|---|---|---|
| WP1 Snapshot Vote Ledger | 完成 | 真实 30 Session 证据仍 BLOCKED。 |
| WP2 多维 Authority Hash | 完成 | 目前新风险使用严格 combined Authority；更细粒度只读消费可在真实 Tape 后增加。 |
| WP3 Authority Promotion Service | 完成 | Candidate 与 Promoted 分表，政策 fail-closed。 |
| WP4 Quote Authority | 本地契约完成 | 行情循环自动持久化 Capsule；没有经过交易日历验证的市场阶段标为 `UNVERIFIED`，不可 Arm。 |
| WP5 Bracket Leg Identity | 完成 | 真实 transmit/restart 恢复仍 BLOCKED。 |
| WP6 Completed Orders / Scope | 本地契约完成 | 真实 IBKR scope、夜间 reset 和不同 Client 可见性仍 BLOCKED。 |
| WP7 Generation Backup | 本地恢复原子性完成 | 多库在线采集需停服/协调 epoch；生产 restore drill BLOCKED。 |
| M7-B Readiness/Timeline/Lifecycle/Backup/Burn-in | 完成只读本地切片 | 不增加浏览器写按钮。真实重启和 Golden Tape 计数保持 0，禁止手填成通过。 |
| Durable IBKR 写 Adapter、Cancel、Bracket 状态机、Canary Permit | 延后 | 需要先完成真实零写入 Burn-in；旧写 Adapter 不作为 M5 durable writer 的完成证据。 |
| 三套真实 Alpha baseline | 方向采纳、外部阻塞 | 慢趋势已有预注册基线；横截面动量和 PEAD 必须等待真实无幸存者偏差 PIT 数据，不能用 synthetic 收益代替。 |
| 增加 Agent/RL/期权/自主调参 | 舍弃当前阶段 | 不改善可验证信息优势，且扩大多重检验与执行风险。 |

## M7-B 设计结果

M7-B 仍是只读决策支持面，而不是远程交易终端。默认视图先回答“此刻是否可以增加风险”，再展示导致阻断的最旧事实、Authority 候选时间轴、差异生命周期、恢复代际和 Burn-in 缺口。收益指标继续不显示，直到 Broker 权威 P&L、费用与基准口径齐备。

## 真实收益路线

基础设施评分不能创造 Alpha。最优资源顺序是：完成本地 Authority hardening；连接 Paper 做零写入 Golden Tape；并行接入真实 PIT 股票池、公司行动、财报发布时间和流动性；只比较三套预注册、低自由度 baseline；用扣费后样本外收益、DSR、PBO、回撤、容量、regime 稳定性和 Evidence on/off 增量决定是否继续。第一笔 Paper Canary 仍必须等待真实 Cancel、Bracket 恢复和不可变 Canary Permit。

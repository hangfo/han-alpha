# M7-B.1 Review逐条决策与E1/R1启动

基线：`99053d998a6fdff10b4b996c475ffed8dcaa0289`

## 总结

Review对“停止扩建框架、转向真实Broker和真实PIT证据”的判断正确。本轮把
可以安全本地实现的建议全部落地；依赖真实Tape、真实许可或真实账户的内容
继续明确BLOCKED；会提前扩大交易权限的建议继续拒绝。

## 逐条评估

| Review项目 | 决策 | 实现或理由 |
|---|---|---|
| P0-1 Completed Orders双Scope入口 | 并入 | `ibkr-observe`、`ibkr-burn-in`支持`api/all`，分别映射`reqCompletedOrders(True/False)`；Scope Hash和Burn-in统计隔离。 |
| P0-2 不可变Session Manifest | 并入 | 每个Session导出独立Tape、Certificate、Manifest；绑定Commit、Config、Account Hash、Client、Port、Scope、计数、Watermark、Semantic Hash和对账结果。 |
| P0-3 Fake App不能证明真实TWS | 保留BLOCKED | 本地合同测试不能替代官方`ibapi`、真实Callback、Reset、Commission迟到和Client可见性；没有伪造通过。 |
| P0-4 Permit必须进入Claim事务 | 延后到E2 | 当前不存在真实IBKR Writer。先完成E1；Writer出现前必须实现Permit原子消费。本轮没有给现有Outbox增加任何真实写能力。 |
| P0-5 Freshness Budget Propagation | 并入 | Arm有效期取请求、Quote Observed、Provider Timestamp、Authority、Reservation和Approval剩余寿命的最小值；Claim再次验证当前Authority与同一Quote Gate。 |
| P0-6 Safety Case可信根 | 安全收口 | Ops不再读取`checks=true`。Verifier要求Canonical ID、ACTIVE、有效期、未撤销、当前Scope、完整Artifact Hash及HMAC签名；没有验证密钥时必定BLOCKED。 |
| P0-7 Ops与Arm Quote Gate漂移 | 并入并澄清 | 抽取`evaluate_quote_admission()`；Arm和Ops共享行情时间、Realtime、Phase、Venue、Currency、Spread规则。Ops另外显示Intent Binding未验证，绝不把“最新行情本身可用”冒充“某Intent可执行”。 |
| P0-8 Heartbeat必需集合 | 并入 | Observer、Shadow、Runtime Control、Paper Canary使用不同显式组件集合；无关或Backup单Heartbeat不能使门禁通过。 |
| P1-1 Burn-in按当前Scope | 并入 | 只统计当前Authority/Observer Scope，显示Scope Hash、Scope Policy和最后Reset原因；同时保留全Scope审计计数。 |
| P1-2 Numeric Canonicalization | 暂缓 | 不能凭猜测统一`2/2.0/2.000`。先用真实Golden Tape识别字段，再按金额、价格、数量分别发布Normalization Policy v2，Raw Hash永久保留。 |
| P1-3 Order Payload瞬态ID | 暂缓 | 是否删除Order ID/Client ID必须由Reconnect、Client 0 Bind、All Open和Completed Tape证明；提前删除可能合并不同经济订单。 |
| P1-4 Generation术语 | 并入 | Manifest新增纯内容`content_set_hash`；`generation_id`继续包含创建时间并明确称为Manifest-addressed Generation。 |
| 工作流A Preflight | 并入 | 新增零写、脱敏、不可变`ibkr-preflight`；当前机器因`ibapi`、Paper端口和Account均缺失而BLOCKED。 |
| 工作流A Burn-in CLI | 并入 | 新增`ibkr-burn-in --sessions --completed-orders-scope --output`，观察进程仍无Broker Write Capability。 |
| Golden Tape 11类场景 | 计划进入E1外部阶段 | 代码已有Session导出基础；没有真实Tape前不制造“Golden”Fixture。 |
| 工作流B 数据先审后跑 | 并入 | 新增PIT Source Profile与不可变资格报告；三份初始Profile均故意BLOCKED。 |
| 三个低自由度Baseline | 保留 | 资格通过后只启动慢趋势、横截面动量/突破、PEAD；不新增Agent/RL/期权/HFT。 |
| 摩擦后样本外晋级 | 保留 | R2继续使用DSR/PBO、回撤、尾部滑点、容量、换手、稳定性、因子暴露和Evidence On/Off。 |
| 真实Writer开发时点 | 接受 | 只有E1与E2通过后进入E3。 |
| 首笔1股Canary | 接受但不实施 | Permit、真实Cancel/Bracket、Paper Account Proof缺失；本轮实现会越权。 |
| Safety Case Merkle Manifest | 修改后接受 | 当前用显式Artifact Hash集合和Canonical Root；当外部Artifact数量稳定后再升级Merkle Tree，避免无收益的密码学复杂度。 |
| Observer Truth Coverage Map | 接受为E1 Dashboard后续 | 必须由真实Callback来源矩阵生成，不能根据预期回调写死。 |
| Architecture Freeze | 接受 | ADR 0010冻结基础架构扩张。 |

## 新命名

不建立M7-B.2。后续为两个并行证据流：

```text
E1 Broker Truth Readiness ──> E2 Canary Authorization ──> E3 Paper Manual Execution
R1 PIT Data Qualification ──> R2 Friction-aware OOS Evidence
                                      \                  /
                                       M8 Live Proposal Review
```

M8仍然只有Proposal权限，没有`live_auto`。

## 第一性原理交易结论

真实收益只能来自可重复的信息优势、风险补偿、行为/资金流迟滞或组合/执行优势。
因此下一笔开发预算不投向更多Agent，而投向：

1. 证明当时知道什么；
2. 证明当时能以什么价格和容量交易；
3. 证明结果在费用、滑点、延迟、停牌、退市和参数扰动后仍存在；
4. 证明Broker实际发生了什么；
5. 最后才允许一个有界、一次性、人工复核的Paper实验。

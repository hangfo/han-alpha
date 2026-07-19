# M5 Review逐条评估与M6只读观察决策

日期：2026-07-19  
输入审计基线：`4fc2ff0` 及用户提供的完整review  
原则：Broker事实优先；不以“能下单”为完成；真实Paper写入必须晚于只读收敛证据。

## 总结

Review的方向正确，88/100评分与仓库当时状态相符。所有P0和P1建议均有价值；其中
IBKR fencing必须按Broker实际能力适配，不能声称TWS支持仓库自定义fencing token。
本轮完成M5安全收口和M6-A至M6-E的本地可验证内核。M6-F第一笔Paper Manual
Bracket未执行，原因是本机没有官方`ibapi`包、Paper端口4002/7497均未开放，而且
durable cancel、真实callback golden tape和多轮burn-in尚未验收。

## P0逐条结论

| Review项 | 决定 | 落实与理由 |
|---|---|---|
| P0-1 执行平面没有运行闭环 | 采纳 | 保留Decision Worker，并新增可独立运行的`execution-reconcile`、`execution-dispatch`、审批CLI；执行命令强制先对账再取得单写lease。生产supervisor部署属于M7。 |
| P0-2 冻结状态不统一 | 采纳 | 新增持久`freeze_tickets`作为新风险、审批和dispatch的安全权威；内存KillSwitch仅保留兼容和风险引擎快速短路。人工解冻只能解决人工ticket，不能越权解决对账ticket。 |
| P0-3 fencing时间窗口 | 适配采纳 | Fake Broker在ExecutionWorker构造时立即`advance_fence`，因此新租约获得后、尚未submit时旧writer也会被拒绝。真实IBKR不理解自定义token，必须依赖DB唯一claim、单writer进程锁、submit前lease复核、orderRef和Unknown查询，不能伪造Broker端fence保证。 |
| P0-4 单一全局Sequence水位 | 采纳 | 事件不再因全局sequence较小而丢弃；按broker_event_id/execId/commission execId/orderStatus内容hash去重，状态归约禁止终态倒退。M6事实层完全使用原生身份而非全局水位。 |
| P0-5 现金未对账 | 采纳 | 保存Broker账户基线，以fill和commission经济投影计算期望现金；Cash差异阻断，SettledCash、BuyingPower、AccruedCash和基础币种余额差异标记DEGRADED。Fake现金全程Decimal字符串运算。 |
| P0-6 保护仅按Symbol汇总 | 采纳 | Broker快照新增按parent client key关联的STOP/TARGET Protection Graph；每个已成交BUY父订单分别要求STOP和TARGET数量覆盖，不允许同Symbol其他订单的child掩盖缺口。Symbol汇总仅保留二级裸露区间度量。 |
| P0-7 Unknown不存在判断不严格 | 采纳 | 仅当完整快照的`as_of`严格晚于`claimed_at`才允许重新入队；相等时间明确拒绝。 |
| P0-8 Broker发现订单但本地仍Unknown | 采纳 | 完整快照发现相同economic client key时，直接绑定broker order id、标记outbox delivered并推进ACKNOWLEDGED，不依赖历史ACK回放。 |

## P1逐条结论

| Review项 | 决定 | 落实与理由 |
|---|---|---|
| Intent不可变spec与Projection混淆 | 采纳 | `intent_json`继续作为不可变经济spec；worker只从它读取经济参数，所有生命周期判断读取关系表的`status/version/filled_quantity` projection。审批receipt同时锁定spec hash和projection version。后续schema迁移可物理拆表，但本轮不做无行为收益的破坏性迁移。 |
| Fake Broker使用REAL现金 | 采纳 | 删除所有`CAST(... AS REAL)`，读写均使用Decimal与TEXT，增加高精度现金对账测试。 |
| 无正式Manual Approval入口 | 采纳 | 新增鉴权API `GET/POST /execution/approvals`与CLI；receipt持久化actor、时间、过期时间、intent/reservation hash和projection version。冻结状态下审批fail-closed。 |
| 遗留`pending_orders`内存状态 | 采纳 | 删除；状态和计数完全来自SQLite projection。 |
| Decision Plane仍读旧Broker账户 | 采纳 | Broker账户仍是现金/仓位权威，同时扣除持久active reservation形成combined available capacity；容量不足记录No-Trade而不是抛错或超配。 |

## 八个设计建议逐条结论

1. Session Epoch：采纳。每次Observer连接创建独立`session_id`，事实身份包含session。
2. Freeze Ticket：采纳，作为统一安全权威。
3. Unknown Submission Escrow：采纳。`UNKNOWN` outbox不可重发，只有完整且更新的Broker快照能解除。
4. Protection Coverage Matrix：采纳并实现为每parent的STOP/TARGET覆盖图。
5. Callback Causal Graph：部分采纳。原始事实保留orderId、permId、parentId、clientId、orderRef、execId；可由tape重建。真实tape出现前不虚构完整因果边。
6. Broker Tape Golden Replay：采纳内核。事实带append-only、按原生身份幂等、Reducer可在反序输入下得到相同结果；真实golden tape仍BLOCKED。
7. Reality Gap分解：采纳。分离decision-to-shadow、shadow-to-broker、commission、missed fill和latency并持久化。
8. Durable Approval Receipt：采纳，API与CLI共用同一SQLite事务入口。

## M6阶段结论

- M6-A Observer：本地契约VERIFIED；真实连接BLOCKED。
- M6-B Raw Facts：本地SQLite事实带、session epoch和callback原生身份VERIFIED。
- M6-C Reducer：重复callback、乱序输入、execId/commission绑定与execution correction根识别VERIFIED。
- M6-D Read-only Reconciliation：`CONVERGED/DEGRADED/INCOMPLETE_SNAPSHOT/BLOCKED`状态和完整性证书门禁VERIFIED；真实burn-in BLOCKED。
- M6-E Shadow Execution：成本分解与Missed Fill持久化VERIFIED；真实Paper对照样本BLOCKED。
- M6-F Paper Manual：NOT IMPLEMENTED/NOT AUTHORIZED。不得在前五阶段只有本地证据时跳过门槛。

## 明确舍弃或延期

- 舍弃“把自定义fencing token发给IBKR并由其拒绝旧token”的字面方案：官方API没有该语义。
- 延期生产supervisor、durable cancel、夜间reset演练、真实bracket transmit验证和第一笔Paper订单；这些需要真实Paper环境和独立验收，不能用Fake结果代替。
- 不进入Paper Auto。盈利性和长期稳定性均无真实证据；Paper Auto必须经过长时间burn-in、成本压力和人工审批可靠性证明。

## 下一决策门

只有在安装官方TWS API、只读Paper端口可用后，先运行：

```bash
hanalpha ibkr-observe --state .state/ibkr-observer.sqlite3 --timeout 15
```

要求多次重启后的完整性证书均为complete、事实带可重放、对账持续收敛且无身份
歧义。此阶段仍不调用`placeOrder`。完成durable cancel与Bracket故障测试后，才单独申请
M6-F第一笔Paper Manual授权。

# M7-B Review逐条决策与M7-B.1收口

日期：2026-07-26

基线：`ba85691581a3729dbfdaef97c6a5072f0f138b62`

## 结论

Review的核心P0判断成立：M7-B把请求级元数据、绝对观察窗口和经济状态混入
同一共识身份，真实双Session可能永远无法投出第二票。M7-B.1已在本地修复并用
两次完整Observer调用证明，而不是继续用`model_copy()`伪造第二次观察。

平台仍不具备发送第一笔Paper Canary的资格。M7-B.1的正确终点是“可信地证明
为什么不能发单”，不是绕过真实burn-in补一个写入按钮。

## Review正面结论逐条复核

| Review项 | 决策 | 当前结论 |
| --- | --- | --- |
| Snapshot Vote不可重放 | 保留 | Observation、Certificate、Session、水位和时间独立性继续强制；同一Observation重放不加票。 |
| Candidate与Promoted分离 | 保留 | 只有完整、佣金结清且对账`CONVERGED`的候选可晋级。 |
| Quote Capsule替代自报价格 | 保留并加固 | Arm仍只接受Authority/Quote ID，并新增源时间、实时Feed、未来时钟、点差、Venue和Currency约束。 |
| Bracket三腿身份 | 保留 | `P/T/S`身份与`permId=0`测试不变。 |
| Component Hash覆盖账户金额 | 修正分层 | 现金字段继续精确哈希；动态净值/购买力移到估值层，不能让盘中价格波动改写现金权威。 |
| Completed Orders与Broker时间 | 保留并加固 | Scope现在明确记录`apiOnly`、手工订单可见性和日期范围。 |
| Generation Restore | 保留并修复 | 已存在且完整的同内容Generation幂等复用；绝不先删除CURRENT。 |
| Dashboard只读边界 | 保留 | 未增加浏览器Approve/Cancel/Flatten/Unfreeze。 |

## P0逐条决策

### P0-1 跨Session Hash不可比较：采纳并完成

实现三层分离：

- `ObservationWindow`：Session、Request ID、Epoch、绝对起止时间；
- `Visibility Scope Policy`：账户Hash、Client/可见性、查询策略、Completed
  Orders策略、Base Currency；
- `Canonical Broker State`：只保留券商经济事实。

Canonical Builder统一剔除Request ID、Session、Epoch和Callback接收时间，并
重建稳定Key。双周期测试验证Request ID/Session/证书不同、水位递增，而
Scope Policy Hash与Canonical State Hash相同，第二票成功。

### P0-2 Account Hash过于动态：采纳，但拒绝无证据的“市场解释”

精确层为Cash、Orders、Positions、Executions、Commissions、Protection；
容差层为`NetLiquidation`和`BuyingPower`。容差预算为25 bps或1个基础货币
单位取较大值，并持久化：

- exact fields是否相同；
- tolerance fields是否在预算内；
- normalization policy是否相同；
- 每字段前值、后值、差额和预算；
- 明确的excluded fields。

没有同期持仓估值分解时，收据只写“预算内”，不声称漂移由市场价格解释。超过
预算即重置共识。

### P0-3 假Paper Canary Gate：采纳并完成本地门禁

旧层更名为`runtime_control`，`/ops/overview`接入真实`system.status()`。
真正`paper_canary`额外要求：

- 新鲜Realtime Quote Authority；
- burn-in、Golden Tape、nightly reset；
- market calendar；
- real cancel、real bracket；
- Paper账户证明、durable writer；
- 一次性Canary Permit。

这些项目由不可变Safety Case提供。当前没有外部证据和签发路径，因此Gate必然
BLOCKED，避免“接上runtime状态就过早变绿”。

### P0-4 Arm过期后不可重Arm：采纳并完成

Arm改为按Intent多版本，状态为`ACTIVE/EXPIRED/SUPERSEDED/CONSUMED`。
Approval不变；新Arm替换旧Active；Worker Claim与Arm消费处于同一事务。
Actor、Source和Operator Session均独立记录。旧表可无损迁移。

### P0-5 Quote接收新鲜不等于源行情新鲜：采纳并完成

Arm同时验证：

- observed age与provider age；
- Provider时间不得越过允许时钟偏差；
- `feed_mode == REALTIME`；
- `OPEN/REGULAR`；
- Spread不超过50 bps；
- Symbol、Venue、Currency；
- 价格漂移仍受10 bps系统上限。

Synthetic、External但未证明Realtime、Delayed、未来时间、过旧源时间和宽
点差均fail closed。交易所日历的真实证明仍属于Safety Case外部门槛。

### P0-6 Completed Orders范围不诚实：采纳并完成

Scope新增`completed_orders_requested`、`completed_orders_api_only`、
`manual_completed_orders_visible`和`completed_order_date_scope`。
当前代码继续使用`apiOnly=True`，不会把它显示为账户全部完成订单。真实
`True/False`两阶段验证留给Paper burn-in。

## P1逐条决策

| P1项 | 决策 | 理由与结果 |
| --- | --- | --- |
| 同实体差异内容变化留下多个OPEN | 采纳 | 新版本出现时旧版本标为`SUPERSEDED`并绑定后继ID；消失才`RESOLVED`。 |
| Dropped Facts固定0 | 采纳 | Certificate持久化accepted/written/dropped；完整性要求零Drop且收写相等；Ops/Prometheus读真实值。 |
| Unknown Age被历史永久拉长 | 采纳 | 只查询当前Unknown Intent，并按每个Intent最近一次Unknown开始时间计算。 |
| Divergent Reset计入稳定会话 | 采纳 | 拆分完整观察、稳定票、连续稳定、分歧重置和非独立拒绝。30次观察与连续稳定分别展示。 |
| overwrite先删CURRENT | 采纳但采用更安全实现 | 内容寻址Generation若完整则幂等复用；若同ID内容损坏则拒绝，不删除CURRENT、不“覆盖修复”。 |
| Base Currency默认USD | 采纳 | 从`AppConfig.base_currency`传入IBKR Observer，并要求配置货币字段真实出现。真实账户声明交叉证明仍需Paper回调证据。 |
| Arm缺少Actor | 采纳 | `armed_by/arm_source/operator_session_id`为独立审计字段；不复用Approval Actor。 |

## 后续路线逐条决策

| 建议 | 决策 |
| --- | --- |
| Canonical State Builder | 已完成。 |
| Scope Policy与Observation Window分离 | 已完成。 |
| Tolerance-aware Authority | 已完成保守版本；不推断市场因果。 |
| 真双Session测试 | 已完成完整Observer双周期Fake contract测试；真实IBKR仍BLOCKED。 |
| Canary Gate重命名与补全 | 已完成本地契约；Safety Case签发BLOCKED。 |
| 可重Arm | 已完成并含迁移、过期、替换、消费测试。 |
| Ops指标校正 | 已完成。 |
| 立即真实IBKR零写入Burn-in | 正确下一步，但当前`ibapi`、Paper会话和行情权限缺失时只能BLOCKED。 |
| Alpha研究并行 | 采纳。只使用M3预注册慢趋势、横截面动量/突破、PEAD；无真实PIT数据时不输出收益结论。 |
| 立即开发Durable Writer/Permit | 延后。必须等待真实burn-in、cancel和bracket恢复证据，防止基础设施“自证可交易”。 |
| 新Agent、RL、复杂策略 | 舍弃。当前瓶颈是数据与外部真实性，不是模型数量。 |

## 五个巧思的并入结果

1. 双Hash：已并入Observation Envelope Hash与Canonical State Hash。
2. Authority Equivalence：已并入逐字段预算和Normalization Policy证明。
3. Executable Safety Case：已并入只读准入契约；外部签发尚未实现。
4. Admission原因图：Dashboard逐条展示Paper Canary PASS/BLOCKED原因。
5. Architecture Freeze：采纳。M7-B.1后除真实Paper暴露的资金安全缺陷，不再
   新增服务、Agent或抽象。

## 第一性原理下的交易与收益设计

下一阶段资源优先级不是继续美化Dashboard，而是：

1. **PIT Alpha证据**：无幸存者偏差、退市、公司行动、财报发布时间、一致预期、
   历史行业与可交易性决定信号是否真实存在。
2. **摩擦后的可实现收益**：佣金、点差、滑点、延迟、参与率、部分成交与
   No-Trade机会成本决定Paper结果是否可外推。
3. **Broker真实性**：Observer/Golden Tape/Reset/Cancel/Bracket证明系统知道
   账户实际发生了什么。
4. **有限风险的准入**：只有上述证据进入不可变Safety Case，才允许设计一股、
   限Notional、单次、人工复核的Canary Permit。

最优策略不是回测收益最高的参数，而是样本外扣费收益、DSR/PBO、最大回撤、
容量、参数稳定性、Regime稳定性与因子暴露共同占优且能在真实执行摩擦下存活的
简单策略。Evidence/LLM只做事件抽取和反方审查，不决定仓位或下单。

# M6 Review逐条决策与M7只读运维实现

日期：2026-07-20

审计基线：`943bfabe731287313589dc61c4a41f99089f2e5…`
原则：券商事实优先于本地投影；安全与可恢复性优先于“看起来能交易”；盈利只能由PIT样本外与前向Paper证据支持。

## 结论

Review的核心判断正确，尤其是跨线程SQLite、请求污染证书、身份碰撞和Observer尚未进入M5对账权威链路。建议不是简单照单全收：与资金安全、事实完整性和可恢复性直接相关的全部落地；依赖真实IBKR Paper或前向时间的项目保留为明确BLOCKED；不以端口号、同步Mock或漂亮Dashboard冒充外部验收。

M6本地硬化现在覆盖回调Queue单写者、transport-only连接、精确Request Barrier、可见性作用域、语义证书、原生订单身份、字段Lattice、数字化Execution Correction、M5 BrokerSnapshot适配、双快照共识、Cash Bridge Epoch、两阶段审批、持久化撤单与部分成交Shadow Schedule。真实Paper连接、nightly reset、Golden Tape、Canary和20+20交易日前向窗口仍为BLOCKED。

M7按Review限定先完成只读运维面：liveness/readiness、指标、心跳、来源说明、降级状态、备份恢复和React严格类型前端。危险控制没有被放进Dashboard；现有写API仍保持默认关闭，后续CSRF/双确认必须在写控件出现前独立验收。

## P0逐条处理

| Review项 | 决策 | 实现或理由 |
|---|---|---|
| P0-1 Callback跨线程SQLite | 采纳并完成 | Callback只生成`IBKRFactDraft`并进入有界Queue；唯一writer线程拥有自己的SQLite连接；并发1000条事实测试验证无跨线程写库。 |
| P0-2 `connect()`预请求污染证书 | 采纳并完成 | 新增`connect_transport_only()`；Observer、session和barrier先安装，再发任何读取请求。旧`connect()`仅作transport别名。 |
| P0-3 未接入M5 Reconciler | 采纳并完成 | `IBKRBrokerSnapshotAdapter`将账户、父单、保护子单、持仓、成交和佣金转换成M5契约；CLI执行连续快照和`reconcile_authoritative()`。 |
| P0-4 `order_id`跨Client碰撞 | 采纳并完成 | 身份优先级为permId、orderRef、session/clientId/orderId；Han Alpha订单写入`HA:<economic-key>` orderRef。 |
| P0-5 Open Order字段不足 | 采纳并完成 | 增加contract/account/action/quantity/type/limit/aux/TIF/transmit/OCA/outsideRth/GTD/status等恢复字段，并测试父子Bracket。 |
| P0-6 Marker仅存在性检查 | 采纳并完成 | 证书核对请求ID、position/open-order epoch、账户hash、必需tag、base currency、execution horizon、scope hash、队列水位及writer错误。 |
| P0-7 缺Drain和干净关闭 | 采纳并完成 | quiet-period drain、最终watermark、取消subscription、disconnect、join network thread、关闭writer；证书记录queue depth/accepted/written/error。 |
| P0-8 `ibkr.py`排除覆盖率 | 采纳并完成 | 已从coverage omit移除；Callback、Bracket、orderRef、断连、flatten、transport timeout与连接别名进入测试分母。 |

## P1逐条处理

| Review项 | 决策 | 实现或理由 |
|---|---|---|
| Order Status需要字段Lattice | 采纳并完成 | status按单调等级、filled取最大、remaining取最小、avg price随更高fill更新；原生ID冲突记录为conflict，不静默覆盖。 |
| Correction字符串排序错误 | 采纳并完成 | correction revision按数字tuple比较，`.10`正确晚于`.2`。 |
| 多账户/可见性范围不明 | 采纳并完成单账户边界 | `VisibilityScope`记录configured account、managed count、client/master/manual/other-client可见性和execution horizon；当前只接受唯一显式账户。多账户组合视图延期，避免假完整。 |
| Paper端口不是充分证明 | 采纳但外部BLOCKED | 本地同时要求`HANALPHA_ENV=paper`、标准Paper端口和显式账户；仍不把端口当作账户类型证明，需真实登录/账户核验。 |
| Baseline过静态 | 采纳并完成 | Cash Bridge Ledger区分可解释事件和UNKNOWN；新baseline epoch同时冻结当时projection delta，避免历史成交再次叠加。UNKNOWN冻结。 |
| Settled Cash/Buying Power线性外推 | 采纳并完成 | 仅对Total Cash做可审计经济投影；settled/buying power返回未知并等待券商权威快照，不伪造。 |
| Approval未绑定快照/Quote | 采纳并完成 | `approve`只产生不可变意图批准；独立`arm`绑定最新broker semantic hash、quote hash、价格漂移上限和短TTL，之后才创建submit outbox。 |
| Shadow只有单一平均成交 | 采纳并完成本地模型 | 支持多slice VWAP、部分/未成交量、佣金、机会成本、首填延迟和Protection Ack延迟；真实值需Paper tape。 |

## 后续顺序、Burn-in与M6-F

Review的WP1–WP7全部采纳并已在本地实现。真实Burn-in四步（空账户、TWS手工事件、重启/reset、Golden Tape）全部保留为外部验收，不能由Fake Broker替代。

M6-F建议逐项如下：

| 项 | 决策 | 当前状态 |
|---|---|---|
| Durable Cancel | 采纳 | 本地完成：持久化、幂等、同一lease/fence、冻结时仍可降风险、响应丢失进入`CANCEL_UNKNOWN`。真实IBKR cancel映射BLOCKED。 |
| 新Execution Adapter | 部分完成 | orderRef/Bracket字段和M5 Snapshot Adapter完成；真实IBKR写适配与回调验收BLOCKED，因此不发送Paper订单。 |
| Bracket状态机 | 部分完成 | parent/STOP/TARGET恢复和Protection Graph已测；真实transmit链、子单拒绝和TWS恢复BLOCKED。 |
| Approval Freshness | 采纳 | 两阶段approve/arm完成；arm fail-closed绑定broker/quote/TTL/漂移。 |
| 第一笔Canary | 延期且禁止当前执行 | 必须先完成真实只读Burn-in、cancel与bracket外部验收；只允许最小数量Paper Manual，绝不自动化。 |

## M7建议逐条处理

| 面板/能力 | 决策 | 当前实现 |
|---|---|---|
| Observer | 采纳 | 显示事实带可用性、证书状态、时间、queue drain、visibility和critical errors。 |
| Safety | 采纳 | Freeze原因、Unknown数量、裸露风险/最长时长、审批和撤单队列。 |
| Reconciliation | 采纳 | 最近状态、未解决差异、权威快照时间和scope hash。 |
| Tape | 部分采纳 | 当前展示控制面计数和来源；原始fact明细页延后到真实Golden Tape出现后，避免空壳页面。 |
| Reality Gap | 采纳 | 展示样本量/No-trade，并由新schedule evaluator提供真实填充契约；没有样本时明确为0。 |
| 写控制 | 暂不并入UI | Review明确要求M7先只读。CSRF、双确认、actor审计和回读未独立验收前，不展示freeze/cancel/flatten按钮。 |

## 十个巧思逐条决策

1. 双快照共识：采纳并完成，要求语义hash相同且时间分离。
2. Callback Metamorphic Testing：采纳并完成乱序/重复/并发等价测试；真实Golden Tape变形测试BLOCKED。
3. Visibility Scope Hash：采纳并完成并进入Broker authority。
4. Request Barrier Graph：采纳为精确barrier集合；当前请求没有复杂依赖图，不额外引入图框架。
5. Explainable Cash Bridge：采纳并完成baseline epoch。
6. Unknown Aging Ladder：采纳设计，M7已暴露Unknown；自动分级告警需要长期worker/supervisor，下一运维增量实现。
7. Protection SLA：采纳数据契约，Shadow记录ack delay、Reconciler记录naked interval；真实阈值需Paper分布校准，不能拍脑袋设定。
8. 两阶段人工审批：采纳并完成approve/arm。
9. Paper SLO：采纳设计，Dashboard已有原始指标；正式SLO必须由真实20日观察窗口校准。
10. Architecture Stop Rule：采纳；本轮只读M7和安全遗留收口后停止扩张基础设施，优先PIT Alpha与真实Paper证据。

## Alpha与最优策略判断

“最优交易策略”不是静态代码选择，而是一个带约束的选择问题：在严格PIT数据、交易成本、容量、回撤、成交概率和regime条件下，最大化可重复的样本外风险调整收益。当前仓库的合理策略仍是可解释慢速基线与预注册组合，不引入LLM自主调参、强化学习下单或盘中频繁策略切换。LLM只用于证据分类和批判，不能改变仓位、风控或调用券商。

下一价值最高的工作不是新增Agent，而是并行积累：真实PIT数据质量、慢趋势/突破/事件延续的walk-forward净成本证据、Shadow/Paper成交分布和no-trade机会成本。没有这些数据前，不宣称任何策略“最优”或已盈利。

## 明确未采纳或延期

- 不用Paper端口号推断账户真实性。
- 不把Fake Broker、同步Mock或本地coverage当作真实IBKR验收。
- 不在只读M7加入危险写按钮。
- 不为未来多账户提前放宽当前单账户完整性门槛。
- 不因Dashboard完成而宣称Alpha或Paper就绪。
- 不立即执行Canary，也不启用无人值守Paper/Live。

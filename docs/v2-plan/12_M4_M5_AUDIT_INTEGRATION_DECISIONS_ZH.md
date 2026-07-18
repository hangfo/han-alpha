# M4/M5外部审计逐条处理决定

日期：2026-07-19
审计基线：`b80489d`
处理原则：先判断建议是否改善真实交易决策的正确性、可恢复性或可审计性，再决定并入；不以增加对象或测试数量为目的。

## 总结

审计指出的缺陷均有价值，没有整条舍弃。实现时对三点作了修正：费用不伪造美元值，只记录官方返回的usage并允许以后用有版本的费率表估算；15个崩溃点按事务不变量等价类覆盖，而不是制造15段重复测试；未知的模型快照不写死，快照名由配置显式提供并进入配置hash。

## P0逐条结论

1. **Responses原始JSON解析：并入。** 原实现把SDK便利属性`output_text`误当成HTTP顶层字段。现从`output[].content[]`提取`output_text`，拒绝refusal和空输出，并用真实HTTP形状的MockTransport测试usage、request ID和模型快照。
2. **LLM不计算offset/hash：并入。** 模型只返回逐字quote、出现序号和可选section；后端在冻结Document中定位、生成offset和hash。无法定位时整个提取失败，Claim/Cache不落库，失败Attempt保留。
3. **Review强绑定：并入。** Review绑定candidate、decision、entity、evidence snapshot、review time和reviewer config hash；跨实体、未来或伪造Claim失败。`ALLOW`改为语义更准确的`NO_OBJECTION`。
4. **Ablation数学修复：并入。** baseline和evidence使用相同decision集合、相同风险权重和固定分母；增量直接取两套总PnL之差再扣模型/延迟成本，avoided loss与missed gain只作归因，不再二次加入总值。
5. **拆除旧Agent直通Broker：并入。** 运行时不再由旧Committee决定后直接调用Broker。M4 Evidence Snapshot/Review先绑定候选，确定性Risk产生Reservation，随后冻结Decision Capsule并写Outbox；执行面不能回调策略、LLM或行情解释。

## P1逐条结论

1. **Cache配置不完整：并入。** config hash覆盖adapter、model snapshot、reasoning effort、schema、prompt、normalization和policy epoch。
2. **Claim语义身份/不可变冲突：并入。** Claim ID覆盖scope和source span；同ID不同JSON触发immutable conflict，并保留revision/supersedes字段。
3. **模型自由决定过期：并入后收紧。** 期限完全由后端`ClaimExpiryPolicy`按Claim类型决定；当前不接受模型期限，因此无需clamp。
4. **Contradiction过粗：并入。** 只有entity和subject/metric/segment/geography/fiscal period/time horizon均一致的反义Claim才连边，避免跨业务线假冲突。
5. **Budget作用域：并入。** Cache按完整extractor配置隔离；逻辑事件预算按document+task type共享，防止换模型绕过事件预算；每次Provider attempt单独审计。
6. **真实费用审计：部分并入，拒绝伪精度。** 持久化provider/request/response/model/http/token/cache/reasoning/latency；美元成本仅在有版本费率来源时填写，否则`unpriced_usage`。Responses返回usage，不返回最终账单，不能声称“真实费用”。
7. **Ingest原子性：并入。** Claim、Contradiction、Cache和Attempt完成在一个事务内提交；Document与调用预算先行持久化是故意的审计边界，失败调用仍必须消耗预算并留下证据。

## Promotion两项

1. **仅TEST基础实验可晋级：并入。** Validation/Train及counterfactual禁止晋级。
2. **No-Trade不可晋级：并入。** 新增最少成交数、最少在场时间和相对基准超额门槛；正向测试改为真实入场及保护性退出，不再用零交易结果冒充成功。

## M5架构建议逐条决定

- Decision Capsule、Durable Reservation、Execution Intent、Transactional Outbox、Broker Inbox、Order Event/Projection、Lease/Fencing：全部并入。
- `SUBMISSION_UNKNOWN`：并入且与ERROR严格区分。未知提交不会盲重发；Broker已有则绑定，权威快照确认不存在后才重排队。
- Durable Fake Broker：并入持久Broker truth、故障场景、Broker Tape、重复事件、部分成交、拒单、接受后丢响应、Broker-only、Fill/Cancel竞争和迟到Commission。
- Reconciliation：并入startup freeze、Broker order/fill/position/protection核对、Critical freeze及仅无Critical时unfreeze。
- 15点Crash Matrix：按等价类并入。数据库事务中间点覆盖capsule/reservation/outbox；claim-before-call与accept-before-response覆盖未知提交；Inbox+Projection同事务覆盖回调中断；restart/partial fill/fencing/reconcile覆盖恢复类。Bracket子单和真实IBKR session reset属于M6适配器验收，不伪称已验证。
- Broker Tape、Decision Capsule Hash、Naked Exposure Clock、Reality Gap Ledger、No-Trade Ledger：全部并入本地契约；Reality Gap的真实Paper/Shadow填充留给M6。

## 边界结论

M4现已完成本地接口和权威链路收口。M5完成的是Fake Broker上的可恢复执行控制内核，不是IBKR Paper验收。真实Provider、真实PIT增量价值、IBKR callback/session reset、真实Bracket transmit语义和前向收益仍分别受凭证、数据许可和M6验证约束。

# Han Alpha V2 实施路线与门禁

## 总原则

每个 milestone 是独立 Goal。只有上一个阶段的证据包、验收命令和风险清单通过，才能进入下一阶段。默认不调用付费 API；任何批量数据采购、LLM 评测、IBKR 连接或订单动作都需要用户再次明确授权。

## M0：基线冻结与安全清理（1–2 周）

交付：原包 hash、实现矩阵、ADR、威胁模型、统一模式能力表；修复模拟限价、决策时钟、默认 `paper_auto=false`、危险 API 认证边界；加入 `live_auto` 不存在的结构性测试。

门禁：纯本地测试全绿；无网络运行；代码搜索证明领域层没有 broker/LLM 密钥；本轮审计 P0 均有失败测试。

## M1：PIT 数据内核（2–4 周）

交付：security master、上市/退市/ticker 变更、公司行动、交易日历、raw/normalized schema、available-time 规则、数据质量与 lineage；小型冻结 fixture。

门禁：PIT universe 测试、公司行动回放、时区/DST、重复/迟到数据、不可得信息泄漏测试；同一 snapshot hash 产生相同特征 hash。

## M2：同构组合回测（3–5 周）

交付：统一时钟、组合/现金/挂单、部分成交、成本模型、halt/TTL/gap、强制收盘规则；实验注册与结果包。

门禁：accounting invariants、bar/event 时间对齐、回测/仿真 parity、随机 null、walk-forward、DSR/PBO、成本敏感性。若基础策略没有稳定证据，停止继续堆 LLM。

## M3：策略基线与预注册（2–4 周）

交付：动量、PEAD、trend-entry overlay；明确特征、参数范围、禁用未来信息；benchmark/factor attribution。

门禁：冻结 OOS 指标、换手/容量/最大回撤、行业与市值桶稳定性；所有参数均可追溯到训练区选择。

## M4：LLM Evidence Service（2–4 周）

交付：Evidence Pack、JSON Schema、缓存/预算/熔断、模型注册、注入隔离、评测集和 on/off ablation。

门禁：事实抽取/引用/反证达到预注册阈值；失败默认 abstain；模型升级回归可复现；扣除 LLM 成本后对主指标有稳定增量，否则保持研究旁路。

## M5：执行控制面与 Fake Broker（3–5 周）

交付：PostgreSQL 状态机、原子 reservation/outbox、单写者租约、approval、kill switch、reconciler；可编程 FakeBroker 故障注入。

门禁：重复事件、乱序、部分成交、拒单、断线、进程崩溃、重放、未知订单/持仓测试；任何情况下不重复提交且风险预占守恒。

## M6：IBKR Paper 集成（3–6 周 + 观察期）

交付：完整 callback、启动/持续对账、account/clientId/port 白名单、nightly reset、人工 runbook。

门禁：先 paper_manual；人工批准最小数量订单；重连和部分成交演练；至少 20 个交易日 Shadow、随后至少 20 个交易日受控 Paper，无未解释对账差异。

## M7：Ops Dashboard（2–3 周）

交付：只读健康/数据新鲜度/候选/风险/订单/成交/对账/LLM 预算；受保护的批准、取消、freeze、flatten；不可直接编辑风险参数。

门禁：localhost 默认、认证/CSRF、双确认、审计 actor、移动端只读、断网/服务降级可见。

## M8：Live Proposal（独立安全审查）

交付：只生成 proposal；每单人工批准；独立凭据和进程能力；法律、税务、市场数据许可和操作责任确认。

门禁：M0–M7 全部通过；灾难恢复演练；风险预算由用户签字确认。**不包含自动实盘。**

## 当前明确不做

- 高频/做市/期权/卖空/盘前盘后/多券商路由。
- 强化学习直接下单、LLM 自主调仓、LLM 生成可执行代码。
- Kubernetes、Kafka、复杂微服务和在 Alpha 未证明前的多区域容灾。
- 用漂亮仪表盘替代数据、回测或对账正确性。

## Codex 模型工作流

- 架构、PIT、风险、订单状态机和券商恢复：`gpt-5.6-sol`，High/Extra High；一次只做一个 milestone。
- 常规实现、测试和 review：Sol Medium/High。
- 机械迁移、格式化、文档一致性：Terra Medium。
- Ultra 只在用户明确要求并行 worktree/subagent 时使用；Max 只给单个最难阻塞问题。


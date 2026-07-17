# Han Alpha V2 Master Task

## 目标

把现有 V0.1 骨架演进为可审计、可复现、Paper-first 的美股/ETF long-only 研究与交易控制系统。成功标准不是“功能多”，而是：PIT 数据无泄漏、研究和运行同构、风险预占原子化、Broker 可恢复对账、LLM 有可测增量且永不拥有执行权。

## 权威文档顺序

1. 根目录 `AGENTS.md`。
2. `docs/v2-plan/01_CONVERSATION_AND_PACKAGE_AUDIT_ZH.md`。
3. `docs/v2-plan/02_TARGET_ARCHITECTURE_ZH.md`。
4. `docs/v2-plan/03_IMPLEMENTATION_ROADMAP_ZH.md`。
5. 当前 milestone 的 exec plan 和 ADR。

若旧文档与 v2-plan 冲突，以 v2-plan 为准，但必须通过 ADR 记录迁移决定，不能静默改语义。

## 永久约束

- US stocks/ETFs、long-only、RTH、Paper-first。
- 模式只允许 research/backtest/shadow/paper_manual/paper_auto/live_proposal；不存在 live_auto。
- LLM 不得决定数量、风险预算、订单类型、账户、路由或调用 Broker。
- `paper_auto` 默认 false；Live proposal 每单人工批准。
- 真实 IBKR、付费大批量数据或 LLM 调用必须在执行前重新获得用户明确授权，并先说明 provider、调用次数、范围与成本上界。
- naive datetime、隐式系统时间、未来可得数据、今日成分股回填历史均是失败。
- Broker 状态优先于本地 projection；任何无法解释的差异冻结新开仓。
- 保留明确 defer；不得用空壳、mock 成功路径或删除验收项制造完成。

## 每个 milestone 的工作协议

1. 先阅读 AGENTS、v2-plan、当前实现矩阵、最新 exec plan、git 状态。
2. 写一个边界明确的 exec plan：范围、非范围、风险、验收、停止条件。
3. 先补失败测试或可观察证据，再实现最小闭环。
4. 使用同一个领域核心支持 historical 和运行模式；适配器不得复制策略/风险规则。
5. 更新 ADR、实现矩阵、已知限制、变更日志和验证报告。
6. 报告采用：完成 / 部分完成 / 明确 defer；每个 defer 写理由、风险、下一 milestone。

## 跨阶段不变量测试

- Capability：任何非执行进程都无法构造 Broker write capability。
- Time：所有决策都带显式 as_of；证据 available_at <= as_of。
- Risk：position + open orders + reservations 的最坏风险不超过预算。
- Idempotency：崩溃、重试、重复/乱序 callback 不产生重复提交或重复成交记账。
- Reconciliation：Broker 与本地差异可检测、分类、审计并触发 freeze。
- Replay：相同 snapshot/config/code/prompt/model 输出相同确定性产物；非确定性 LLM 输出使用缓存快照回放。
- Research：无 LLM 基线、成本、退市/公司行动、walk-forward 和 factor attribution 不可跳过。

## 完成定义

只有当前 milestone 的代码、测试、文档、迁移、运行手册和失败演练都完成，验证命令可从干净环境重现，且没有被掩盖的 P0/P1 风险时，才可声明该 milestone 完成。项目总体完成不等于允许实盘；Live Proposal 仍需独立审批。


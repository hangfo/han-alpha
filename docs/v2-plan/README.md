# Han Alpha V2 设计审查索引

状态：**M0-M5 已完成本地验收；M6 IBKR Paper 是下一阶段。**

本目录起源于对原会话最终附件 `han-alpha-codex-ready.zip` 与最后一版
Codex Goal 提示词的独立复核。00-06 保存设计冻结背景，07 以后记录逐里程碑
实施决策。M0-M4 已运行本地验证并修改代码；仍未连接券商、下载真实供应商
数据或调用真实 LLM Provider。

## 结论

项目作为“研究 → 回测 → Shadow → IBKR Paper”的分阶段系统可行；作为“一次 Goal 完成、随后可自动实盘”的系统不可行。当前附件是一个结构清晰、能表达边界的教学型 V0.1 骨架，不是生产级交易平台。最优路线不是继续堆多 Agent，而是先建立时间一致的数据、研究/实盘同构的策略核心、单写者订单状态机、券商对账权威和可证明的无 LLM 基线。

## 阅读顺序

1. [00_BASELINE_PROVENANCE.md](00_BASELINE_PROVENANCE.md)：会话、附件、哈希和本轮只读边界。
2. [01_CONVERSATION_AND_PACKAGE_AUDIT_ZH.md](01_CONVERSATION_AND_PACKAGE_AUDIT_ZH.md)：逐条评分、代码审计与可行性判断。
3. [02_TARGET_ARCHITECTURE_ZH.md](02_TARGET_ARCHITECTURE_ZH.md)：从第一性原理推导的目标架构。
4. [03_IMPLEMENTATION_ROADMAP_ZH.md](03_IMPLEMENTATION_ROADMAP_ZH.md)：阶段、门禁、验收和明确不做项。
5. [04_MASTER_TASK_ZH.md](04_MASTER_TASK_ZH.md)：未来 Codex 实施时的完整任务规格。
6. [05_CODEX_GOAL_PROMPT_ZH.md](05_CODEX_GOAL_PROMPT_ZH.md)：小于 4,000 字符的最新 Goal 提示词。
7. [06_PUBLIC_EVIDENCE_REGISTER.md](06_PUBLIC_EVIDENCE_REGISTER.md)：公开资料、论文和官方文档证据表。
8. [07_M0_CLOSEOUT_AND_M1_DECISION_ZH.md](07_M0_CLOSEOUT_AND_M1_DECISION_ZH.md)：M0 收口与 PIT 决策。
9. [08_M1_FROZEN_FIXTURE_SPEC_ZH.md](08_M1_FROZEN_FIXTURE_SPEC_ZH.md)：M1 冻结 fixture 规格。
10. [09_PASTED_REVIEW_AND_M2_DECISIONS_ZH.md](09_PASTED_REVIEW_AND_M2_DECISIONS_ZH.md)：M2 审计并入决定。
11. [10_M3_AUDIT_INTEGRATION_DECISIONS_ZH.md](10_M3_AUDIT_INTEGRATION_DECISIONS_ZH.md)：M3 审计并入决定。
12. [11_M3_CLOSEOUT_AND_M4_AUDIT_DECISIONS_ZH.md](11_M3_CLOSEOUT_AND_M4_AUDIT_DECISIONS_ZH.md)：M3 权限收口与 M4 证据服务决定。

## 决策摘要

- 交易范围继续锁定：美国股票/ETF、long-only、常规交易时段、Paper-first、没有 `live_auto`。
- 研究频率调整：日频/小时级负责选股与事件持续性；5 分钟数据只负责入场、流动性和执行质量。
- LLM 降级为证据处理器：结构化抽取、矛盾检查、行业传导、反证与置信度；不产生仓位、订单或最终数值分数。
- 架构从“多 Agent 叙事”改为“可审计模块化单体”：PostgreSQL 保存控制面真相，Parquet/DuckDB 保存历史研究数据，Broker 是订单/持仓权威。
- 第一项 Alpha 证明必须是不调用 LLM 的基线；LLM 只有在盲测中证明扣除成本后的增量价值，才可进入 Shadow。
- 每个阶段单独 Goal、单独验收；禁止用“NOT_IMPLEMENTED 必须为空”制造表面完整性。

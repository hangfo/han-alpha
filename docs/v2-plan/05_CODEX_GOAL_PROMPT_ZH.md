# Codex Goal 提示词（M0，仅设计与安全基线）

> 下列正文可直接作为新 Codex Goal。详细要求已经版本化在 repo 中，Goal 本身保持短小。

```text
目标：在 /Users/rich/han-alpha 中完成 Han Alpha V2 的 M0“基线冻结与安全清理”，不要推进 M1 以后内容。

开始前完整阅读：根 AGENTS.md、docs/v2-plan/README.md、01_CONVERSATION_AND_PACKAGE_AUDIT_ZH.md、02_TARGET_ARCHITECTURE_ZH.md、03_IMPLEMENTATION_ROADMAP_ZH.md、04_MASTER_TASK_ZH.md，以及现有 IMPLEMENTATION_MATRIX、KNOWN_LIMITATIONS、SECURITY_THREAT_MODEL、git 状态。先给出简短计划，再实施。

本 Goal 只允许本地、无网络、无付费调用、无券商连接。不得连接 IBKR，不得下单，不得请求市场数据或 LLM，不得开启 paper_auto/live。若任何步骤需要这些权限，立即停止并报告。

M0 必须交付：
1. 冻结原始附件来源、SHA256、文件清单与 V0.1 基线说明。
2. 用 ADR 定义 capability-based modes；明确不存在 live_auto，paper_auto 默认 false。
3. 为审计列出的 P0 缺陷先补失败测试；本 Goal 只修与 M0 安全边界直接相关的问题：显式 DecisionClock、模拟限价不穿价、危险 API 默认不可写、运行时 Broker write capability 隔离。
4. 建立 V2 实现矩阵、当前风险登记、M1 入口条件；不得用空壳实现把未完项标为完成。
5. 更新 CHANGELOG、KNOWN_LIMITATIONS、VERIFICATION_REPORT 和 M0 exec plan。

约束：保留现有用户改动；不做破坏性 git 操作；所有时间为 timezone-aware；LLM 永远无 Broker 工具；Broker 写能力必须由独立进程配置和显式 capability 同时满足；本地 API 默认只读/localhost；任何 defer 都要写理由、风险和目标 milestone。

完成标准：相关 unit/integration/adversarial 测试、ruff、mypy 全绿；新增结构性测试证明 research/backtest/shadow/live_proposal 不能提交订单，paper_auto 默认关闭，模拟限价成交不越限，naive/as-of 不被静默接受；验证可在干净本地环境复现。最后逐条报告完成、部分完成和 defer，并明确 M1 是否可开始。不要连接外部系统，也不要声称项目整体完成。
```

## 后续 Goal 规则

M1–M8 每个阶段都应生成新的、同样短小的 Goal，详细需求写入阶段 exec plan。不要复用原会话 9k+ 字符的“一次性完成”提示词。


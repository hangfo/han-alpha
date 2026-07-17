# 可直接粘贴给Codex的主提示词

你正在本地打开`han-alpha`仓库。请完整接管并完成这个项目，不要只做分析、计划、代码骨架或局部演示。

首先读取并严格遵守：

1. `AGENTS.md`
2. `CODEX_START_HERE.md`
3. `docs/codex/MASTER_TASK_ZH.md`
4. `docs/codex/ACCEPTANCE_CRITERIA.md`
5. `docs/codex/EXECUTION_PLAN.md`
6. `docs/codex/TEST_MATRIX.md`
7. `docs/exec-plans/active/001-complete-platform.md`
8. 现有`docs/`全部相关架构、策略、安全和运行文档

任务目标：在现有V0.1基础上，一次性完成可长期运行的交易研究、研究级回测、Agent证据审查、IBKR Paper执行、Dashboard、可观测性和运维平台。盈利是研究目标，但不得宣称未被严格样本外和Paper前向测试证明的Alpha。

工作要求：

- 立即运行基线测试并记录结果，然后按活动执行计划依赖顺序持续实现；
- 不要完成一个阶段后停下来询问是否继续；除非需要真实密钥、付费订阅或用户在TWS中手动登录，否则自行作出保守工程决策并继续；
- 外部权限缺失时，完成全部fake、contract、replay和故障注入测试，并在验证报告中标为BLOCKED，附准确联调命令；
- 保持synthetic模式零密钥可运行；
- 实现React/TypeScript Dashboard、point-in-time数据层、组合级回测、walk-forward/purged CV、实验注册、IBKR启动对账与恢复、LLM缓存和消融、结构化日志/指标/告警、Docker Compose和完整CI；
- 不允许LLM计算仓位、修改风控或直接调用Broker；
- 不允许无人值守live自动下单，`live_proposal`只能生成待人工审批建议；
- 不得为了让测试通过而削弱风控、幂等、数据时效或对账；
- 每个功能必须有正常、失败、边界、并发和对抗性测试；
- 后端分支覆盖率至少85%，前端关键流程有Vitest和Playwright；
- 运行`./scripts/preflight.sh`和`./scripts/verify_all.sh`，修复全部失败；
- 更新README、架构、运行手册、已知限制、活动执行计划和`docs/VERIFICATION_REPORT.md`；
- 使用git分阶段提交，最终工作树保持干净。

完成标准以`docs/codex/ACCEPTANCE_CRITERIA.md`为唯一准绳。最终不要只说“完成”，而要逐项给出VERIFIED、BLOCKED和NOT IMPLEMENTED，并引用实际测试命令、覆盖率和端到端结果。任何无法真实验证的外部集成都必须诚实标注，不得模拟成成功。

现在开始执行，不要先向我复述计划。

你是`han-alpha`平台的独立安全、数据正确性和交易工程审计者。不要默认相信README、验证报告或前一个Agent的完成声明。

读取`AGENTS.md`和`docs/codex/ACCEPTANCE_CRITERIA.md`，然后执行以下工作：

- 从代码实际控制流确认不存在无人值守live自动transmit路径；
- 检查LLM能否越权计算仓位、修改风险或调用Broker；
- 检查point-in-time、公司行动、退市、SEC发布时间和ALFRED vintage；
- 检查回测是否存在同bar成交、未来数据、幸存者偏差和成本遗漏；
- 检查IBKR幂等、partial fill、重连、启动对账和夜间恢复；
- 检查Dashboard权限、CSRF、XSS、重放和破坏性操作幂等；
- 运行全部静态、类型、测试、覆盖率、构建、E2E和安全扫描；
- 主动增加能击穿系统的对抗性测试，不要只重复现有测试；
- 对每项验收标准给出PASS、FAIL或BLOCKED及证据；
- 发现问题时直接修复并补回归测试，不要只写审计意见；
- 最终更新`docs/VERIFICATION_REPORT.md`，提交修复并保持工作树干净。

禁止把缺少真实凭证的外部联调写成PASS；禁止为了通过审计而降低测试阈值或风控。

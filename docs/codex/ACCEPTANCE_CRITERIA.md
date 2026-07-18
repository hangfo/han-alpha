# 完整平台验收标准

Codex必须逐项核对，不得用“代码已写”代替行为证明。

## 1. 零凭证可运行

- [ ] 新机器按README可安装。
- [ ] `synthetic`模式无需网络和密钥完成完整周期。
- [ ] CLI、API和Dashboard可启动。
- [ ] 产生信号、风控决策、订单、成交、持仓和退出审计。

## 2. Dashboard

- [ ] 环境和自动提交状态始终醒目显示。
- [ ] 健康、账户、持仓、订单、信号、风险、审计和研究页面可用。
- [ ] destructive actions有二次确认、确认词、权限和审计。
- [ ] 前端不能直接连接Broker。
- [ ] Vitest和Playwright关键路径通过。
- [ ] 空状态、错误状态、断线和陈旧数据有明确提示。

## 3. 数据正确性

- [ ] 所有时间戳带时区并使用UTC存储。
- [ ] 外部观测含source、observed_at、effective_at、ingested_at。
- [ ] 公司行动和退市不会造成虚假收益。
- [ ] SEC事件在公开前不可见。
- [ ] FRED历史研究使用ALFRED vintage或显式标注非vintage。
- [ ] 数据快照有hash和schema版本。
- [ ] 缺失数据不被未来值静默回填。

## 4. 回测

- [ ] 多资产共享资金和组合风控。
- [ ] 成交延迟、佣金、点差、滑点和市场冲击可配置。
- [ ] 支持部分成交、跳空止损、停牌和退市。
- [ ] 支持walk-forward、purge和embargo。
- [ ] 输出基准和无LLM消融。
- [ ] 实验可由commit、配置、数据hash和seed复现。
- [ ] 参数扰动和多重检验报告存在。

## 5. IBKR Paper

- [ ] 无TWS时contract/fake测试完整通过。
- [ ] 有TWS Paper时完成账户、持仓、open orders和成交对账。
- [ ] 重复提交不会产生重复券商订单。
- [ ] 部分成交、拒单、取消和夜间重连可恢复。
- [ ] Shadow Fill和Paper Fill同时记录。
- [ ] `live_proposal`不存在自动transmit路径，并有测试证明。

## 6. Agent安全

- [x] Agent不能访问Broker或仓位计算函数。
- [x] malformed JSON、伪造evidence、prompt injection均fail-closed。
- [x] LLM超时和限流不会生成未审查订单。
- [x] 相同证据缓存命中，不重复计费。
- [x] 提供Agent on/off增量报告。

M4 以上五项为本地结构、fake/deterministic 测试和度量契约验收；真实
Provider 故障行为与真实 PIT on/off 增量价值仍为 BLOCKED，不得据此声称 Alpha。

## 7. 风控和并发

- [ ] 单笔、单票、行业、总敞口、持仓数、日亏和回撤限制有测试。
- [ ] stale data、unknown regime、broker disconnect拒绝新单。
- [ ] 并发信号不能绕过总敞口或idempotency。
- [ ] kill switch、freeze、cancel-all和flatten-all可重复调用且安全。
- [ ] flatten缺失可靠报价时不会猜价格。

M5已在本地Fake Broker边界验证并发Reservation容量、经济订单幂等、持久
freeze、Unknown Submit对账和缺失保护冻结；真实IBKR及完整cancel/flatten
单写入者路径仍属于M6，因此以上平台级条目暂不整体勾选。

## 8. 工程质量

- [x] Ruff通过。
- [x] Mypy strict通过。
- [x] 后端分支覆盖率至少85%。
- [ ] 前端测试通过。
- [x] package build通过。
- [ ] Docker Compose健康启动。
- [ ] secret scan、dependency audit和基础SAST无高危未处理项。
- [ ] CI与本地验证命令一致。

## 9. 运维

- [ ] health与readiness区分。
- [ ] worker和broker心跳可见。
- [ ] 数据库备份与恢复演练有脚本和测试记录。
- [ ] 账本错配产生告警和reconciliation事件。
- [ ] 运行手册覆盖启动、停止、升级、重启、灾难恢复和Paper对账。

## 10. 文档与诚实性

- [ ] README与真实命令一致。
- [ ] 架构图和数据流与实现一致。
- [ ] 所有BLOCKED外部验收列出所需权限和执行命令。
- [ ] 不宣称已证明盈利。
- [ ] 不存在关键范围内的空实现、`pass`、未解释TODO或跳过测试。

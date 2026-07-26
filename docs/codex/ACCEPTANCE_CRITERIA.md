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
Freeze Ticket、严格Unknown Submit对账、按父订单保护图、精确现金对账和
reservation-aware账户容量。M6只读事实带与完整性证书也已通过本地测试；
真实IBKR burn-in及完整durable cancel/flatten单写入者路径仍未完成，因此以上
平台级条目暂不整体勾选。

M7-B.1已把Observation Window、Scope Policy和Canonical Broker State分离，
用两次完整Observer周期验证跨Session共识，并增加估值容差证明、可重Arm和
严格Quote准入。完整Paper Canary仍要求外部Safety Case、真实Writer/Cancel/
Bracket与一次性Permit，因此不得据本地测试勾选真实Paper验收。

E1进一步加入Completed Orders双Scope、不可变Session Artifact、Freshness
Budget传播、当前Scope Burn-in和Safety Case Verifier；R1加入真实数据源资格门。
当前机器缺少官方`ibapi`、Paper端口、Paper账户和Vendor凭证，因此这些新增
本地合同仍不能勾选真实Broker或真实PIT验收。

E1-A/R1-A进一步拒绝Hash形状和Profile自报结论：Session/Corpus必须可解析并
重验，Safety Case采用离线Ed25519双Reviewer，数据资格需要带Expiry的Artifact
与Reviewer Receipt。E1-B/R1-B真实环境和样本仍未完成，相关外部条目不勾选。

E1-B/R1-B本地验收工具进一步区分TWS Read-Only账户观察与ALL-Scope订单可见性；
Observer写方法被结构性封锁。Golden Tape变形回放、Callback Truth Map、有界真实
源Probe、Claim-scoped Artifact及Evidence/Corpus只读视图已实现。没有真实账户、
许可、样本和Reviewer Receipt时仍不得勾选外部验收。

Issue #3 的本地安全接入已实现：Keychain SecretProvider、`local-onboard`、
可恢复 `e1/r1 run`、严格Artifact文档、可搬迁内容寻址对象、真实HTTP传输字节
分层和结构化退出码均有对抗性测试。许可证接受、安装、Paper登录/2FA、账户/
密钥录入、书面数据权利和独立签名仍是人工或外部阻塞，不能据此勾选E1-B/R1-B。

Issue #4 本地加固已把子进程Secret迁移到有界stdin IPC，Broker证据绑定组合
账户/环境/实例身份，增加本人License证明后的官方ZIP安全安装器、R1权利模板和
Registry-backed外部验收面板。真实License接受、Paper登录/2FA、API/ALL
Callback Corpus、Vendor Rights/Samples和独立签名仍未发生，因此E1-B/R1-B
继续不勾选。

2026-07-27 用户已完成TWS Paper安装、登录/2FA、API许可证接受和官方ZIP下载。
本机已安装`ibapi 10.48.1`/`protobuf 5.29.5`，7497真实监听，单一Paper账户通过
原生macOS Keychain安全发现。API Scope已有5个合格`empty_account` Session，
回调完整、零丢失且对账收敛；但`static_position`、API/ALL订单、重启/恢复/
nightly reset/client切换和每个Broker写入仍未验证，所以IBKR Paper整项继续
不勾选，E2/E3不得启动。

Issue #5 本地加固已完成：restart/recovery 不再能由标签冒充；统一政策明确
API 22个同Scope + 2个跨Scope Session、ALL 9+1；Client-switch 仅通过跨Scope
Case；Observer改为正向只读方法白名单；订单快照与未来自动绑定分离；受限
Paper fixture 仅作为一次性测试事实生产器。尚未执行任何fixture Broker写入，
也尚无真实static/API/manual order或reset Case，因此E1-B仍不勾选。

## 8. 工程质量

- [x] Ruff通过。
- [x] Mypy strict通过。
- [x] 后端分支覆盖率至少85%。
- [x] 前端测试通过。
- [x] package build通过。
- [ ] Docker Compose健康启动。
- [ ] secret scan、dependency audit和基础SAST无高危未处理项。
- [ ] CI与本地验证命令一致。

## 9. 运维

- [x] health与readiness区分。
- [x] worker和broker心跳可见。
- [x] 数据库备份与恢复演练有脚本和测试记录。
- [x] 账本错配产生告警和reconciliation事件。
- [x] 运行手册覆盖启动、停止、升级、重启、灾难恢复和Paper对账。

## 10. 文档与诚实性

- [ ] README与真实命令一致。
- [ ] 架构图和数据流与实现一致。
- [ ] 所有BLOCKED外部验收列出所需权限和执行命令。
- [ ] 不宣称已证明盈利。
- [ ] 不存在关键范围内的空实现、`pass`、未解释TODO或跳过测试。

# E1-B/R1-B 网页 Review逐条决策与真实环境边界

基线：`0b9b9879071b928e6524917263e90904aaaf962f`

## 总结

Review对E1-A/R1-A的评分和“停止扩张架构、转向真实Broker与真实数据”的主结论
成立。但它遗漏了一个关键IBKR约束：TWS的Read-Only API会隐藏订单信息，因此不能
在保持该设置的同时验收ALL Scope手工订单。当前观察CLI还复用了完整Broker类，虽无
Capability且没有写调用，仍不满足最强的结构隔离。本轮修复该缺口，并实现Issue中
所有无需外部账户即可证明的功能。

## 逐条评估

| Review项目 | 决策 | 理由与实现 |
|---|---|---|
| 工程成熟度96分、赚钱能力10–15分 | 接受量级，不接受“接近满分”的外推 | 本地治理质量高，但真实Broker、许可、PIT样本、OOS和Forward均为空；收益评分不能靠架构补齐。 |
| Artifact Registry是本轮最大价值 | 接受并加固 | 新增Claim Scope；同一类型Artifact只有显式声明`qualifies_checks`才能满足对应资格项，防止一个通用TIMESTAMP Artifact包办所有时间语义。 |
| Manifest达到审计级 | 接受并加固 | Session捕获后自动注册；Corpus显式拒绝混合Completed Orders Scope。 |
| Burn-in必须是场景矩阵 | 接受 | API/ALL继续独立；Dashboard和CLI现在读取真实Corpus覆盖计数，不再显示硬编码0。 |
| Ed25519离线双Reviewer | 接受 | 保持Runtime公钥-only；不在应用中生成或保存Reviewer私钥。 |
| R1资格系统成为资格管理 | 接受并加固 | Artifact类型正确仍不够，必须同时绑定具体Check Claim、Expiry和独立Review Receipt。 |
| 下一阶段只做E1-B/R1-B | 接受 | 不增加Agent、策略自由度或Writer。 |
| 安装官方IBKR API | 接受，账户所有者阻塞 | 官方许可、TWS安装、GUI登录和2FA不能代签；本机已生成安全`.env`，账户字段留空。 |
| 全程保持TWS Read-Only | 修改采用 | 账户/持仓阶段保持Read-Only；订单可见性阶段必须关闭TWS Read-Only，但Han Alpha使用Observer-only客户端，`placeOrder/cancelOrder/reqGlobalCancel/exerciseOptions`全部结构性拒绝。 |
| 5次小捕获→API 30→ALL 10 | 接受 | 小批检查后再扩大；Capture不等于Corpus PASS。 |
| Massive先小权限、小样本 | 接受 | 新增最多7个Ticker的有界Probe；不自动购买、不会下载Flat File全集。 |
| SEC优先，100家公司 | 修改采用 | PEAD价值高，但第一批限制最多10个CIK；先覆盖10-K/10-Q/8-K及Amendment，再扩大到100，避免未验证抓取。 |
| ALFRED从CPI/非农/GDP开始 | 接受 | Probe保存Observation realtime period与Vintage Dates；日期级Vintage不能自动证明盘中发布时间。 |
| Evidence Registry Dashboard | 接受并实现 | Ops API/React显示Artifact总数、类型、状态、重新解析结果与最近证据。 |
| Corpus Explorer | 接受并实现 | Ops读取已验证Burn-in/Golden Tape Corpus的场景覆盖、重启、Reset和Transform Coverage。 |
| TradingAgents只作Evidence Analyst | 接受 | 当前不引入新Agent。 |
| E1-B/R1-B→E2/E3/R2→M8 | 接受 | M8仍是人工Live Proposal，永不产生`live_auto`。 |

## GitHub Issues覆盖审计

Issue #1覆盖真实IBKR安装、Preflight、API/ALL矩阵、Golden Tape与Truth Map；
Issue #2覆盖Massive、SEC、ALFRED的许可、Entitlement、样本和各类PIT审计。

原Issue未覆盖：

1. TWS Read-Only与订单可见性的官方冲突；
2. 观察进程对写方法的结构性封锁；
3. Qualification Artifact必须绑定具体Check Claim；
4. Review建议的Evidence Registry Dashboard与Corpus Explorer；
5. Provider错误可能在Traceback URL中泄漏API Key的边界。

以上均已在本轮实现或文档化。两个Issue仍不能关闭，因为外部账户、许可、签名Reviewer
和真实样本是其硬验收内容，不应把代码就绪冒充Issue完成。

## 当前外部阻塞

- IBKR：官方TWS/API许可、安装、Paper登录/2FA、Paper账号及真实Callback。
- SEC：真实项目联系邮箱。
- Massive/FRED：账户API Key及计划/底层数据许可。
- 审批：独立Data Reviewer、Risk Reviewer和Execution Reviewer私钥仍须离线管理。
- Alpha：Promotion Qualified数据、真实成本、OOS、Capacity和Forward证据均不存在。

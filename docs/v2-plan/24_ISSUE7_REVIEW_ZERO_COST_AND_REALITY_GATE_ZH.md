# Issue #7 review：零增量成本、实时行情与首笔 Paper Lifecycle

日期：2026-07-30
结论：Review 的核心 P0/P1 判断成立并已并入；评分和“凭证已跑通即等于
R1-B 完成”不作为工程事实。Issue #7 覆盖了 Review 尚未实现的代码缺口，但
外部套餐、许可、行情会话和独立签名仍不是 Issue 能替代的事实。

## 逐条采纳判断

| Review 建议 | 判断 | 落地或理由 |
|---|---|---|
| Case 证据不得复用 | 已有，保留 | Scenario Case v2 和一次性分配已在 Issue #6 完成。 |
| API 34 / ALL 16 的矩阵数学 | 已有，保留 | 不退回旧 24/10 或 22+2/9+1 口径。 |
| Quote Capsule 必须是实时、RTH、窄点差、精确合约 | 已有并加固 | 继续拒绝 delayed/frozen、过期、错合约和越过价格 collar。 |
| 不把 ACK、成交、拒绝、未知结果混为一类 | 已有，保留 | Outcome 分类和 Unknown 后禁止自动重试不变。 |
| 一张 15 秒 Quote 无法覆盖完整 Lifecycle | 采纳，P0 | 每个 PLACE/MODIFY/CLOSE 动作必须绑定独立的新 Quote；Quote ID 与 Permit ID 均唯一。 |
| Lifecycle 约束不能依赖首张 Quote | 采纳，P0 | Lifecycle 固化账户、合约、币种、交易所、数量和名义金额上限；价格新鲜度由逐动作 Quote 负责。 |
| Lifecycle ledger 要兼容旧库 | 补充采纳 | 自动迁移旧列并使用显式列名写入，避免列顺序变化破坏恢复。 |
| 行情“实时”不等于 consolidated NBBO | 采纳，P1 | Quote 写入 `feed_scope`、`bbo_exchange`、snapshot permissions 和用途矩阵；UNKNOWN 不得生成 fixture Permit。 |
| 每次外部请求前生成 Cost Receipt | 采纳，P0 | IBKR、SEC、Massive、FRED 均在网络或 Broker 写前生成并注册不可变回执。 |
| Regulatory Snapshot 可能计费，不能作为默认后备 | 采纳，P0 | 明确禁止；代码只允许已订阅的 streaming quote。 |
| Massive 套餐未知时不能试调用 | 采纳，P0 | 仅 `BASIC_FREE` 或已确认固定订阅、且声明已有 entitlement 时允许最多 3 个 GET。 |
| SEC 证明性调用应保守限速 | 采纳，P1 | 每次 R1 仅 2 个请求，请求间至少 0.5 秒，即不超过 2 次/秒。 |
| FRED/ALFRED 需要重新核对使用条款 | 采纳，P0 | 当前条款审查前在网络前阻断，API key 存在不构成 AI/软件使用和存储权。 |
| HTTP 证据需要请求/首字节/完成/规范化/持久化时间 | 采纳，P1 | Manifest 增加全部阶段、单调时长、服务端 Date 与时钟偏差。 |
| 先零写行情，再最小 Paper Lifecycle | 采纳 | 当前零写 SPY 实测仍被 TWS 拒绝为无实时权限，因此没有创建 Permit 或发送订单。 |
| 正式 Paper Writer 可直接继续 | 不采纳 | Fixture 事实生产器、M5 Writer 和 live proposal 权限域不同；E1 完成前不扩大正式 Writer。 |
| Live Writer 可以顺带实现 | 不采纳 | 项目不允许 `live_auto`；live 只能 proposal-only。 |
| 先把所有真实源大规模入库 | 不采纳 | 必须先通过许可、PIT、时间、退市/修订和独立 Review；成功 HTTP 不是可研究数据。 |
| PEAD → 慢趋势 → 横截面动量 | 采纳为 R2 顺序 | 先做事件时间与预期修正证据，再做低换手基线，最后做更依赖执行质量的动量。 |
| Execution Price Ladder | 延后 | 应在真实 Quote/Paper fill 形成后实现，用于限价偏移、成交率和机会成本实验，不进入 E1 许可门。 |
| Strategy-to-Execution 耦合 | 采纳为设计原则 | 策略排名必须使用扣除点差、佣金、滑点、延迟、未成交和冲击后的结果。 |
| 双价格源校验 | 有条件采纳 | 可做监测和异常否决，不能把未许可的第二源写入回测，也不能用浏览器价替代 IBKR Quote。 |
| Review 的 8.9/10 等评分 | 不作为事实 | 评分是启发式意见；验收只看可复现测试、外部回执、Broker 真相和明确的 BLOCKED 状态。 |

## 本轮真实结果

- GitHub `51b8c95` 已完整提交并推送；旧红叉来自 CI 环境没有另行授权安装
  的官方 `ibapi`，不是 Git 提交失败。Fixture 模块现可在无 `ibapi` 环境被测试
  收集，真正连接或写入仍会 fail-closed。
- macOS Keychain 中 SEC、FRED、Massive 三项配置均可被 runner 发现，且只输出
  presence/hash，不输出值。
- SEC 两请求真实探测成功并生成 transport、normalized、headers、timing 和审计
  Artifact；它仍因书面权利和独立 Reviewer 缺失而是
  `BLOCKED_EXTERNAL_RIGHTS`。
- FRED 在网络前因当前使用政策待审阻断。
- Massive 在网络前因套餐/现有 entitlement 未确认而阻断。
- IBKR SPY streaming quote 仍返回
  `REALTIME_MARKET_DATA_ENTITLEMENT_REQUIRED`。操作者报告已订阅不会覆盖当前
  API 会话的反证；重新登录/确认 Paper 数据共享后必须重跑 Stage A。
- 本轮没有 regulatory snapshot、没有付费调用、没有 Permit、没有 Broker 写。

## 最佳后续顺序

1. 操作者确认 Massive 当前套餐是 `BASIC_FREE` 还是已有固定订阅，并确认 API
   使用不会产生增量费用；随后只跑 3 个 GET 的证明批次。
2. 在 TWS 完全退出并重新登录 Paper 后，确认 API acknowledgement 和 SPY 对应
   的美股 Network B/共享订阅，再重跑零写 streaming quote。
3. 只有 Quote Capsule 的 `PAPER_FIXTURE=PASS` 后，执行一股、USD 1,000 上限的
   PLACE → observe → cancel/fill → fresh quote → close → baseline cleanup。
4. 补齐 API/ALL order、restart/recovery/nightly/client-switch 真实 Case，完成
   E1-B 后才进入 E2/E3。
5. R1-B 逐源形成书面权利、PIT 审计与独立签名；之后按
   PEAD、慢趋势、横截面动量顺序进入 R2，所有比较均使用真实摩擦后的样本外结果。

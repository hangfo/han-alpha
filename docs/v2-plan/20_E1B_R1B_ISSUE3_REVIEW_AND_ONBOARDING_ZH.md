# E1-B/R1-B Review、Issue #3 与安全接入收口

更新时间：2026-07-26  
基线：`10f5fd3b029634d35d9a2b02ea75d2e53e834dda`

## 结论

网页 Review 对工程状态的判断基本准确，但其评分是“当前环境成熟度观察”，
不是仓库验收结论。值得立即并入的部分已落地：Keychain 密钥提供器、可恢复的
E1/R1 外部验收运行器、严格证据文档、可搬迁的内容寻址对象、真实 HTTP 传输
字节和规范化 JSON 分层、结构化退出状态以及 GitHub-safe 摘要。需要真实账户、
许可、登录、2FA、付费数据权利或独立签名的部分仍然是外部阻塞，不能由代码
伪造为完成。

Issue #1、#2、#3 已覆盖当前 E1-B/R1-B 的实现与外部验收缺口。Review 提出的
Evidence Firewall、Research Sandbox、Alpha Confidence 和三类研究 Agent 属于
R2 及之后的研究治理设计，不是 E1/R1 缺陷，因此不应为了“覆盖率”提前扩张架构。

## 逐条评估

| Review 建议 | 决策 | 理由与落地 |
|---|---|---|
| 当前版本工程质量高、外部证据成熟度低 | 接受但校准 | 本地静态检查、类型、测试和安全边界可验证；Broker Truth、数据权利、独立 Review 和 Alpha 尚不可验证，不能混成一个总分。 |
| Observer、Golden Tape、Probe、Claim Authority 方向正确 | 接受 | 保留现有结构；新增运行器只编排和封存证据，不绕过既有验证器。 |
| 增加 Artifact Identity Type | 接受并加强 | 新增 `CONTENT_HASH` / `MANIFEST_HASH`，同时要求严格文档类型、Schema、有效期和内容寻址副本；仅加一个自由文本标签没有权威性。 |
| 保存“真实 HTTP bytes”而非重序列化 JSON | 接受并实现 | Probe 分离 `transport/*.body.bin`、`transport/*.headers.json`、`normalized/*.json`，分别哈希；审计只读取由清单哈希绑定的规范化对象。 |
| 用真实 Callback Truth Map 校准 Golden Tape | 接受，外部阻塞 | 必须来自已认证的 IBKR Paper 回调和受控场景，属于 Issue #1；本机没有 TWS/Gateway、官方 `ibapi`、登录会话或 Paper 账户配置。 |
| API/ALL Scope 使用隔离窗口 | 接受 | E1 运行器为两个 Scope 使用独立目录、独立矩阵和独立计数，跨 Scope Session 不计入。 |
| API/ALL Scope 必须使用不同账户 | 暂不设为硬门槛 | 单一 Paper 账户是常见现实约束；账户哈希、Scope 和时间窗已经防止混证。若用户拥有第二个 Paper 账户，物理隔离更优，但不能把非必要账户条件写成普适验收要求。 |
| Keychain SecretProvider | 接受并实现 | macOS Keychain 为首选；秘密写入使用 stdin、读取值不进入 argv，CLI 不回显。`.env` 只保留为兼容后备并提供迁移/清理命令。 |
| `local-onboard ibkr` | 接受并实现 | 检查应用、官方 API、Paper 配置、账户、端口和零写边界；可启动已安装应用，但许可证、安装、登录和 2FA 必须由用户完成。 |
| `e1 run` 可恢复编排 | 接受并实现 | 每次最多采集一个 Session，按矩阵报告缺口和下一人工动作；只统计已通过清单验证且 Scope 一致的 Session。 |
| `r1 run` 有界真实探针 | 接受并实现 | SEC、FRED/ALFRED、Massive 使用固定小样本；没有本地身份/密钥或未显式 `--execute` 时不发网络请求。成功访问仍只生成待权利与独立 Review 的 Bundle。 |
| 严格 Artifact Schema、可搬迁路径、过期策略 | 接受并实现 | 权威文档必须声明精确 `artifact_type`；注册时复制进 Registry 相对路径的内容寻址对象库，源文件移动不破坏证据；资格文档要求时区有效期。 |
| 结构化退出码和 GitHub 摘要 | 接受并实现 | `PASS=0`、`FAILED_CODE=1`、`BLOCKED_HUMAN_ACTION=20`、`BLOCKED_EXTERNAL_RIGHTS=21`；摘要不输出秘密、账户号或完整敏感标识。 |
| Evidence Firewall | 有价值，延后 | 应在真实 R1 数据和研究接口稳定后实现，用于隔离不可信文本与结构化证据；现在实现会制造没有真实输入的抽象层。 |
| Research Sandbox / Agent 权限分层 | 有价值，延后 | 研究 Agent 只能读证据、生成假设和批评；不能调仓、改风控或调用 Broker。该边界已是设计法则，具体 Sandbox 在 R2 实证工作流中落地。 |
| Alpha Confidence / 三类 Agent | 有价值，延后 | 应由样本外、成本后、稳定性和多重检验结果决定，不能由 LLM 自评分。需要先完成 R1、策略登记和纸面实盘观察。 |
| 直接用 SPY/QQQ 一股开启 Paper 闭环 | 不在本阶段执行 | 这是 E2/E3 之后的受控 Paper Canary 候选，不可越过 E1 Broker Truth、风险审批和人工许可。 |

## 三个 Issue 的覆盖关系

| Issue | 覆盖范围 | 当前状态 |
|---|---|---|
| #1 Broker Truth | TWS/Gateway、官方 `ibapi`、API/ALL 场景矩阵、真实回调、重启/断网/夜间重置、Golden Tape | 本地验证与运行器就绪；真实账户环境阻塞 |
| #2 PIT Source Qualification | 书面许可、Entitlement、真实 SEC/FRED/Massive 小样本、时间/修订/存续审计、独立 Reviewer Receipt | 本地 Probe、审计、权威门禁和运行器就绪；身份、密钥、许可及 Review 阻塞 |
| #3 Secure Onboarding | Keychain、安装/登录接力、E1/R1 Runner、严格 Schema、可搬迁 Artifact、退出分类、零秘密测试 | 本地实现完成；仍需用户完成许可证、安装、账户/密钥录入和外部权利 |

因此，Review 所说的“目前没有实现的 E1-B/R1-B 真实功能”已被三个 Issue
覆盖。没有被这些 Issue 覆盖的是 R2 之后的策略研究治理构想；它们不是本阶段
漏项，已记录为后续设计输入。

## 第一性原理后的下一阶段

系统目标不是让 Agent 给出看起来聪明的买卖建议，而是在不可伪造的时点数据、
真实成本和 Broker 真相之上，寻找可证伪、可复现、风险受限的期望收益。

依赖顺序保持为：

1. 完成 E1 Broker Truth：先证明看到的账户、订单、成交和恢复行为是真的。
2. 完成 R1 PIT Qualification：再证明研究时使用的是当时可知且有权使用的数据。
3. 进入 R2 Strategy Evidence：预注册假设，做成本后 walk-forward、purged/
   embargo 验证、容量与压力测试，并把失败试验永久留在 Cemetery。
4. 只有通过独立 Review 的候选进入 E2 影子执行，比较模型决策与 Broker
   可成交现实。
5. E3 才允许极小、人工批准、可随时撤销的 Paper Canary；Live 仍为 proposal-only。

最优策略不能预先宣称。合理的候选组合是低换手趋势/突破、事件延续和风险状态
过滤，并以净收益、回撤、换手、滑点敏感度、参数稳定性和不同市场状态下的
退化程度共同排序。LLM 只负责证据分类、反例搜索和解释审计，不产生仓位、不改
风险策略、不触碰 Broker。

## 本机验收边界

本轮实测结果：

```text
local-onboard ibkr: BLOCKED_HUMAN_ACTION
e1 run --scope api: BLOCKED_HUMAN_ACTION
r1 run --source sec_edgar: BLOCKED_HUMAN_ACTION
```

精确缺口为：安装并接受 TWS/IB Gateway 与官方 TWS API 许可证、完成 Paper
登录/2FA、将 Paper 账户写入 Keychain，以及为真实数据源写入身份/密钥并取得
书面权利。上述命令在缺口存在时均未请求 Broker 或数据供应商。

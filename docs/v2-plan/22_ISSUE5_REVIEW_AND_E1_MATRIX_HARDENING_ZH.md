# Issue #5 Review 与 E1 真实矩阵加固决策

日期：2026-07-27
基线：`47a253b`

## 结论

网页 Review 对真实进度的核心判断成立：本地工程已成熟，但真实 Broker
覆盖、Paper 执行准备和 Alpha 证明仍远未完成。Review 指出的五个 P0 均并入；
Issue #5 完整覆盖这五项以及受限 Paper fixture、回调语义和执行交接。Issue #2
继续覆盖 R1 真实 PIT 数据源资格，Issue #1/#4 继续分别作为 E1 验收权威和操作
队列。没有发现 Review 中尚未被这些 Issue 覆盖的实现缺口。

## 逐项评估

| Review 建议 | 决策 | 理由与实现 |
|---|---|---|
| 将 `47a253b` 视为从代码接入跨到真实 Broker 验证 | 接受，但收窄 | 真实 7497、官方 API、账户/持仓/订单/执行回调和五个空账户 Session 已证实；不能外推到下单、恢复或收益。 |
| 本地工程 97/100、真实 Broker 35%、Alpha 10% | 作为方向性评分保留 | 评分不是验收证据。仓库只使用可重验 Artifact、测试与外部回调判定完成度。 |
| 保持 Broker Truth、PIT、可重复性优先 | 接受 | 不为补矩阵弱化 Scope、风险、幂等或对账；Broker 仍是订单、成交、持仓和资金权威。 |
| restart/recovery/client-switch 不能靠标签计数 | 接受并实现 | 新增哈希绑定的 `E1EventReceipt` 与 `E1ScenarioCase`。标签只安排采集，Case 必须绑定真实子 Session、事件凭证、预期/观测转换和有效期；Process receipt 还必须精确匹配采集进程启动时生成并写入 Session 的 UUID。 |
| 24/30 Session 与单一连续共识矛盾 | 接受并实现 | 单一 `E1AcceptancePolicy` 同时供 Runner/Evaluator 使用；API 为 22 个同 Scope 子 Session + 2 个跨 Scope Client-switch 子 Session，总计 24；ALL 为 9+1，总计 10。不同经济状态分别判断，不再要求跨状态形成同一语义共识。 |
| client-ID switch 不能混入稳定 Scope | 接受并实现 | Client-switch Session 只作为跨 Scope 子证据；普通 Scope 绑定与阈值排除这些 Session，Case 仍要求两个 client ID、两个 Scope Hash 和兼容 Broker 经济状态。 |
| Observer denylist 应改为正向能力边界 | 接受并实现 | Observer 仅暴露九个实际使用的只读请求；所有其余 `req*`、`place*`、`cancel*`、`exercise*`、`replace*`、`bind*` 和日志级别 Broker 操作均失败关闭。测试枚举当前官方 `EClient` 表面，未来新增操作默认不可达。 |
| 区分快照可见与未来自动绑定 | 接受并实现 | Scope 分拆为当前 `reqAllOpenOrders` 快照、未来手工单绑定、未来其他 API 客户端更新三项。Client 41 只能声明本次快照，不能声明未来手工单自动绑定。 |
| 捕获订单来源字段，禁止重贴标签 | 接受并实现 | Raw callback 增加 `origin_evidence`；API Case 必须看到 `E1FIX:` 与 fixture client ID，Manual Case 必须有 Client-0/无 API namespace 的真实回调证据及明确可见路径。 |
| 建立 State Transition Topology | 接受 | 每个 Case 持有 expected/observed transition、子 Session 和事件凭证；Corpus 分开报告 per-state stability、预期转换及未解释发散。 |
| 建立 Broker Reality Coverage 面板 | 接受，复用现有 Ops 数据面 | Progress/Corpus 已输出 Session/Case 要求、实际数量、版本、跨 Scope 子证据和阻塞原因；UI 展示仍是后续只读呈现，不为本轮制造第二套真相。 |
| 添加受限 Paper fixture 降低人工交互 | 接受并隔离实现 | `scripts/e1_paper_fixture.py` 不被 runtime 导入；只连 Paper 端口，使用 9100–9199，单股/1000 美元上限、仅 STK、只允许 BUY 建仓或精确证明后的 SELL 平仓，不提供全局撤单。Permit 一次性原子消费，写前/写后凭证不可变并进入 Registry。 |
| fixture 可替代 E2/E3 Writer/Permit | 舍弃 | fixture 是测试事实生产器，不接策略、风险或 Outbox，不构成 Canary Permit、真实执行控制面或 E2/E3 授权。 |
| 自动化 TWS GUI 手工单 | 舍弃 | Manual Order 必须保留显式可信操作和真实 callback 来源；未经过独立安全/可访问性设计，不自动点击 GUI。 |
| 立即进入 E2 | 舍弃 | E1 全矩阵、真实 cancel/bracket recovery、Golden Tape 和独立 Safety Case 仍未通过。 |
| R1 先 SEC，再 ALFRED/FRED，再 Massive | 接受 | 这是最低权限/成本且最能校准 PIT 时间语义的顺序。当前三个真实凭证均未配置，因此不伪造 Probe 成功。 |

## 代码边界

- `src/hanalpha/execution/e1_scenarios.py`：类型化事件/场景证据和唯一验收政策。
- `src/hanalpha/execution/burn_in.py`：同 Scope 子 Corpus、跨 Scope 子证据、
  版本维度、逐状态稳定性和转换判定。
- `src/hanalpha/execution/ibkr.py`、`ibkr_observer.py`：Observer 正向只读
  能力和精确订单可见性/来源事实。
- `scripts/e1_paper_fixture.py`：独立 Paper 测试事实生产器；生产 runtime
  不导入，也不允许生产 broker-write 配置开启。
- `hanalpha e1 event-receipt/build-case`：从已验证 Session 构建不可变证据。

## 当前真实阻塞

TWS 7497 与 Keychain Paper 账户仍可用，但 TWS API Read-Only 当前按最近一次
人工截图为开启状态。任何 fixture Broker 写入都必须等待操作员明确关闭该选项；
在此之前不得尝试用错误回调冒充成功。R1 还缺 SEC User-Agent、FRED API key
和 Massive API key。以上均属于账户/权限事实，不在代码中猜测。

## 第一性原理后的开发顺序

1. 完成本轮本地全回归并冻结 Issue #5 代码契约。
2. 操作员关闭 TWS API Read-Only 后，以一份一用 Permit 创建一股 Paper
   持仓；采集五个 `static_position` Session 并构建稳定 Case。
3. 用另一 Permit 创建远离成交价的单股限价单，采集 API order callback，
   再用绑定 order ID/ref 的独立 Permit 修改/撤销；构建 API lifecycle Case。
4. 自动做 Han Alpha process restart；TWS restart、网络/IBKR reset、nightly
   reset 和 Manual order 只在真实事件窗口生成凭证。
5. 并行按 SEC → FRED/ALFRED → Massive 做 R1 有界真实 Probe 与权利审查。
6. 只有 E1/R1 外部证据和独立 Review 完整后，才设计 E2 durable Writer /
   Canary Permit；策略收益仍必须由真实 PIT 样本外、扣费后证据决定。

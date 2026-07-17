# 粘贴评审建议复核与 M2 取舍

日期：2026-07-18
依据：用户提供的 992 行仓库评审文字与当前 `79a3f05` 代码；当前代码优先于旧评审快照。

## 总判断

评审的方向判断仍然成立：Han Alpha 应以数据真实性、同构回放、策略证据和可恢复执行为核心，而不是复制多 Agent 投票演示。但其中“PIT 1/10、M1 尚未开始”等状态已过时：M1 已通过 76 项测试和干净哈希锁环境验证。本轮只采纳能加强 M2 正确性与审计性的建议。

## 立即并入 M2

| 建议 | 结论 | 当前证据与实现方式 |
|---|---|---|
| 修复 next-bar 入场却在当前 bar 计入权益 | 采纳 | V0.1 `BacktestEngine` 确有此时序缺陷；改为 pending entry，在下一 bar 开盘激活后才进入该时点权益 |
| 修复跳空穿越止损仍按 stop 附近成交 | 采纳 | stop-market 使用不利的 `min(open, stop)`（多头退出）再施加成本；stop-limit 跳空可不成交 |
| Backtest/Shadow/Paper 共用决策、订单、组合契约 | 采纳 | ADR 0003 固定事件顺序；M2 实现统一 `DecisionIdentity`、订单状态机、组合账本和 Parity Harness |
| Alpha Trial Registry / Strategy Cemetery | 采纳 M2 基础版 | 实验 manifest 与状态事件只追加、不提供删除；失败试验保留且不能晋级 |
| Counterfactual Ledger | 采纳通用结构 | 实验允许 `counterfactual_of`/variant 关系；Agent/Regime 具体消融待对应里程碑 |
| CI 使用哈希锁并执行完整门禁 | 采纳 | GitHub Actions 改为 Python 3.12 哈希安装并直接运行与本地相同的 preflight/verify 脚本 |
| `PROJECT_TREE.txt` 从 Git 内容生成 | 采纳 | 删除缓存/构建目录漂移，使用 Git tracked/待提交文件生成 |
| M2 只读研究结果页 | 采纳最小版 | 输出确定性 JSON + 静态 HTML 结果包，不提前引入 React/认证控制面 |
| 统一 milestone 编号 | 采纳 | 总计划对齐 V2 路线：M2 回放、M3 策略证据、M4 LLM、M5 控制面、M6 IBKR、M7 Dashboard、M8 Live Proposal |

## 延后但保留

| 建议 | 目标阶段 | 原因 |
|---|---|---|
| Cross-sectional momentum、PEAD、AI 产业链传播 | M3 | 属于可预注册策略假设；在模拟器可靠前实现会把工程错误误当 Alpha |
| DSR、PBO、walk-forward、purge/embargo | M3 | M2 先产出可信事件与结果序列；统计选择门禁必须基于冻结真实研究协议 |
| Agent Delta Gate | M4 | 需先有 M3 无 LLM 基准和冻结 OOS 结果 |
| Evidence Expiry | M4 | 属于 Evidence Service 领域，不应污染订单/组合内核 |
| Shadow Twin | M6 | 需要真实 IBKR Paper fill 才能比较；M2 只冻结可复用 fill-policy 接口 |
| 原子 reservation/outbox 与进程恢复 | M5 | M2 是单进程确定性模拟；跨进程耐久控制面需要 PostgreSQL/单写者设计 |

## 舍弃或纠正

| 建议/表述 | 结论 | 理由 |
|---|---|---|
| 现在仍是“PIT 1/10、M1 未开始” | 舍弃 | 已被 M1 实现和验证证据取代 |
| M1 fixture 应使用真实市场数据 | 舍弃 | 冻结合成 fixture 才能无许可风险、稳定验证契约；真实供应商正确性需另行授权 |
| 在 M2 直接证明策略 Alpha | 舍弃 | M2 只能证明模拟与会计机制；盈利证据属于 M3 及 forward observation |
| 为统一而让历史模拟直接复用 IBKR 适配器 | 舍弃 | 共用的是领域契约，不是外部适配器；否则会把网络/券商语义带入确定性回放 |

## M2 第一性原理设计

M2 的最小可信闭环是：发布的 PIT 快照提供当时可见事实，统一候选核心产生带哈希的决策，组合账本先原子预留，再由可替换的历史交易所产生部分/跳空/成本成交，最后以不可删除的实验 manifest 和事件 hash 固化结果。任何漂亮指标都排在会计守恒和无前视之后。

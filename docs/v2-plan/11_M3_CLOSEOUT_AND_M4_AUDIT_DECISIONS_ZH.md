# M3 收口与 M4 审计建议并入决定

## 总结

本轮审计指出的五项 P0 全部成立并已并入：晋级自报、协议与 manifest
未绑定、研究预算仅在内存、反事实未实际执行、同 bar 入场与保护止损
存在歧义。这些问题都会直接改变交易决策可信度，因此先修复再进入 M4。

## 逐条决定

| 建议 | 决定 | 理由与结果 |
|---|---|---|
| 晋级证据不可由调用方自报 | 采纳 | Promotion Service 从哈希 artifact、结果、协议阈值、签名验证报告和独立审批推导；研究者不能自批 |
| protocol 必须绑定 manifest | 采纳 | 持久 trial allocation 绑定 protocol/program/参数哈希/窗口角色；注册时原子消费 |
| 预算持久化与并发安全 | 采纳 | SQLite `BEGIN IMMEDIATE`；幂等键只保护重试，不给新试验免预算 |
| 反事实必须执行 | 采纳 | 双倍成本改变真实 FillPolicy，一 bar 延迟改变真实 proposal 时序，全部生成结果 artifact |
| 同 bar 止损语义 | 采纳 | 新建 reduce-only bracket 可在入场 bar 成交；OHLC 不可辨序时采用 stop-first 不利假设 |
| Moving-block bootstrap | 采纳 | 金融收益相关性使 IID bootstrap 过于乐观；保留确定 seed |
| 事件区间 purge | 采纳 | 用信息开始/标签结束区间消除泄漏；bar purge 不再被误称通用答案 |
| DSR 试验数来自 registry | 采纳 | research program 的持久 allocations 是搜索家族真相源 |
| 更完整 PBO 变体 | 部分采纳 | 当前 CSCV 保留并 fail closed；更复杂实现需真实样本频率和足够分区后验证 |
| 频率感知 momentum/波动率仓位/PEAD period | 延后 | 方向正确，但当前缺真实 PIT 数据语义；现在写会把合成假设固化成“策略事实” |
| 指标去重和 ledger artifact | 采纳 | exposure 三指标定义分离；journal/cash/lots 单独 JSONL 可见 |
| 改里程碑为 M3.1/M4.1 等 | 不采纳 | 保持冻结的 M0-M8 治理编号；本轮作为 M3 closeout amendment 记录 |

## M4 设计结论

M4 不是“多个 Agent 投票选股”，而是只读证据内核：冻结文档，抽取带精确
span 的 typed claim，维护过期和冲突，缓存并限制调用，再对已有量化候选做
allow/veto/abstain。没有 claim、存在注入、模型失败或预算用尽时，不生成交易。

## 明确未证明

- 未调用真实 OpenAI API，因此真实认证、429、延迟和费用验收为 BLOCKED。
- 没有真实 PIT 新闻/公告前向标签，因此 Agent on/off 只有测量框架，没有 Alpha 结论。
- 没有因此授权 Paper 或 Live 下单；M5 才开始 durable execution control plane。


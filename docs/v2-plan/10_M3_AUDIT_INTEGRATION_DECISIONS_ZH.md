# M3 审计建议复核与并入决定

## 结论

审计准确识别了 M2 的四个研究真实性缺口：历史修订可能进入撮合、保护止损尚非订单、主 CLI 仍走旧引擎、候选顺序不稳定。这些问题会直接制造错误交易决策，因此并入 M3 的 WP0，修完前不允许策略晋级。

## 立即并入

| 建议 | 决定 | 理由与实现边界 |
|---|---|---|
| Knowledge Clock / Execution Clock | 采纳 | 修订进入研究历史但不进入撮合；初始市场事件才可成交 |
| Bracket/OCO 与部分成交保护 | 采纳 | 风险预算必须对应真实可执行的 reduce-only 保护订单 |
| CLI 默认新内核 | 采纳 | `backtest` 走 replay + experiment；旧入口改名 `legacy-backtest` |
| Proposal 稳定排序 | 采纳 | 内容哈希 `candidate_id`，顺序变化不能改变 event hash |
| 不可变 ResearchContext | 采纳 | 策略只见当时历史、特征、事件和组合快照，不持有存储句柄 |
| Promotion Gate | 采纳 | 禁止普通 `COMPLETED -> PROMOTED`；必须有统计、风险、复现和人工批准证据 |
| Research Budget / Counterfactual / No-Trade | 采纳 | 把搜索次数、反事实与拒绝信号后果纳入证据，减少选择性展示 |
| 真正 Journal Accounting | 采纳 | 每个货币事件借贷平衡；FIFO lot 是操作视图，不再误称现金列表为复式账本 |

## 部分采纳或延后

| 建议 | 决定 | 理由 |
|---|---|---|
| 公司行动五阶段 | M3 建契约并阻止修订重复；真实归属验证 BLOCKED | 当前 M1 fixture 没有 announcement/ex/record/payment 四组日期，不能猜测持有人资格 |
| Momentum、PEAD、慢趋势 | M3 只做可解释基准 | 用于验证研究平台能否淘汰坏策略，不宣称已获 Alpha；PEAD 缺 PIT 预期数据时必须 abstain |
| DSR/PBO/Walk-forward/Purge | 采纳为拒绝门 | 小样本或候选不足返回 insufficient，不允许默认通过 |
| AI 产业链因果图 | 延后 M4 | 需要 Evidence Service 的引用、过期和反证契约；M3 先冻结无 LLM 基准 |
| Reality Gap Ledger | 延后 M5/M6 | 需要 Fake Broker 与真实 IBKR Paper fill 才有可比较对象 |

## 舍弃或纠正

| 建议 | 决定 | 理由 |
|---|---|---|
| 新增永久 M2.1 并把后续改成 M9 | 舍弃编号变更 | 技术问题采纳为 M3 WP0；保持已冻结 M0–M8 路线，避免治理漂移 |
| M3 直接接真实数据并寻找赚钱曲线 | 舍弃 | 真实数据许可、字段语义和样本外窗口必须先审查；本轮可完成框架和冻结 fixture 证据 |
| 一次增加大量策略/高频策略 | 舍弃 | 搜索空间越大，过拟合预算越快耗尽；当前没有盘口、队列或低延迟证据 |
| 提前 Dashboard、LLM 或 IBKR 自动化 | 舍弃 | 不改善策略证据，反而扩大误操作面 |

## 最终目的

M3 的产物不是一条最高收益曲线，而是一套能回答以下问题的决策证据：当时看到了什么、为何候选、交易成本和风险是什么、哪些反事实解释收益、样本外是否稳健、未交易是否更好，以及为何允许或拒绝晋级。

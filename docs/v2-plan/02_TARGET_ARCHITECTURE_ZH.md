# Han Alpha V2 目标架构

## 第一性原理

交易系统首先是一个**在不完整、延迟且可能矛盾的信息下管理资本风险的状态机**，不是一个聊天机器人。系统是否可信取决于五件事：在当时真正知道什么、为何产生候选、最多能亏多少、向券商提交了什么、券商最终确认了什么。LLM 只能改善第一项中的非结构化证据处理，不能成为其余四项的权威。

因此目标架构遵守以下不变量：

1. 同一输入、同一时钟、同一配置，Quant/Risk/OrderIntent 必须确定性复现。
2. 任何 LLM 输出都是带来源和版本的“证据派生物”，不是订单指令。
3. 风险预占先于提交；预占、幂等与 outbox 在一个事务中完成。
4. Broker 是订单、成交、持仓和现金的最终权威；本地状态必须持续对账。
5. `live_auto` 不存在。Live 只能生成 proposal，必须人工批准，且执行器还要有独立能力令牌。
6. 研究与运行使用同一个策略/风险核心，只替换时钟、数据游标和执行适配器。

## 采用“模块化单体 + 隔离的 Broker Gateway”

V2 不从微服务起步。微服务会在系统尚未证明 Alpha 时增加分布式状态、重试和对账面。初期用一个 Python monorepo、一个 PostgreSQL、一个 Parquet 数据湖，只有券商网关作为独立进程和权限边界。

```text
PIT ingest -> immutable raw -> normalized facts/features -> deterministic candidates
                                                        |
                                                        v
                         evidence pack -> LLM extraction/challenge cache
                                                        |
                                                        v
                              deterministic portfolio/risk policy
                                                        |
                                                        v
                     intent + reservation + approval + outbox (atomic)
                                                        |
                                                        v
                              isolated IBKR broker gateway
                                                        |
                                                        v
                         broker events -> reconciler -> projections
```

## 四个平面

### 1. 数据与研究平面

- 原始数据以内容 hash、供应商、请求参数、抓取时间保存，不覆盖。
- 规范化记录至少有 `event_time`、`published_at`、`available_at`、`ingested_at`、`effective_from/to`、`source_version`。
- Parquet/Iceberg 风格分区负责长历史；DuckDB/Polars 负责本地研究；PostgreSQL 只存元数据、任务和实验注册。
- PIT universe 不依赖今天的 S&P 500 成分：从当时可交易证券、上市/退市状态和当时流动性条件动态生成。
- Massive 可作为起步数据源；若 PIT 公司行动、安全主表和逐笔时序要求提高，再评估 Databento。供应商通过契约测试接入，不把字段语义散落在策略代码。

### 2. 策略与组合平面

- 统一 `DecisionClock`：historical、shadow、paper、live 都注入明确的 `as_of`，禁止隐式 `now()`。
- 日频/小时级生成 alpha；5 分钟仅处理入场窗口、价差、成交量参与率、停牌和订单 TTL。
- V1 三个 sleeve：
  - 横截面中期动量/相对强弱：12-1 与 6-1，多时间窗一致性，行业/市场 beta 约束。
  - PEAD/事件延续：earnings surprise、guidance delta、分析师 revision、8-K/10-Q 可得时间、异常量价。
  - 趋势回撤执行 overlay：只优化已有日频候选的入场，不单独声称 alpha。
- 加入 ETF regime/cash sleeve；波动和市场状态用于降低风险，不让 LLM预测宏观方向。
- 组合器输出目标风险和最大名义额度；风险引擎用**可执行计划价到止损价**计算风险，并计入已有持仓、挂单与预占。

### 3. LLM 证据平面

- 先由确定性代码筛选少量候选，再构造冻结的 Evidence Pack。
- 三层模型路由：廉价模型做结构化抽取；中档模型做矛盾/反证；只有冲突和高影响候选才交给最强模型裁决。
- 使用严格 JSON Schema、固定 prompt/version、温度/推理参数白名单、超时、重试、熔断、缓存、token/美元预算。
- 输出字段只允许：事件类型、事实三元组、来源引用、矛盾、风险、置信度、失效条件、`abstain`。
- 新闻、SEC 文本和网页全部视为不可信数据。模型没有券商工具、数据库写权限或执行工具；提示注入检测只是附加层，不作为核心安全边界。
- 每次模型升级先跑冻结 eval：抽取准确率、引用完整性、反证召回、Brier/ECE、延迟、成本、注入攻击和 replay drift。

### 4. 控制、执行与观测平面

- PostgreSQL 规范表：candidate、evidence_pack、assessment、order_intent、risk_reservation、approval、outbox、broker_order、execution、commission、position_snapshot、reconciliation_diff、kill_switch、audit_event。
- `order_intent + reservation + unique idempotency key + outbox` 同事务提交；只有一个持有数据库租约的 execution writer 消费 outbox。
- Broker Gateway 使用独立配置、账户白名单、clientId、Paper/Live 端口限制和运行时 capability token。
- 完整处理 IBKR orderRef/orderId/permId、openOrder/orderStatus、execDetails、commissionReport、completedOrders、reqExecutions、重连和 nightly reset。
- 对账循环比较 broker 与本地 projection；出现未知订单、未知持仓、现金差异、长期挂单或部分成交不一致时冻结新开仓。
- API 默认只绑定 localhost；写操作要求认证、CSRF/nonce、actor、原因和审计。危险操作（cancel-all、flatten）双确认且限定账户/策略订单。

## 模式不是字符串，而是能力集合

| 模式 | 市场数据 | LLM | Broker 读 | Broker 写 | 人工审批 |
|---|---|---|---|---|---|
| research/backtest | 历史 | 可选回放 | 否 | 否 | 否 |
| shadow | 实时 | 可选 | 可选只读 | 否 | 否 |
| paper_manual | 实时 | 可选 | 是 | 仅批准后 | 是 |
| paper_auto | 实时 | 可选 | 是 | 允许 | 启用前一次确认 |
| live_proposal | 实时 | 可选 | 是 | 默认否；批准服务可单独开启 | 每单必需 |

每个能力由部署配置和进程凭据同时约束。仅改变 YAML 字符串不能把研究进程变成执行进程。

## 研究有效性的门槛

1. 基准：SPY/QQQ、等权可交易 universe、简单 12-1 动量、随机组合 null。
2. 时间协议：anchored walk-forward；标签重叠使用 purge + embargo；参数选择只看训练/验证区。
3. 经济性：佣金、spread、冲击、参与率、借贷（虽 long-only 仍记录）、退市与公司行动。
4. 统计性：Deflated Sharpe、PBO、bootstrap、跨时期/行业/市值桶稳定性、参数扰动。
5. 归因：市场、行业、size/value/momentum/quality/volatility exposure 与真正的 selection alpha。
6. LLM 增量：冻结 Quant 候选，比较 no-LLM、规则证据、LLM；预注册主指标并盲测。

任何策略若只在 5 分钟 bar、少数热门股票或单一短窗口表现好，只能标记为探索结果，不能进入 Shadow。

## 技术选型

- Python 3.12、Pydantic v2、SQLAlchemy 2/Alembic、PostgreSQL 16。
- Parquet + DuckDB/Polars；初期不引入 Redis、Kafka、Kubernetes。
- FastAPI 只作为控制/查询 API；scheduler 使用显式交易日历。
- React/TypeScript 在控制面稳定后加入；首先只做 Ops 页面。
- OpenTelemetry、Prometheus 风格指标、结构化日志；本地部署可用 Docker Compose/launchd，但执行进程单实例。
- LLM provider 使用抽象层和 Responses/structured-output 能力；模型由 eval 结果选择，不在领域逻辑中硬编码。


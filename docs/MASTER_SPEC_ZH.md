# Han Alpha Trading System 全套开发总文档

## 一、项目结论

本项目不是直接复刻小红书展示系统，也不是直接 Fork TauricResearch/TradingAgents，更不是把 IBKR MCP 当成盈利策略。最终方案把三者中真正有价值的部分拆开重组：

- 借鉴 TradingAgents 的角色分工和多空反证，但不把多 Agent 对话当作 Alpha；
- 借鉴 IBKR MCP 的本地账户可观测性和只读安全思想；
- 借鉴小红书系统的策略分账、自动执行、止盈止损、复盘和仪表盘形态；
- 核心重新自建：点时数据、可回测策略、确定性风控、订单状态机、幂等、审计和 Champion-Challenger。

最终系统定位：

> 一个以盈利为目标、但以可证伪、可回放、扣除成本和风险约束为开发原则的交易研究与 IBKR 模拟盘执行系统。

任何收益目标都不能绕过以下事实：系统只能提高发现和执行有效策略的概率，不能保证盈利。判断策略是否有效的唯一标准，是严格样本外、扣除成本后的真实结果。

## 二、第一性原理

### 1. 盈利来源必须可拆解

每笔收益只能来自四类因素：

1. 可重复的信息优势；
2. 可重复的行为或资金流优势；
3. 风险承担获得的补偿；
4. 执行和组合管理优势。

LLM 本身不自动创造以上任何一项。LLM 的有效作用是：快速读取非结构化材料、识别事件、形成反方论证、检查证据冲突和整理产业链传导。

### 2. 决策与执行必须隔离

- 策略只产生 Signal；
- Agent 只产生 Assessment；
- 风控产生 RiskDecision；
- 订单服务产生 OrderRequest；
- Broker 只执行已批准订单；
- 任何一层都不能越权。

### 3. 系统必须在没有 LLM 时仍可运行

LLM 超时、限流、输出错误或遭遇提示注入时，系统必须自动否决或降级，不能凭猜测继续下单。

### 4. 券商状态是持仓和订单的最终真相

本地账本只用于审计和投影。出现差异时以 IBKR 为准，通过追加 reconciliation 事件修复，不删除历史。

## 三、当前已实现的完整链路

```text
合成数据或 Polygon
        ↓
OHLC、报价、时间戳和流动性校验
        ↓
市场状态 Regime Engine
        ↓
Breakout / Pullback / Event 三套独立策略
        ↓
Evidence Agent + Market Alignment + Skeptic
        ↓
确定性仓位与组合风控
        ↓
Paper 自动提交或生成待审批订单
        ↓
模拟券商或 IBKR TWS API
        ↓
止损、止盈、撤单、全平、回调状态
        ↓
SQLite 追加式审计账本
        ↓
FastAPI / CLI / Worker
```

## 四、代码模块

| 模块 | 目录 | 作用 |
|---|---|---|
| 领域模型 | `src/hanalpha/domain` | Bar、Quote、Signal、TradePlan、Order、Position 等强校验模型 |
| 数据层 | `src/hanalpha/data` | Synthetic、Polygon、SEC、FRED 客户端 |
| 特征层 | `src/hanalpha/features` | SMA、ATR、RSI、相对强度、成交量 Z 分数等 |
| 策略层 | `src/hanalpha/strategies` | 突破、趋势回撤、事件延续 |
| Agent 层 | `src/hanalpha/agents` | 证据覆盖、市场匹配、反方审查、可选 LLM |
| 市场状态 | `src/hanalpha/regime` | Risk-on、Neutral、Risk-off 和策略开关 |
| 风控 | `src/hanalpha/risk` | 仓位、敞口、亏损熔断、陈旧行情、重复订单等 |
| 执行 | `src/hanalpha/execution` | 保守模拟成交、IBKR bracket order、撤单和平仓 |
| 组合审计 | `src/hanalpha/portfolio` | SQLite WAL 追加式事件账本 |
| 回测 | `src/hanalpha/backtest` | 下一根 Bar 进入、成本和滑点、无前视事件过滤 |
| 编排 | `src/hanalpha/orchestrator` | 完整交易循环 |
| API | `src/hanalpha/api` | 健康、状态、运行、冻结、撤单、全平 |
| CLI | `src/hanalpha/cli.py` | doctor、demo、backtest、worker、serve |

## 五、V1 策略

### 1. Breakout

- 快均线高于慢均线；
- 当前价格突破此前滚动高点；
- 相对 SPY 强度为正；
- 成交量没有明显失真；
- 仅在允许 Breakout 的 Regime 中运行。

### 2. Trend Pullback

- 价格位于长期趋势均线上方；
- 前一根位于短均线附近或以下；
- 当前重新站回短均线；
- RSI 未过热；
- 相对强度未显著转负。

### 3. Event Continuation

- 催化剂在决策时刻已经公开；
- 分值超过阈值；
- 事件没有过期；
- 必须带完整 evidence_id；
- 价格相对强度没有反向确认。

V1 只做多、不开空、不做期权、不摊低成本、不允许同一股票叠加第二笔仓位。后续只有在独立回测和模拟盘证明加仓逻辑有效后，才开放“盈利加仓”。

## 六、Agent 权限边界

Agent 可以：

- 判断证据是否齐全；
- 识别旧闻、冲突和提示注入；
- 判断策略是否符合市场状态；
- 输出结构化反方意见；
- 引用已经提供的 evidence_id。

Agent 不可以：

- 读取券商密码或密钥；
- 计算仓位；
- 修改风险参数；
- 直接访问 Broker；
- 直接生成自由格式订单；
- 引用未提供的证据；
- 因近期盈利自行扩大仓位。

## 七、风控规则

默认 Paper 参数：

- 单笔风险 0.35%；
- 单票最大权重 7%；
- 单行业最大 25%；
- 总敞口最大 50%；
- 最多 8 个持仓；
- 单日亏损 1% 熔断；
- 滚动最大回撤 5% 熔断；
- 单笔订单最大 50,000 美元；
- 报价超过 20 秒拒绝；
- 平均成交额不足拒绝；
- 财报窗口默认拒绝隔夜；
- 不使用市价单；
- Broker 断线拒绝；
- Unknown Regime 拒绝；
- 相同 idempotency key 拒绝；
- 已持有同一股票时拒绝新开仓。

## 八、Paper 与 Live 隔离

### Paper

- 默认模拟券商；
- 可打开 `auto_submit_paper` 自动执行；
- 使用独立账本、端口和 client ID；
- 同时记录保守滑点和佣金。

### Live

- 配置校验要求 Broker 必须为 IBKR；
- `require_human_approval_live` 必须为 true；
- `auto_submit_paper` 必须为 false；
- 当前代码在 Live 下只产生待审批订单，不会自动提交；
- Live 真正启用前仍需增加认证审批面板、完整重连和券商对账。

## 九、数据和权限

### 立即运行

不需要任何权限。Synthetic 模式可以直接运行全链路。

### 接真实模拟盘需要

- IBKR Pro；
- 已开通 Paper Trading；
- TWS 或 IB Gateway；
- 官方 TWS API；
- Socket API 开启；
- Paper 端口和独立 client ID；
- 必要的 API 行情订阅；
- Polygon API Key；
- 可选 FRED API Key；
- SEC User-Agent，包含组织和联系邮箱；
- 可选 LLM API Key 和模型名。

密码、2FA、完整 API Key、私钥不得发到聊天或提交 Git。

## 十、启动方法

```bash
cd han-alpha
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
hanalpha doctor
pytest
hanalpha demo --cycles 10
hanalpha backtest --symbol NVDA --bars 1000
hanalpha worker --interval-seconds 60 --cycles 10
hanalpha serve
```

API 文档：`http://127.0.0.1:8000/docs`

## 十一、IBKR Paper 切换步骤

1. 安装并登录 IB Gateway/TWS Paper；
2. 安装相同版本官方 TWS API，使 Python 可 `import ibapi`；
3. 配置 Paper 端口，Gateway 常见为 4002，TWS 常见为 7497；
4. 先测试账户和持仓读取；
5. 使用 Polygon 作为行情与历史数据；
6. 将 `mode` 改为 `external`；
7. 将 `execution.broker` 改为 `ibkr`；
8. 保持 environment 为 `paper`；
9. 第一阶段把 `auto_submit_paper` 设为 false，只观察建议；
10. 对账正确后再设为 true；
11. 从一只高流动性股票和极小风险开始。

## 十二、回测与晋级

策略进入自动 Paper 前，建议至少满足：

- 样本外交易数超过 300；
- Profit Factor > 1.25；
- 样本外 Sharpe > 1.0；
- 最大回撤 < 12%；
- 70% 以上滚动窗口为正；
- 单一股票贡献利润不超过 25%；
- 参数上下扰动 20% 后仍为正；
- 与不使用 LLM 的基线单独比较。

Paper 进入 Live Pilot 前：

- 至少 60 个交易日；
- 没有未解决订单错配；
- Broker 成交与 Shadow Fill 差异可接受；
- 没有风控越界；
- 通过单独安全评审；
- 实盘资金和风险参数显著降低。

## 十三、当前验证结果

- Ruff：通过；
- Mypy strict：43 个源文件无错误；
- Pytest：32 项测试通过；
- 分支覆盖率：72%；
- Python compileall：通过；
- CLI doctor：通过；
- 10 周期 Demo：成功产生信号、订单、持仓和保护退出；
- Worker：成功运行；
- FastAPI 实际启动、Health 和 Cycle：通过；
- Synthetic 回测：成功运行。

Synthetic 回测收益数字仅用于验证程序链路，绝不能作为策略盈利证据。

## 十四、已覆盖的对抗性测试

- 不可能 OHLC；
- 买卖价倒挂；
- 无时区时间戳；
- 陈旧报价；
- Broker 断线；
- 重复 idempotency key；
- 已有同票持仓后重复开仓；
- Kill switch；
- Live 误开 Paper 自动提交；
- 允许 LLM 计算仓位；
- 新闻提示注入；
- LLM 输出非 JSON；
- LLM 编造 evidence_id；
- 催化剂在决策时点尚不可见；
- 止损触发；
- 全平缺少报价时拒绝猜测；
- Paper 自动提交关闭后仅生成 Proposed 订单；
- API 生命周期和操作控制。

## 十五、尚未完成且不能假装已完成的部分

- 没有你的 Polygon、IBKR、FRED 和 LLM 权限，无法进行真实端到端验收；
- IBKR Adapter 已实现 bracket order 和回调映射，但未连接你的 TWS Paper 实测；
- SEC/FRED 客户端已实现，但还没有接入具体股票 CIK 映射和每日事件流水；
- 未实现 Point-in-time 退市股票主表；
- 未实现完整 Walk-forward、Purged CV 和多重检验校正；
- 未实现认证后的手机审批；
- 未实现 Telegram；
- 未实现期权、做空和多账户虚拟分账；
- 未证明任何策略在真实数据上有 Alpha。

这些属于下一阶段工程和研究任务，不应在没有真实数据与模拟盘验证时声称完成。

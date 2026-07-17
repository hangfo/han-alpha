# Codex主任务：完成Han Alpha交易研究与IBKR模拟盘平台

## 1. 最终目标

在现有V0.1工程上，完成一个可长期运行、可回放、可审计、可进行研究级回测、可接入IBKR Paper的交易平台。系统以获得可验证的风险调整后超额收益为研究目标，但禁止把未经严格样本外验证的结果表述为已证明Alpha。

交付必须同时包含：后端、Dashboard、数据管线、回测研究框架、Paper执行、监控、测试、文档、启动脚本和验收报告。

## 2. 第一性原理约束

- 收益只能来自可重复信息优势、行为/资金流优势、风险补偿或执行/组合优势。
- 多Agent对话本身不是Alpha。
- 量化规则负责触发，LLM负责非结构化信息抽取、证据核验和反方否决。
- 仓位、止损、敞口、订单和券商调用全部由确定性代码控制。
- 所有研究必须使用point-in-time信息，明确observed_at、effective_at、ingested_at。
- 所有交易结果必须扣除佣金、点差、滑点和延迟。
- Broker为订单、成交、持仓、现金和购买力的最终真相。

## 3. 必须完成的产品范围

### A. 运行控制台Dashboard

实现React + TypeScript前端，默认仅绑定localhost，与FastAPI通信。包含：

- 明显的环境横幅：SYNTHETIC / SHADOW / PAPER / LIVE_PROPOSAL；
- 系统健康：worker、数据源、broker、LLM、数据库、最后心跳；
- 账户：净值、现金、购买力、总敞口、当日P&L、回撤；
- 持仓：策略、入场、现价、止损、目标、风险、浮盈亏；
- 订单：状态机、部分成交、拒绝原因、父子订单；
- 信号：量化条件、证据、Agent意见、风控决定；
- 研究：策略收益、成本、滑点、基准、市场状态分解；
- 控制：freeze、cancel-all、flatten-all、kill switch；
- 所有破坏性操作要求二次确认、输入确认词、CSRF保护和审计记录；
- Dashboard不能直接绕过后端风控或调用券商。

### B. 真实数据与point-in-time数据层

完成统一数据契约和缓存：

- Massive/Polygon：分钟线、报价、公司行动、参考数据、新闻；
- SEC：CIK映射、submissions、10-K/10-Q/8-K、XBRL facts；
- FRED/ALFRED：宏观序列和vintage；
- 股票主表：symbol、exchange、有效起止日期、退市、行业、CIK；
- 拆股、分红、改名、并购、退市处理；
- 数据快照、schema版本、内容hash、来源和许可元数据；
- 网络超时、重试、限流、缓存、断点续传；
- 缺失或冲突数据必须显式标记，禁止静默填充未来值。

真实数据不可用时，synthetic模式必须继续独立运行。

### C. 研究级回测与实验平台

把当前单仓位验证器升级为多资产、组合级、事件驱动回测：

- 多股票、多策略、共享资金和风险预算；
- next-bar或明确延迟成交；
- bid/ask、佣金、滑点、成交量参与率和市场冲击情景；
- 部分成交、跳空越过止损、停牌、无成交、退市；
- point-in-time股票池和公司行动；
- 基准：SPY、QQQ、等权股票池、简单动量、不使用LLM版本；
- walk-forward；
- purged/embargoed交叉验证；
- 参数扰动；
- 多重检验校正；
- 按年份、市场状态、行业、股票、策略和持仓期归因；
- 实验注册表：代码commit、配置、数据hash、随机种子、结果和artifact；
- Champion-Challenger注册和晋级规则；
- 支持缓存LLM事件标注，回测不得重复付费调用同一材料。

### D. IBKR Paper生产化

完成官方TWS API Paper适配器的真实运行能力：

- 连接、重连、心跳、pacing和错误分类；
- 启动时账户、持仓、open orders、executions和commission对账；
- client/order/perm/execution ID映射；
- 幂等提交；
- bracket父子订单和transmit语义；
- 部分成交、拒单、取消、改单、孤儿子单；
- TWS/IB Gateway夜间重置恢复；
- 本地账本与Broker差异事件化修复；
- Paper Fill和保守Shadow Fill并行记录；
- paper_manual与paper_auto严格分离；
- live_proposal永远不能自动transmit；
- 缺少本地Paper凭证时，完成mock contract测试并输出BLOCKED联调清单，禁止假称通过。

### E. Agent与证据系统

- Catalyst、Industry、Fundamental Revision、Market Alignment、Skeptic；
- 每个Agent只看到其授权证据；
- 所有输出严格JSON Schema；
- evidence_id必须来自输入；
- Prompt injection、旧闻、重复新闻、冲突来源和未来信息防护；
- LLM不可用时fail-closed或使用确定性审查；
- 模型路由、预算、缓存、超时、重试和调用审计；
- 提供Agent on/off消融测试，证明其增量而非只展示文本。

### F. 运维、可观测性和安全

- 结构化日志、correlation_id、metrics、health和readiness；
- 关键告警：broker断线、行情陈旧、账本错配、订单卡住、风控熔断；
- Telegram只发送通知和审批链接，不直接携带高权限命令；
- secrets仅来自环境或本机安全存储；
- localhost默认、远程访问必须认证、TLS和最小权限；
- 自动备份、恢复演练、数据库迁移和审计保留；
- Docker Compose开发环境；
- CI执行后端、前端、类型、覆盖率、安全扫描和构建。

## 4. 明确不做

- 不实现无人值守实盘自动交易；
- 不使用LLM直接下单或更改风控；
- 不把synthetic或短期Paper利润称为Alpha；
- 不为了视觉效果牺牲数据正确性；
- 不使用未来修订数据进行历史判断；
- 不把无法验证的外部接口标记为通过。

## 5. 技术决策

- 后端：Python 3.12、FastAPI、Pydantic、SQLAlchemy/Alembic；
- 研究：Polars或Pandas、DuckDB、Parquet；
- 主数据库：PostgreSQL，可选TimescaleDB；SQLite保留为零配置demo；
- 缓存/队列：Redis，可在本地降级为进程内实现；
- 前端：React、TypeScript、Vite、TanStack Query、Recharts；
- 前端测试：Vitest + Playwright；
- 后端测试：pytest、mypy strict、ruff、coverage；
- 运行：Docker Compose + 本机原生启动；
- 所有外部服务通过接口和fake实现隔离。

如果现有代码与技术决策冲突，优先渐进迁移，不得破坏synthetic快速启动。

## 6. 实施方式

按照`docs/codex/EXECUTION_PLAN.md`和活动执行计划逐阶段实施。每个阶段必须：

1. 先记录基线；
2. 写或更新测试；
3. 实现功能；
4. 运行完整验证；
5. 更新文档和执行计划；
6. 提交一个清晰commit。

不要在计划完成前停止，不要只生成骨架、TODO或伪实现。外部凭证缺失不应阻塞其他工作。

## 7. 最终输出

最终回复和`docs/VERIFICATION_REPORT.md`必须列出：

- VERIFIED：用命令和结果证明；
- BLOCKED：仅因真实凭证、市场订阅或本地TWS不可用；
- NOT IMPLEMENTED：必须为空，或明确解释为什么超出范围；
- 安全边界；
- 启动命令；
- Paper联调步骤；
- 测试和覆盖率；
- 已知限制；
- 下一步真实回测和Paper前向测试方案。

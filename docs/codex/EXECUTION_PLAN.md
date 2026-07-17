# Codex执行顺序

## 阶段0：基线与风险冻结

- 运行现有全部检查并记录结果。
- 创建git基线提交。
- 扫描TODO、pass、未覆盖分支和不安全默认值。
- 确认live自动提交没有任何可达路径。

## 阶段1：统一领域和数据契约

- 增加point-in-time元数据、数据快照和provider接口。
- 实现symbol master、公司行动、SEC、FRED/ALFRED持久化。
- 增加数据库迁移，同时保持SQLite demo。
- 完成数据异常和无前视测试。

## 阶段2：组合级回测与实验注册

- 多资产、共享现金、组合风险和订单撮合。
- 成本、点差、滑点、参与率、跳空和停牌。
- walk-forward、purge/embargo、参数扰动和基准。
- 实验注册、数据hash和artifact输出。

## 阶段3：Paper执行生产化

- broker连接状态机、重连和启动对账。
- open order恢复、partial fill、commission、ID映射。
- shadow fill、差异分析和夜间重置恢复。
- paper_manual与paper_auto端到端测试。

## 阶段4：Agent证据层

- 事件抽取、行业传导、基本面修正和Skeptic。
- JSON schema、来源约束、缓存、预算和审计。
- prompt injection和LLM故障测试。
- Agent消融研究接口。

## 阶段5：Dashboard和控制面

- FastAPI查询与控制API完善。
- React/TypeScript Dashboard。
- 认证边界、CSRF、审计和二次确认。
- Vitest、Playwright和API契约测试。

## 阶段6：可观测性与运维

- logs、metrics、health/readiness、heartbeat和alerts。
- Docker Compose、数据库备份恢复、迁移和运行手册。
- Telegram通知，禁止直接高权限交易命令。

## 阶段7：全面验证与发布

- 运行`./scripts/verify_all.sh`。
- 运行故障注入和并发测试。
- 启动完整本地栈并执行synthetic E2E。
- 有凭证时执行真实数据和IBKR Paper联调；无凭证则生成BLOCKED证据包。
- 更新验证报告、已知限制、项目树和发布包。

每阶段完成后更新活动执行计划中的日期、commit、命令、结果和遗留风险。

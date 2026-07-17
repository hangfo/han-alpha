# 当前V0.1与完整平台之间的差距

## 必须补齐

1. 真实point-in-time股票主表、退市和公司行动。
2. SEC/FRED客户端尚未进入生产证据流水。
3. 当前回测器是单标的/单仓位验证器，不足以评估组合Alpha。
4. 缺少walk-forward、purged CV、embargo和多重检验校正。
5. IBKR尚未在用户本地Paper会话真实联调。
6. 缺少启动对账、open order恢复、commission和夜间重置恢复。
7. 缺少可视Dashboard、认证和破坏性控制防护。
8. 缺少Agent增量消融、调用预算和永久缓存。
9. 缺少结构化可观测性、告警、备份恢复和SLO。
10. 覆盖率72%，完整平台门槛为分支覆盖率85%。

## 已决定的技术取舍

- 不直接Fork Tauric TradingAgents；只借鉴证据角色和反方审查。
- 不把IBKR MCP当策略；IBKR层只负责账户和执行。
- 不复制小红书的逐笔参数自我进化；使用Champion-Challenger。
- Dashboard先服务安全、运营和研究，不服务炫技。
- 默认本地运行，远程控制必须独立认证。
- 数据和券商适配器都必须有fake实现，CI不依赖外部服务。

## 需要用户在本地提供但不能提交到仓库

- Massive/Polygon API Key；
- FRED API Key；
- SEC合规User-Agent；
- 可选OpenAI API Key；
- IBKR Paper登录由用户在TWS/IB Gateway完成；
- 需要的IBKR市场数据订阅；
- 可选Telegram Bot Token。

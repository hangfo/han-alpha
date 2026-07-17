# Dashboard产品与安全规格

## 目的

Dashboard首先是安全和运营工具，其次才是研究展示。它不能创造Alpha，但必须缩短发现故障、解释亏损和执行紧急控制的时间。

## 页面

1. Overview：环境、系统健康、净值、P&L、回撤、敞口、告警。
2. Positions：实时持仓、策略归属、保护价格、风险贡献。
3. Orders：完整状态机、部分成交、父子订单和错误。
4. Signals：量化条件、证据、Agent审查和风控拒绝。
5. Research：策略曲线、成本、基准、regime、消融和实验。
6. Audit：不可变事件、operator、request_id和时间。
7. Settings：只允许安全的运行时设置；风险上限修改需要重启或审批。

## destructive actions

- Freeze new orders；
- Unfreeze；
- Cancel all；
- Flatten selected strategy；
- Flatten account；
- Kill switch。

要求：权限校验、CSRF token、确认词、当前环境和影响范围预览、幂等键、审计、结果回读。Live proposal环境禁止显示自动提交控件。

## 前端验收

- TypeScript strict；
- 关键组件单元测试；
- Playwright覆盖启动、查看状态、freeze、cancel和flatten确认流程；
- 无障碍基础检查；
- 错误、loading、empty和stale状态；
- 新闻/Agent文本转义，防XSS；
- 不在浏览器保存Broker或API密钥。

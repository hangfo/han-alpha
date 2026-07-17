# 完整测试与对抗矩阵

## 数据

- 非法OHLC、负成交量、NaN/Inf、重复bar、乱序bar；
- 无时区时间戳、DST、市场假日、提前收盘；
- 拆股、现金分红、改名、并购、退市；
- SEC发布时间晚于文件期末；
- ALFRED修订值与首次发布值差异；
- API限流、分页中断、重复页、schema漂移；
- 缓存损坏、hash不一致、部分下载。

## 策略和回测

- look-ahead、survivorship、selection和label leakage；
- next-bar执行与同bar错误成交；
- 点差扩大、滑点恶化、跳空越过止损；
- 停牌、无成交量、部分成交、退市归零或现金结算；
- 多策略同时争用现金和风险预算；
- 同股票冲突信号；
- 参数扰动、随机seed、窗口边界；
- Agent开启/关闭消融。

## Broker

- 初次连接失败、断线、半连接、心跳超时；
- 重复orderStatus、execDetails乱序、重复execution；
- client ID冲突、order ID回退、permId重映射；
- parent成交前child状态异常；
- partial fill后取消；
- 拒单、保证金不足、价格增量非法；
- 夜间reset和进程重启；
- 本地账本与Broker持仓不一致；
- kill switch并发触发。

## LLM和证据

- prompt injection；
- malformed JSON和schema缺字段；
- 虚构evidence_id；
- 旧新闻重复包装；
- 来源冲突；
- 超时、429、5xx、空响应；
- 试图计算仓位、扩大风险或调用Broker；
- 高token材料和预算耗尽；
- 缓存污染和跨标的串证据。

## API和Dashboard

- 未授权访问；
- CSRF；
- 重放destructive action；
- 双击flatten/cancel；
- 页面陈旧状态；
- backend断线；
- 错误环境横幅；
- 空账户、无持仓、无信号；
- mobile viewport；
- XSS内容来自新闻或Agent文本。

## 运维

- 数据库不可用、磁盘满、只读文件系统；
- Redis不可用降级；
- worker崩溃和自动恢复；
- 备份损坏与恢复验证；
- 日志中密钥脱敏；
- 多进程并发和锁；
- 时钟漂移；
- Docker重启后状态恢复。

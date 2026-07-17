# M1 冻结 PIT Fixture 规范

日期：2026-07-18
状态：M1 测试输入规范；尚未生成数据文件

## 目的

用完全合成、可提交、无市场数据许可风险的小数据集，证明 PIT 查询、symbology、公司行动、迟到/修订策略、DST 和 snapshot replay。Fixture 不用于收益评价。

## 时间与日历

- 所有持久化时间使用 UTC、timezone-aware ISO 8601。
- 交易所语义使用 `America/New_York`，覆盖 2024 年春季和秋季 DST 切换附近日期。
- 决策点至少包含开盘前、RTH 内、收盘后和非交易日。
- 故意提供一条 naive datetime，预期 ingestion 失败。

## 合成证券

| instrument_id | 情景 | 预期性质 |
|---|---|---|
| `inst-alpha` | ticker `ALFA` 后改为 `BETA` | 改名前查询不到 `BETA`，改名后查询不到活动的 `ALFA` |
| `inst-delisted` | ticker `DELI` 后退市 | 历史 snapshot 可见，退市后活动 universe 不可见 |
| `inst-reused` | ticker `ALFA` 在更晚日期被另一实体复用 | 相同 ticker 不得合并 instrument history |
| `inst-split` | ticker `SPLT`，发生 2-for-1 split | raw price 不改写；调整视图按事件重放 |
| `inst-dividend` | ticker `DIVD`，现金分红 | raw/total-return 视图分离且政策可追溯 |

## 数据记录

每个证券生成少量日线与分钟线记录，并至少包含：

- 正常准时记录；
- `event_time < available_at < ingested_at` 的迟到记录；
- 同一 `source_record_id` 的更高 `source_revision`；
- 字节相同的重复输入；
- 主键相同但字节不同的冲突输入；
- `available_at` 晚于两个历史决策点的记录；
- 一条 orphan corporate action；
- 一组重叠 ticker validity intervals。

## 固定断言

1. 任意返回记录均满足 `available_at <= as_of`。
2. ticker 只在其 validity interval 内解析到对应 `instrument_id`。
3. 退市不会删除历史记录，也不会留在退市后的 active universe。
4. ticker 复用不会连接两家实体的价格或公司行动。
5. 原始价格永不因复权而改变；调整结果带 policy/version。
6. 字节相同的重复输入幂等；冲突输入和重叠区间阻止 snapshot 发布。
7. 未知/naive 时间、orphan action、失败质量报告均 fail closed。
8. 相同 fixture、schema、代码和配置重复运行得到相同 snapshot hash。
9. 任一输入字节、schema version 或 normalization config 改变都会改变 snapshot hash。

## 文件组织

M1 实现时创建：

```text
tests/pit/fixtures/v1/raw/
tests/pit/fixtures/v1/expected/
tests/pit/fixtures/v1/manifest.json
tests/pit/fixtures/v1/README.md
```

Manifest 必须列出每个 fixture 文件的 SHA-256、schema version、生成器版本和预期失败/成功分类。Fixture 生成器必须确定性、固定 seed，生成后文件进入版本控制；测试不得在运行时偷偷重写 golden 数据。

## 权限边界

本 fixture 不复制真实行情、公司名称、公告、供应商 payload 或账户数据。M1 开发不需要任何 API key。若后续引入真实样本，必须先单独审查供应商许可、保存期限、再分发限制、调用次数和成本。

# M0 收口、PIT 入口判断与平台实现方案

日期：2026-07-18

## 结论先行

- **M0 代码与安全边界：已实现。** 基线已用 Git tree 冻结；模式、写能力、API、决策时钟和模拟限价的 P0 修复已落地。
- **M0 验证门：尚未完全通过。** 当前机器缺少完整 dev toolchain，不能诚实声称 ruff、mypy、完整 pytest 与 build 已通过。
- **现在进入 M1 PIT 代码：NO-GO。** 先恢复可复现开发环境并让 `scripts/verify_all.sh` 全绿。
- **平台开发方向：GO，但顺序锁定为“数据内核先行”。** M0 已是平台内核开发的开始；M1 只做本地 fixture 驱动的 PIT 数据纵向切片，不先做 Dashboard、不接 IBKR、不加交易 LLM。
- **外部数据采购/调用：仍为 NO-GO。** 供应商、调用量、费用、许可和缓存边界需另行授权。

## 第一性原理

交易系统的输出价值可近似写成：

`可执行优势 = 时间正确的数据 × 可证伪策略 × 真实成本后的组合结果 × 可恢复执行`

其中任何一项为零，更多 Agent、UI 或自动化都不会产生可信优势。因此实施顺序必须是：

1. 安全权限和时间语义；
2. PIT 数据事实；
3. 同构组合回测和成本；
4. 预注册策略证据；
5. 证明有增量后才引入 LLM Evidence Service；
6. 可恢复的 Paper 执行；
7. 最后建设操作台。

这也是为何 M1 不应从“行情接口能返回数据”开始，而应从“任意历史 `as_of` 只能看到当时可得且当时存在的证券和事实”开始。

## M1 最佳架构：模块化单体 + 不可变数据层

现阶段不需要微服务、Kafka 或 Kubernetes。推荐一个可拆分但先单进程运行的模块化单体：

```text
Vendor/Fixture adapters
        |
        v
Immutable raw envelope  ---> content hash / source / received_at
        |
        v
Canonical PIT records   ---> event_time / available_at / valid interval / revision
        |
        v
Snapshot catalog        ---> dataset + schema + code + config hashes
        |
        v
AsOfRepository          ---> mandatory available_at <= as_of predicate
        |
        v
Feature/strategy ports  ---> same contracts for backtest, shadow and paper
```

建议存储边界：

- Raw 与 canonical 数据：分区 Parquet，append-only；
- 本地分析与质量查询：DuckDB；
- snapshot/lineage/quality 元数据：先 SQLite，执行状态在 M5 再迁 PostgreSQL；
- 小型冻结 fixture：随测试版本化，不包含受许可限制的生产数据；
- 每个 snapshot 用内容 hash 标识，禁止“同名数据集原地更新”。

## M1 领域契约

每条可用于决策的记录至少有：

- `instrument_id`：稳定内部 ID，不以 ticker 作为主键；
- `event_time`：经济事件或市场事件发生时间；
- `available_at`：策略最早可获得时间；
- `ingested_at`：本系统接收时间；
- `valid_from` / `valid_to`：证券名称、ticker、上市状态等有效区间；
- `source`、`source_record_id`、`source_revision`；
- `payload_hash`、`schema_version`、`snapshot_id`。

强制查询不变量：

```text
available_at <= decision.as_of
valid_from <= decision.as_of < valid_to
snapshot_id is immutable
```

价格复权不能覆盖原始价；拆股、分红、ticker 变更和退市作为版本化事件保存。研究可选择 raw/adjusted 视图，但必须在实验 manifest 中声明。

## 代码规划

M1 应以一个小型、可验收的纵向切片实现，建议文件边界：

```text
src/hanalpha/pit/models.py          # bitemporal records and stable IDs
src/hanalpha/pit/clock.py           # AsOfContext using the M0 DecisionClock
src/hanalpha/pit/raw_store.py       # append-only raw envelopes
src/hanalpha/pit/canonical_store.py # canonical Parquet writer/reader
src/hanalpha/pit/catalog.py         # snapshot manifest and lineage hashes
src/hanalpha/pit/repository.py      # mandatory as-of query API
src/hanalpha/pit/quality.py         # uniqueness, gaps, lateness, revisions
src/hanalpha/pit/symbology.py       # listing intervals and ticker aliases
src/hanalpha/pit/actions.py         # split/dividend/delist events
src/hanalpha/data/fixtures.py       # deterministic local adapter only
src/hanalpha/cli.py                 # pit ingest-fixture/snapshot/quality commands
tests/pit/fixtures/                 # frozen tiny dataset
tests/pit/test_as_of_queries.py
tests/pit/test_symbology.py
tests/pit/test_corporate_actions.py
tests/pit/test_snapshot_replay.py
tests/pit/test_quality_fail_closed.py
```

实施顺序：

1. 先写 schema、查询不变量和失败测试；
2. 实现 fixture adapter 与 raw envelope；
3. 实现 canonical normalization 和 symbol master；
4. 实现 snapshot catalog/hash；
5. 让一条简单价格特征通过 `AsOfRepository` 回放；
6. 加入重复、迟到、修订、DST、ticker 变更、拆股、退市测试；
7. 输出数据质量报告和可复现实验 manifest；
8. 最后才评估真实供应商适配器。

## M1 入口条件

必须全部满足：

- `scripts/verify_all.sh` 全绿，M0 无未解释回归；
- Python 版本与 dev 依赖可复现，建议新增锁文件或 hash-locked requirements；
- `paper.yaml` 保持 `paper_manual`、Broker/API 写能力保持 false；
- M1 exec plan、schema ADR、数据许可边界已审阅；
- 不需要真实 API 的 frozen fixture 已定义；
- P0 风险仅剩 M1 本身要解决的 PIT 缺口，没有新的执行安全 P0。

## M1 退出条件

- 当前成分股不能回填历史；上市、退市和 ticker 变更按有效区间重放；
- 公司行动计算可由原始事件复现；
- naive datetime、DST 歧义、迟到/重复/修订数据均 fail closed 或有显式政策；
- 任一记录 `available_at > as_of` 时不可被查询到；
- 同一 raw snapshot + schema + code 产生相同 canonical/feature hash；
- 数据质量失败会阻止 snapshot 发布；
- 全过程仍不触发 Broker、LLM 或外部付费调用。

## 明确延后

- 组合回测、部分成交和容量模型：M2；
- 策略参数与真实 alpha 结论：M3；
- LLM agent 选择、prompt 和消融：M4；
- 单写者、reservation/outbox/reconciler：M5；
- IBKR Paper：M6；
- Dashboard：M7。

公开最新交易 Agent 研究只支持“证据服务、任务专用评测、forward observation”的方向，不支持让 LLM 获得执行权或在 PIT/成本/回测缺失时宣称 alpha。相关来源与设计映射已冻结在 `06_PUBLIC_EVIDENCE_REGISTER.md`。

# E1/R1 Review逐条决策与证据权威收口

基线：`778fac41b95efde6e0a8551cd455732754e58b54`

## 总结

Review指出的核心缺口成立：`Hash格式正确`、`Profile写VERIFIED`、`有30个
Session`都不等于外部事实成立。本轮只增加证明链所必需的本地能力，不增加
Broker写权限、策略自由度或自动交易能力。

## 逐条决策

| Review项目 | 决策 | 实现或理由 |
|---|---|---|
| P0-1 Manifest未验证自身ID和调用绑定 | 并入 | `verify_burn_in_manifest()`重算Manifest ID、文件Hash，交叉检查Certificate、Scope、Account、Normalization、Semantic Hash、Watermark及Tape内唯一Session；已有目录必须与当前完整Manifest完全一致。 |
| P0-2 Safety Case只检查64位Hash | 并入 | 新增Artifact Registry/Resolver；每次解析都重新检查文件存在、SHA256、Artifact类型、Schema/Canonical ID和Policy结果。Safety Case保存逐Artifact五维解析结果。 |
| P0-3 HMAC无审批隔离 | 并入 | HMAC验证被Ed25519替代；运行时只读取公钥，私钥只允许存在于离线Reviewer流程。本仓库不提供在线签发端点。 |
| P0-4 Reviewer只是文本 | 并入 | Safety Case要求RISK与EXECUTION两个不同Reviewer、不同公钥的不可变签名收据，绑定Case Hash、Decision和Review Time；重复Reviewer/Key拒绝。 |
| P1-1 Capture正常结束不等于验收 | 并入 | Capture继续保存成功或失败事实；新增`ibkr-burn-in-evaluate`生成Corpus，BLOCKED时退出码2。 |
| P1-2 Manifest关键字段可空 | 并入 | Manifest v2新增`capture_complete`、`safety_case_eligible`和具体拒绝原因；缺Commit、TWS/API版本、Vote或完整证书仍保存但不合格。 |
| P1-3 Manifest缺Vote/Equivalence/Promotion | 并入 | 每个Session绑定Disposition、投票后Consensus、Equivalence Receipt及Hash、Candidate状态和Authority晋级事实。 |
| P1-4 30次连接不能代替矩阵 | 并入 | Corpus按API/ALL Scope使用不同最小Session和Coverage Matrix；缺Process/TWS重启、网络恢复、Nightly Reset、Client切换、API或Manual Order场景即BLOCKED。 |
| P1-5 Profile可自报VERIFIED | 并入 | Profile状态不再是权威；每个检查必须引用已注册、未过期、类型正确的Artifact及独立Ed25519 Reviewer Receipt，否则BLOCKED。 |
| P1-6 `ready_sources`误导 | 并入 | 改为`credentials_present_for`；`access_ready_for`保持空，直到License与Entitlement Artifact通过。 |
| P1-7 SEC User-Agent仅检查长度 | 并入 | 要求项目标识和非占位联系邮箱，拒绝`example.com`和疑似Token；Artifact只保存User-Agent Hash及节流策略Hash。 |
| E1-A Artifact Registry | 并入 | 实现限定类型、不可变注册、文件重验和Policy解析；Registry状态本身不能替代文件和签名。 |
| E1-B Corpus Builder | 并入 | 同一Corpus禁止混合Account、Scope、Commit、Config和Normalization；汇总Drop、Writer Error、Reconciliation、Reset、稳定性、版本和Coverage。 |
| E1-C真实Burn-in矩阵 | 外部BLOCKED | 代码已能表达并验收场景；本机无官方`ibapi`、TWS/Gateway、Paper Account，不能生成真实结果。 |
| E1-D Golden Tape与变形测试 | 保留下一外部阶段 | 先采真实Tape再确定Numeric和Order ID规范化；不制造假Golden Tape。 |
| E1-E Callback Truth Map | 保留下一外部阶段 | 必须从真实Callback覆盖生成，不能按文档预填为AUTHORITATIVE。 |
| R1-A许可边界 | 并入合同 | License Receipt成为固定Artifact类型；没有实际合同/条款仍BLOCKED。 |
| R1-B小样本 | 外部BLOCKED | 不自动购买或大规模下载；先由用户选择Plan和许可，再运行有界样本。 |
| R1-C Qualification Evidence Registry | 并入 | Check Code引用Artifact与Reviewer Receipt，含失效时间；调用方文字不产生资格。 |
| R1-D三层资格 | 修改并入 | 凭据存在不叫ACCESS_READY；资格报告只产生BLOCKED、RESEARCH_QUALIFIED、PROMOTION_QUALIFIED，生产晋级只接受最后一级。 |
| R2三类低自由度策略 | 保留不启动 | R1未达PROMOTION_QUALIFIED前不优化收益；之后只跑慢趋势、横截面动量/突破、PEAD。 |
| E2 Permit原子消费 | 延后 | 公钥验证基础已完成；Permit表和Claim原子消费必须等E1真实Corpus通过，避免提前形成Writer路径。 |
| E3首笔1股Canary | 延后 | 真实Cancel、Bracket、Recovery和Permit均未通过；当前实现会越权。 |
| Evidence Merkle Root | 暂不引入树结构 | Corpus Canonical ID已经把有序Session Manifest Hash集合绑定为Root；Artifact数量/分组稳定后再引入Merkle Proof，当前收益不足。 |
| 双层签名 | 部分并入 | Reviewer签名已实现；Producer签名等真实采集主机身份确定后再实现，当前文件Hash和Git/Config绑定保留。 |
| Vendor Drift Sentinel | 进入R1-B退出门 | 需要真实固定样本和合法重抓权限，本地先记录契约，不伪造监控结果。 |
| PIT Negative Controls | 进入R2 | 随机、时间打乱、简单Momentum、等权和Evidence On/Off均列为R2硬门。 |
| Evidence Decay | 并入 | Qualification Evidence和Reviewer Receipt必须有Expiry；Safety Case仍为短期；License按合同变化失效。 |

## M7-B.1后的最终命名

不恢复M7-B.x版本号，按可证明事实拆分工作包：

```text
E1-A Evidence Integrity          [本地完成]
E1-B Broker Acceptance           [真实IBKR阻塞]
        ↓
E2 Canary Authorization          [Verifier完成，Permit阻塞]
        ↓
E3 Paper Manual Execution        [阻塞]

R1-A Qualification Authority     [本地完成]
R1-B Source Acceptance           [许可/样本阻塞]
        ↓
R2 Friction-aware OOS Evidence   [阻塞]

E3 + R2 → M8 Live Proposal Review
```

M8仍然只有Proposal权限，不存在`live_auto`。

## 第一性原理资源分配

下一阶段40%投入真实Broker矩阵，40%投入许可与有界数据样本，10%投入外部
Artifact审查，10%投入运维文档。禁止新增Agent、RL、期权/HFT、自主调参、
浏览器交易按钮或自动实盘。

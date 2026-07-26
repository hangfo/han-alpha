# E1-B/R1-B Issue #4 审阅决策与真实接入操作手册

更新：2026-07-26

## 结论

网页审计准确指出：工程闭环已经接近完成，但工程评分不能替代真实
Broker、真实许可、真实PIT样本、独立签名和真实收益证据。当前最优路径不是扩展
Agent或策略，而是完成 E1 Broker Truth、R1 PIT Qualification，再进入 E2/E3
Paper Canary 和 R2 摩擦后研究。

Issue #1 覆盖 Broker Truth，Issue #2 覆盖 PIT Rights/Qualification，Issue #4
覆盖最小人工门和 Codex 执行队列。三者覆盖剩余真实验收，但网页审计提出的四项
本地加固和操作面板不是 Issue #4 的独立验收项；本轮已将其实现，不能据此关闭
#1、#2 或 #4。

## 网页审计逐条处置

| 建议 | 决定 | 理由/落地 |
|---|---|---|
| Keychain SecretProvider | 保留 | 正确；值不进入参数、日志、Artifact或Git。 |
| `local-onboard`傻瓜化 | 接受并增强 | 保留检查/启动/等待；新增本人接受License后的安全官方ZIP安装命令。 |
| E1/R1 Runner状态机 | 保留 | 固定矩阵、可恢复、单次有界执行、非零阻塞退出是正确抽象。 |
| Artifact Registry严格解析 | 保留 | 文件、哈希、类型、Schema、Policy均为资格必要条件。 |
| P0-1 Secret不经子进程环境 | 接受并实现 | 子进程Secrets改走一次性stdin JSON IPC；清除继承Secret环境，仍保留字段白名单和大小上限。 |
| P0-2 账户Hash强化 | 接受并实现 | Preflight/Session增加`broker + paper/live + host/port实例 + account hash`的组合身份；Corpus绑定并拒绝篡改。 |
| P0-3 R1 Bundle仍unsigned | 接受事实，外部阻塞 | 不允许本仓库自签冒充独立Data Owner/Research Reviewer；继续输出待独立签署Bundle。 |
| P0-4 License Artifact模板 | 接受并实现 | 增加Massive许可收据、权限探针、SEC/FRED政策模板；默认BLOCKED且claim精确绑定。 |
| External Acceptance Dashboard | 接受并实现 | 只读汇总Registry内已验证E1 API 24/ALL 10 Session和R1样本，不触发外部请求。 |
| Safety Case签名器 | 暂缓运行时实现 | 运行时自签会破坏独立审查边界；待确定独立签署人和离线密钥保管流程后单独实现。 |
| External Evidence Passport | 延后 | 真实E1/R1证据为空时只是自发徽章；先取得权威证据，再生成可验证Passport。 |
| 暂停新Agent/RL/自动交易 | 接受 | 当前瓶颈是证据和权限，不是模型数量；避免扩大不可验证攻击面。 |
| 96/100工程评分 | 仅作审计意见 | 不是Acceptance Gate；真实Broker/PIT/Alpha仍分别BLOCKED/NOT ESTABLISHED。 |

## 本轮额外安全设计

1. 官方TWS API ZIP只从用户已下载的本地文件安装；CLI要求显式
   `--license-accepted`，拒绝路径穿越、符号链接和非`twsapi*.zip`。
2. 子进程Secret不在argv/env中出现；stdin通道仅对子命令内部启用，未知字段、
   空值和超过64 KiB的载荷全部拒绝。
3. 组合Broker身份防止两个Paper账户、Paper/Live、TWS/Gateway实例之间的
   Burn-in证据误合并。
4. Dashboard只统计Registry中`VERIFIED`且满足严格解析的Artifact；缺失即
   BLOCKED，不把计划数量当真实数量。
5. 这批改动不改变Broker写权限、不增加外部请求，也不改变回测热路径。

## 你的Mac当前事实

- Apple M3 Pro / arm64，适用Apple Silicon安装包；
- 未发现TWS或IB Gateway；
- 未发现本地TWS API压缩包，当前虚拟环境不能`import ibapi`；
- `127.0.0.1:7497`和`:4002`均未监听；
- Keychain中尚无Han Alpha Paper Account；
- 因此没有发起任何Broker或Vendor请求。

## IBKR从零到真实Paper连接

### A. 准备账户和2FA

1. 先确认IBKR账户已经批准，并能进入Client Portal。Paper账户号通常以`DU`
   开头，可在TWS账户窗口查看。不要把账户号、密码、Cookie或2FA发到聊天、
   Issue或截图。
2. 手机从官方App Store/Google Play安装“IBKR Mobile”。
3. Client Portal登录后进入右上角用户菜单：
   `Settings > Security > Secure Login System`，选择IBKR Mobile，按官方页面
   扫描二维码并完成手机验证：
   <https://www.ibkrguides.com/securelogin/sls/activating-two-factor-via-mobile.htm>
4. 此后登录时先输入用户名/密码，再在手机通知中点`Authorize/Approve`，
   通过Face ID、指纹或PIN：
   <https://www.ibkrguides.com/securelogin/sls/using-two-factor.htm>

这些步骤必须由账户本人完成。不要让浏览器自动化、Codex或第三方代为确认。

### B. 安装TWS

本机推荐“**TWS Latest / Apple Silicon**”，而不是IB Gateway：TWS对首次配置和
手工创建Paper场景更直观；Latest可与当前含Python的API Latest 10.48配套。官方
下载页：

<https://www.interactivebrokers.com/en/trading/download-tws.php?p=latest>

当前Apple Silicon Latest直链：

<https://download2.interactivebrokers.com/installers/tws/latest/tws-latest-macos-arm.dmg>

1. 在官方页面选择Latest和Apple Silicon；
2. 下载DMG，打开后按安装器提示完成安装；
3. macOS若拦截，先核对下载来源和开发者签名，再到
   `System Settings > Privacy & Security`允许官方应用；不要绕过未知签名；
4. 启动TWS，选择**Paper Trading**，输入本人用户名/密码并在手机完成2FA；
5. 不要使用TWS登录界面的“Read-Only Login”。本文后面的“API Read-Only”是
   另一层设置。

### C. 配置真实API Socket

在TWS Mosaic进入`File > Global Configuration > API > Settings`
（Classic界面为`Edit > Global Configuration`）：

1. 勾选`Enable ActiveX and Socket Clients`；
2. Socket port设为`7497`（TWS Paper默认；TWS Live是7496，Gateway
   Paper/Live默认4002/4001）；
3. 仅信任本机`127.0.0.1`，不要开放公网端口；
4. Han Alpha使用专用Client ID `41`；
5. 在E1有界采集窗口启用API日志和Detail级别，采集完成后按需降低；
6. API/账户持仓阶段勾选`Read-Only API`。这仍然是真实、已认证、可读取账户的
   Paper连接，并不是模拟或“只看页面”；
7. ALL Scope需要观察TWS手工订单时，按Issue #4步骤临时取消`Read-Only API`。
   Han Alpha Observer仍在代码层拒绝`placeOrder/cancelOrder/reqGlobalCancel/
   exerciseOptions`。完成后立即重新勾选。

官方设置说明：
<https://www.ibkrguides.com/traderworkstation/api.htm>

### D. 接受并安装官方TWS API

只使用IBKR官方页，不要直接安装PyPI上名称相似的第三方包：

<https://interactivebrokers.github.io/>

截至2026-07-26，Stable API为10.45，但官方Mac/Unix Stable不含Python；
Latest API为10.48且Mac/Unix包包含Python。因此本机使用Latest 10.48，并让TWS
保持相同代际。当前官方ZIP：

<https://interactivebrokers.github.io/downloads/twsapi_macunix.1048.01.zip>

在网页阅读License并由本人点击`I Agree`下载后执行：

```bash
cd /Users/rich/han-alpha
source .venv/bin/activate
hanalpha local-onboard install-ibapi \
  --archive ~/Downloads/twsapi_macunix.1048.01.zip \
  --license-accepted
python -c 'from ibapi.client import EClient; print("official ibapi import OK")'
```

版本更新时文件名可能变化，应以官方页面为准。

### E. 把Paper账户写入Keychain并连接

在TWS已登录Paper并开启7497后：

```bash
cd /Users/rich/han-alpha
source .venv/bin/activate
hanalpha local-onboard set-secret --name ibkr-account
```

终端会隐藏输入。只输入Paper账户号，不输入密码或2FA。然后：

```bash
hanalpha local-onboard ibkr --read-only-attested --github-summary
hanalpha e1 run --scope api --dry-run --github-summary
hanalpha e1 run --scope api --execute --read-only-attested --github-summary
```

首次真实连接时保持TWS在前台，留意并批准“允许来自本机的API连接”提示。不得把
TWS/API端口转发到互联网。

### F. ALL Scope和后续Paper交易边界

1. API Scope通过后，Codex按固定场景逐次运行，不能靠重复空账户连接凑数量。
2. ALL Scope由你在TWS GUI创建Issue #4指定的精确Paper事件；Han Alpha只观察。
3. 只有E1完整Corpus、独立Safety Case和E2 Canary授权后，才进入E3
   Paper Manual Execution。当前不会为了“真实连接”提交订单。
4. Live始终proposal-only并需人工批准；本流程不会开启无人值守Live交易。

## Issue覆盖与下一阶段

| 剩余项 | Authority |
|---|---|
| 真实登录、Callback、重启/断网/夜间Reset、API/ALL Corpus | Issue #1 + #4 |
| Massive/SEC/FRED许可、权限、真实样本、独立签名 | Issue #2 + #4 |
| Secret IPC、组合Broker身份、许可模板、验收看板 | 本轮本地实现 |
| 离线独立Signer和Evidence Passport | E1/R1真实证据及审查人就位后 |
| E2/E3 Paper Canary | E1通过后 |
| R2摩擦后OOS/Forward研究 | R1通过后 |
| M8 Live Proposal评审 | E2/E3/R2通过后 |

真实功能尚未全部跑通的原因不是Issue遗漏，而是四个不可替代的人类/外部事实：
License接受、账户登录/2FA、供应商合同/付费权限、独立Reviewer签名。在这些事实
出现前，系统必须报告BLOCKED，不能伪造成PASS。

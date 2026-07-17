# 用户在Codex开始前只需完成的操作

## 1. 推荐使用方式

在Mac上的Codex桌面应用中打开本项目文件夹。需要真实IBKR Paper联调时，必须让Codex运行在能访问本机TWS/IB Gateway的本地环境；云端隔离任务通常不能访问`127.0.0.1`上的券商会话。

## 2. 初始化仓库

```bash
unzip han-alpha-codex-ready.zip
cd han-alpha-release
./scripts/bootstrap_codex.sh
```

脚本会创建虚拟环境、安装开发依赖、运行基线检查，并在当前目录不是Git仓库时初始化Git和建立基线commit。

## 3. 打开Codex并粘贴主提示词

完整提示词位于：

```text
docs/codex/CODEX_PROMPT_ZH.md
```

不要把整个旧会话再次粘贴给Codex。仓库文档已经是唯一事实来源，重复长对话会浪费上下文并增加冲突。

## 4. 密钥和权限

先不填写密钥也能开始全部开发和synthetic测试。需要真实联调时只在本机`.env`填写：

- Massive/Polygon；
- FRED；
- SEC User-Agent；
- 可选OpenAI API；
- 可选Telegram；
- IBKR由你在TWS/IB Gateway中人工登录，不把密码交给Codex。

## 5. IBKR Paper联调前

- 登录IBKR Paper；
- 开启Socket API；
- 确认Paper端口，Gateway常见4002，TWS常见7497；
- 确认市场数据订阅；
- 先以paper_manual运行和对账；
- 对账稳定后才允许paper_auto。

## 6. Codex意外停止

不要重新从头开始。新开Codex任务，粘贴`docs/codex/CODEX_RESUME_PROMPT_ZH.md`。它会从活动执行计划和Git状态恢复。

## 7. 完成后独立审计

建议新开一个Codex任务，只做审计，不继续美化，粘贴`docs/codex/CODEX_FINAL_AUDIT_PROMPT_ZH.md`。主实现者和审计者分离，可以减少“自己验证自己”的盲点。

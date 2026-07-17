# 环境、权限和密钥

## 推荐执行环境

IBKR Paper真实联调必须在能访问本机TWS或IB Gateway的Codex本地任务中进行。云端隔离环境无法直接访问用户Mac上的本地券商会话时，只能完成fake/contract测试。

## 环境文件

复制`.env.example`到`.env`，只在本机填写。仓库、提示词、Issue和日志中不得包含完整密钥。

建议变量：

```text
HANALPHA_ENV=synthetic
DATABASE_URL=sqlite:///./.state/hanalpha.db
REDIS_URL=
POLYGON_API_KEY=
FRED_API_KEY=
SEC_USER_AGENT=Name email@example.com
OPENAI_API_KEY=
OPENAI_MODEL=
IBKR_HOST=127.0.0.1
IBKR_PORT=4002
IBKR_CLIENT_ID=15
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

## 权限升级顺序

1. synthetic；
2. 历史数据只读；
3. 实时行情只读；
4. IBKR Paper只读；
5. Paper manual；
6. Paper auto；
7. Live proposal只读与人工审批。

不得跨级直接进入Paper auto，更不得建立live auto。

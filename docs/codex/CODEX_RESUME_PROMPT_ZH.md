你正在继续`han-alpha`仓库中一个尚未完成的长任务。不要从头重写，也不要只总结。

请依次读取：

1. `AGENTS.md`
2. `CODEX_START_HERE.md`
3. `docs/exec-plans/active/001-complete-platform.md`
4. `docs/codex/ACCEPTANCE_CRITERIA.md`
5. `git status`、最近commit和现有测试结果

先运行`./scripts/preflight.sh`，识别最后一个已完成milestone和当前失败点；然后从活动执行计划中第一个未完成项目继续实现，直到全部验收标准满足。保留已有正确实现，不得回退安全边界，不得重新询问已经写入文档的决策。

完成前运行`./scripts/verify_all.sh`，更新活动执行计划和`docs/VERIFICATION_REPORT.md`，提交修改并保持工作树干净。外部凭证缺失仅标记BLOCKED，不能阻塞其余实现，也不得伪造外部联调成功。

# A6 单卡 SWA 验证任务

[迁移结论与本分支的适配](a6-migration.zh-CN.md#本分支的修正与验证) · [构建和运行命令](usage.zh-CN.md#单卡-a6-swa)

- [ ] **P0　在干净的 `a6-migrate-case` 工作树重建 HBG 和 SWA，单卡执行一次，返回数值与退出结果。**

保留上轮有本地 diff 的工作树。可在已有仓库执行以下命令，目录名选择尚未使用的名字。然后按上方链接在干净 worktree 内构建并运行。

```bash
git fetch https://github.com/mihudaner/simpler.git refs/heads/a6-migrate-case
git worktree add --detach ../simpler-a6-swa-verify FETCH_HEAD
cd ../simpler-a6-swa-verify
```

| 结果 | 在下方填写 |
| ---- | ---------- |
| 通过 | 实际提交 SHA、设备型号、运行退出码，贴本轮 `rank0/result.json` 中 `passed`、`snapshot_inputs`、`validated_against_fused_prefix` 及 `console.log` 的 `scheduler_mode`。 |
| 失败 | 实际提交 SHA、最早失败阶段、错误码和相关日志数行。启动失败附已有的 `site/workers/dispatch_arrived/bootstrap_complete`，退出失败附 retirement 记录，数值不符附 buffer 编号。 |

## 本轮回答区

- 提交与运行结果：
- 关键输出或首个错误：

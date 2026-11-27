# 007 A6 单卡 L0 验证包

包内有同一提交构建的 HBG 和日历调度（`percounter`）运行库、AICPU dispatcher、原生 runner、业务核和参考输出。每个用例的两种模式使用相同的输入、计划与参考。每次启动独立进程，默认预热 0 轮、正式 1 轮。

| 用例 | 计划 | 每轮核执行数 | 输出校验 |
| --- | --- | ---: | ---: |
| Engram | 第 1 层的单卡切片，3 个计算任务 | 160 | 17 个参考 |
| SWA | 沿用 005 的 A6 分块，首个任务 5 分块，15 个计算任务 | 645 | 25 个参考 |
| C1A reuse | 第 21 层，复用已有索引，15 个计算任务 | 466 | 26 个参考 |
| C1A reindex | 第 24 层，重新计算索引和 top-k，19 个计算任务 | 615 | 33 个参考 |
| C2A full | 第 2 层，包含压缩、索引发布、打分和 top-k，26 个任务 | 654 | 39 个参考 |

SWA、C1A reuse 和 C1A reindex 都用设备 C++ 实现替代 `hc_collapse_norm`、`qkv_quant`、`norm_rope_publish`、`mhc_sinkhorn` 原有的四组 VF，首个任务使用 5 分块。C2A full 也替换这四组 VF，另含压缩核 `_c2a_compress__2` 和索引发布核 `idx_k_norm_rope_publish`，首个任务同为 5 分块。五项用例各自保留对应模型层的边界输入和参考输出。MIX 每块由 1 个 AIC 和 1 个 AIV 执行。C1A reindex 的源任务 1594 使用 pool-mode top-k，C2A full 的源任务 165 执行完整索引打分和 top-k。两项都需要全 AIV 硬件栅栏，各启动 54 个 1C1V 分块。前 32 组处理逻辑分片，其余 22 组参加栅栏。

## 拷入 A6 主机

从构建机的 `build/007-handoff/` 将五模型包 `007-a6-calendar-5models-*.tar.xz` 和同名 `.sha256` 拷入 A6 主机的新目录，再执行以下命令。最后一步只读文件并打印运行时和 PTO-ISA 版本，可在申卡前完成。

```bash
sha256sum -c 007-a6-calendar-5models-*.tar.xz.sha256
tar -xJf 007-a6-calendar-5models-*.tar.xz
cd 007-a6-calendar
./run-a6.sh --verify
```

## 执行

板端需要 AArch64 Linux、Ascend960、匹配驱动、CANN 9.3.0 和 Python 3。加载 CANN 后，在已独占一张 A6 的任务里运行。程序先在指定逻辑设备上通过 ACL 查询型号。结果目录必须是新路径。

```bash
source /usr/local/Ascend/cann-9.3.0/set_env.sh
./run-a6.sh "${TASK_DEVICE:?}" "$PWD/results-L0"
```

有 `task-submit` 的共享机可直接申领一张卡。以包根目录为当前目录，分配与执行在同一个任务内。

```bash
task-submit --device auto --device-num 1 --timeout 900 --max-time 900 \
    --run 'source /usr/local/Ascend/cann-9.3.0/set_env.sh && ./run-a6.sh "$TASK_DEVICE" "$PWD/results-L0"'
```

默认按表格顺序逐项运行 HBG 和日历调度。也可以单独跑一项，或在首次验证通过后指定预热与正式轮数。

```bash
./run-a6.sh "$TASK_DEVICE" "$PWD/engram-calendar" engram percounter
./run-a6.sh "$TASK_DEVICE" "$PWD/c1a-reindex-ab" c1a_reindex both 1 10
```

`status.tsv` 按场景记录退出码；`device.txt` 记录设备和 SoC。运行成功时，每项的 `<case>/<runtime>/rank0/result.json` 应有 `passed=true`、`snapshot_inputs=true`、`validated_against_fused_prefix=true`。`rank0/console.log` 和 `rank0/host/` 保存原生输出和 Host 日志；CANN 将设备日志写入 `ascend/<case>/<runtime>/`。失败项也有退出码，完整测试会继续运行其余项。请按实际输出目录名归档回传：

```bash
tar -cJf 007-a6-L0-results.tar.xz results-L0/
```

## 重建

在源码目录准备项目本地 `.venv` 和与 `pto_isa.pin` 一致的 `build/pto-isa`，加载 CANN 9.3.0。以包内 `BUILD` 记录的 `simpler` 提交为准；打包脚本所在的 007 结果目录可以单独保留。脚本重建 A6 两种 runtime 并分别执行 `prepare.py`，核对两种模式输入、计划和参考数据，再生成压缩包与 SHA-256 文件。使用新目录存放每次构建。

```bash
source /usr/local/Ascend/cann-9.3.0/set_env.sh
source .venv/bin/activate
bash tests/fdwic/a6_dsv41_scheduler/results/007-calendar-scheduler/a6/pack-a6.sh build/007-handoff-5models
```

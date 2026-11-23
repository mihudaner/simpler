# A6 单卡 SWA 性能复测与回填

## 005 上板复测

005 使用主线 `48fd8fef3` 的 PyPTO-lib SWA。跨机器比较取 A5 与 A6 的同一迁移版，A5 实测运行时代码为 `ad69fb740`。A6 已离线核对 15 个计算任务、19 个「任务 × 核类型」和每轮 660 次核执行，首次上板在完成计数处报 271，修复后的设备数值和性能待复测。[故障与修复](../results/005-main-swa/README.zh-CN.md#a6-完成计数故障-271) · [005 对照表](../results/005-main-swa/README.zh-CN.md) · [构建环境与输入快照](usage.zh-CN.md)

在仓库根目录加载 A6 CANN 和项目 venv，准备单卡 SWA。005 使用当前图内置的 A6 分片。以下命令在同一个 Bash 中执行。

```bash
set -e
source /usr/local/Ascend/cann/set_env.sh
source .venv/bin/activate
export PYTHONNOUSERSITE=1
case_dir=tests/fdwic/a6_dsv41_scheduler
mkdir -p "$case_dir/build"
work_dir=$(mktemp -d "$PWD/$case_dir/build/005-a6-XXXXXXXX")
git rev-parse HEAD > "$work_dir/commit.txt"
python simpler_setup/build_runtimes.py --platforms a6 --runtime host_build_graph \
  --profiling-dfx 1 --profiling-orch 0 --profiling-sched 0 --profiling-tensormap 0
python -I "$case_dir/prepare.py" build --platform a6 --pto-isa build/pto-isa \
  --build-dir "$work_dir/replay"
```

将 `device` 设为已分配的逻辑设备号。L0、L1、L2 各启一个进程，各预热 1 轮、正式测 10 轮，与 005 的 A5 一致。每级的 `rank0/result.json` 对应同一套 25 个可写 Device 缓冲区的数值校验。

```bash
device=${TASK_DEVICE:-0}  # 手工分卡时将 0 改为已分配的逻辑卡号
unset SIMPLER_HBG_AICPU_DETAIL_ENABLE SIMPLER_HBG_BIND_BREAKDOWN_ENABLE SIMPLER_HBG_HOST_PHASE_RECORDS_ENABLE
for level in 0 1 2; do
  out="$work_dir/L$level"
  rank="$out/rank0"
  mkdir -p "$rank/ascend"
  ASCEND_PROCESS_LOG_PATH="$rank/ascend" "$work_dir/replay/host/native-runner" \
    "$work_dir/replay/bundle" "$PWD/build/lib/a6/onboard" "$device" 0 \
    "$out/rootinfo" "$rank" "$level" 1 10 --runtime=host_build_graph > "$rank/console.log" 2>&1
  python "$case_dir/performance.py" "$out" --platform a6 --level "$level" --json "$out/metrics.json"
done
```

## 005 回填位置

- **L0**　用 `L0/metrics.json` 的 `means.core`、`means.device` 回填总表的核窗口和 Device wall。A6 若已确认 AICPU 与 AICore 共享同一纪元的 1 GHz 计数器，可给统计命令加 `--shared-device-clock` 并指定新的 JSON 文件名，再填计算前、计算后。
- **L1**　逐轮按 `source_task`、`core` 对齐 CSV，核对核名和 `executions`。每轮 19 项合计应为 660。将十个正式轮的 `mean_kernel_us`、`span_us` 分别取均值，填入 CSV 的 `a6_mean_kernel_us`、`a6_mean_span_us`。报告中七行取对应的单实例均值，末列为其除以同一行 A5 的 `migrated_mean_kernel_us`。同步下界需按 A6 的 54C/54V 求解，主线默认求解器使用 A5 的 32C/64V。[完整逐核 CSV](../results/005-main-swa/swa-l1-kernel-times.csv)
- **L2**　用 `L2/metrics.json` 的 `means` 回填 L2 核窗口、Device wall、全卡计算空隙和 AICPU 阶段。Host 表分别取 L0 和 L2 的同级统计。缺少时间戳的项留空。记录测量提交、卡型、设备号和 CANN 版本，原始采集留在本次 `work_dir`。[005 性能与生命周期表](../results/005-main-swa/README.zh-CN.md#l2-泳道与采集开销)

## 00–004 历史复测

[优化阶段索引](a6-optimization.zh-CN.md) · [优化前基线](../results/00-baseline/README.zh-CN.md) · [迁移结论](a6-migration.zh-CN.md)

- [x] **单卡 SWA 的 L0、L1 下界与 L3 已回填。** [性能总表](../results/00-baseline/README.zh-CN.md) · [逐核分析](../results/00-baseline/README.zh-CN.md#下界为何更高)
- [x] **合并后、原分片的 A6 对照已有数据。** `0d76a7d` 使用 GM-FAA，L0 核窗口 328.139 µs，Device wall 414.771 µs。[阶段 002](../results/002-hbg-same-address-access/README.zh-CN.md#a6-单卡-swa-l0)
- [x] **003 的 A6 核窗口为 319.060 µs，Device wall 为 406.690 µs。** [阶段 003](../results/003-a6-swa-blocks/README.zh-CN.md)
- [x] **004 的 HC post 与 O-B 组合已通过校验。** L0 核窗口 290.068 µs，Device wall 377.707 µs。[004 同卡对照](../results/004-a6-swa-output-tiles/README.zh-CN.md#同卡对照)

### 旧版夹具的复测方法

在相应历史提交上加载 A6 CANN 环境、激活与当前提交匹配的项目 venv，在仓库根目录执行。先编译 HBG 与 SWA，构建不占卡。复测 A5 时设 `platform=a5` 并使用已分配的 A5 卡，余下命令相同。

```bash
platform=a6
plan=${plan:-post54-ob54}
case_dir=tests/fdwic/a6_dsv41_scheduler
mkdir -p "$case_dir/build"
work_dir=$(mktemp -d "$case_dir/build/perf-${platform}-XXXXXXXX")
runtime=build/lib/$platform/onboard
git rev-parse HEAD
python simpler_setup/build_runtimes.py --platforms "$platform" --runtime host_build_graph \
  --profiling-dfx 1 --profiling-orch 0 --profiling-sched 0 --profiling-tensormap 0
# plan 取当前对照的配置名，每种配置重新创建 work_dir。
plan_args=()
if [ "$platform" = a6 ]; then plan_args=(--a6-plan "$plan"); fi
python -I "$case_dir/prepare.py" build --platform "$platform" "${plan_args[@]}" --pto-isa build/pto-isa --build-dir "$work_dir/replay"
```

在同一个 shell 中使用已分配的逻辑设备，下例为 0。每级一个进程、1 次预热、10 次正式。L0 关闭附加打点，L3 打开 AICPU 细分；两组使用同一构建和用例包。运行期间不要切换分支或库路径。

```bash
set -e
device=0
for level in 0 3; do
  out="$work_dir/L$level"
  mkdir -p "$out/rank0"
  detail=0
  if [ "$level" = 3 ]; then detail=1; fi
  SIMPLER_HBG_AICPU_DETAIL_ENABLE=$detail SIMPLER_HBG_BIND_BREAKDOWN_ENABLE=0 \
    "$work_dir/replay/host/native-runner" "$work_dir/replay/bundle" "$runtime" \
    "$device" 0 "$out/rootinfo" "$out/rank0" "$level" 1 10 --runtime=host_build_graph \
    > "$out/rank0/console.log" 2>&1
done
python "$case_dir/performance.py" "$work_dir/L0" --platform "$platform" --level 0
python "$case_dir/performance.py" "$work_dir/L3" --platform "$platform" --level 3 \
  --trace "$work_dir/swa-${platform}-hbg-L3-detail.json.xz"
```

若核实 AICPU RunWall 与 AICore 使用同一纪元的 1 GHz 设备计数器，在上述两条统计命令添加 `--shared-device-clock`，即可得到 `before/after` 并在图上显示 Device wall 分段。仅有频率一致不能确定纪元一致。若已导出泳道，重跑时选择新的文件名。其余指标都可独立回填。新 worktree 的环境准备见 [使用方法](usage.zh-CN.md#单卡-a6-swa)。

汇总表记录提交号、芯片、测量轮次和均值。

### 004 归档结果

004 已归档同批原配置、两个单项和组合配置。L3 的 `t21_kernel_span` 和 `t27_kernel_span` 分别对应 O-B 和 HC post 的首末实例跨度。[004 测量结果](../results/004-a6-swa-output-tiles/README.zh-CN.md#同卡对照)

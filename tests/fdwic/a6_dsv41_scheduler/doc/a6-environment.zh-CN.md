# A6 单卡 SWA 性能复测与回填

本文记录 00–004 所用的 SWA 图、夹具与命令。005 的任务编号、分片和运行方法见[使用方法](usage.zh-CN.md)及[005 报告](../results/005-main-swa/README.zh-CN.md)。

[优化阶段索引](a6-optimization.zh-CN.md) · [优化前基线](../results/00-baseline/README.zh-CN.md) · [迁移结论](a6-migration.zh-CN.md)

- [x] **单卡 SWA 的 L0、L1 下界与 L3 已回填。** [性能总表](../results/00-baseline/README.zh-CN.md) · [逐核分析](../results/00-baseline/README.zh-CN.md#下界为何更高)
- [x] **合并后、原分片的 A6 对照已有数据。** `0d76a7d` 使用 GM-FAA，L0 核窗口 328.139 µs，Device wall 414.771 µs。[阶段 002](../results/002-hbg-same-address-access/README.zh-CN.md#a6-单卡-swa-l0)
- [x] **003 的 A6 核窗口为 319.060 µs，Device wall 为 406.690 µs。** [阶段 003](../results/003-a6-swa-blocks/README.zh-CN.md)
- [x] **004 的 HC post 与 O-B 组合已通过校验。** L0 核窗口 290.068 µs，Device wall 377.707 µs。[004 同卡对照](../results/004-a6-swa-output-tiles/README.zh-CN.md#同卡对照)

## 已有性能数据的复测方法

加载 A6 CANN 环境、激活与当前提交匹配的项目 venv，在仓库根目录执行。先编译 HBG 与 SWA，构建不占卡。复测 A5 时设 `platform=a5` 并使用已分配的 A5 卡，余下命令相同。

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

## 本轮回答区

004 已归档同批原配置、两个单项和组合配置。L3 的 `t21_kernel_span` 和 `t27_kernel_span` 分别对应 O-B 和 HC post 的首末实例跨度。[004 测量结果](../results/004-a6-swa-output-tiles/README.zh-CN.md#同卡对照)

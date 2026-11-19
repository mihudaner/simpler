# A6 单卡 SWA 性能复测与回填

[优化阶段索引](a6-optimization.zh-CN.md) · [优化前基线](../results/00-baseline/README.zh-CN.md) · [迁移结论](a6-migration.zh-CN.md)

- [x] **单卡 SWA 的 L0、L1 下界与 L3 已回填。** [性能总表](../results/00-baseline/README.zh-CN.md) · [逐核分析](../results/00-baseline/README.zh-CN.md#下界为何更高)
- [ ] **当前待定位的是纯 C 的 O-B 为何每实例从 17.656 增至 25.809 µs。**

## 已有性能数据的复测方法

加载 A6 CANN 环境、激活与当前提交匹配的项目 venv，在仓库根目录执行。先编译 HBG 与 SWA，构建不占卡。复测 A5 时设 `platform=a5` 并使用已分配的 A5 卡，余下命令相同。

```bash
platform=a6
case_dir=tests/fdwic/a6_dsv41_scheduler
mkdir -p "$case_dir/build"
work_dir=$(mktemp -d "$case_dir/build/perf-${platform}-XXXXXXXX")
runtime=build/lib/$platform/onboard
git rev-parse HEAD
python simpler_setup/build_runtimes.py --platforms "$platform" --runtime host_build_graph \
  --profiling-dfx 1 --profiling-orch 0 --profiling-sched 0 --profiling-tensormap 0
python -I "$case_dir/prepare.py" build --platform "$platform" --pto-isa build/pto-isa --build-dir "$work_dir/replay"
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

A6 泳道保存在本地工作目录；按阶段整理时放入对应的 `local-traces/`。回填提交号、轮次和汇总值即可。

## 本轮回答区

优先复用已有资料，仅回传 Markdown。本轮如能补充，请在相应项下贴结果。

- O-B（回放 t21／源码 t29）的 A6 子核机器码指纹、实际核心频率及可用的矩阵和搬运流水计数。若补测，固定输入、tile 与每实例工作量，对比单 block 与原 32 block 的核体时间。
- 若继续对照调度窗口，贴十轮 dispatch、complete 端点的取法与逐轮跨度，标明产生 667.320 和 682.560 µs 的轮次。当前 run5 核体窗口已由逐核 CSV 确认为 672.200 µs。

答：

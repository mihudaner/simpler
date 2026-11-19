# A6 单卡 SWA 性能复测与回填

[性能总表](a5-results-2026-11-17.zh-CN.md) · [迁移结论](a6-migration.zh-CN.md)

- [ ] **P0　用同一张 A6 跑 L0 和 L3，回填下表，保留一份带 AICPU 细分的设备泳道。**

## P0 复现

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

## 本轮回答区

只需返回本 MD，数值均为 µs、10 轮均值。保留 L3 图在 A6 本地，填写文件名即可。

| 等级 | Host bind | 发布镜像 | 准备执行 | 完整调用 | 计算前 | AICore 窗口 | 计算后 | Device wall |
| ---- | --------: | -------: | -------: | -------: | -----: | ----------: | -----: | ----------: |
| L0 | | | | | | | | |
| L3 细分 | | | | | | | | |

| L3 细分 | 泳道初始化 | 核握手 | bootstrap 等待 | 退出等待 | 泳道汇总 |
| ------- | ---------: | -----: | -------------: | -------: | -------: |
| A6 | | | | | |

- 提交、设备、CANN、校验结果、设备时钟依据：
- L3 泳道文件名、所选轮次、A6 与 A5 的主要差异：

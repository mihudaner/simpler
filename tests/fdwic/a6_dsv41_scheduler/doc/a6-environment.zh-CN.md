# 005 SWA · 四个 C++ 核的 A6 五 block 回放

本轮优先验证黄区 A6 能否越过 t12 并完成 25 份输出校验，随后采集详细 L2。默认组包使用 `--kernel-set cpp`。两端共用 005 的 15 个计算任务、19 个活跃核的源码及输入、输出参考。A6 继续使用 54 个 qkv block 和 5 个 t0 block，每轮 645 次执行；A5 原计划为 632 次。旧 A5 性能数据来自另一套核与注册布局，不能替代本组数据。

## 回退范围

| 业务核 | 两端共用实现及适配 |
| --- | --- |
| t0 `hc_collapse_norm` | 原 A6 的 C++ 实现扩展到 A5，沿用四路顺序求和、BF16 舍入及 RMSNorm。源自 PyPTO-lib `ad299c7f` |
| t4 `qkv_quant` | 采用 #1870 前的 C++ 量化实现（`873c2452`），保留 005 入口的 atomic mode 复位，按实际 block 数跨步，写 M16 排布的 scales |
| t12 `norm_rope_publish` | 采用 #1810 前的 C++（`31ed39ac`），保留页归属、RMSNorm、RoPE、FP8 打包和两个真实写回。005 的 cache 是二维字节视图，按 `strides[0]` 取每行 544 字节 |
| 源任务 27 `mhc_sinkhorn` | 采用 #1750 前的 C++ 系数计算（`5359e772`），接 005 的 7 个张量和 4 个标量，每组 6 行、20 次迭代、epsilon 为 1e-6 |

这四项覆盖本图所有原来带独立 VF LLVM 文件的核，其余 15 项使用原源码。两个平台均直接用 CCEC 编译 C++，按原 func ID 注册实际生成的 19 个核。每项源码、机器码的 SHA-256 和编译目标见各包的 `build.json` 和 `kernels/summary.json`。历史导出核对照可通过 `--kernel-set 005-export` 组包。[构建选择](../compile_kernels.py) · [历史超时及直写实验记录](../results/005-main-swa/README.zh-CN.md#11-月-24-日整图复测与-c-对照)

## 黄区取得新包

构建机已用 CANN 9.3.0、PTO-ISA `45435c06` 从实现提交 `72ffa134378d` 生成 `build/005-core/a6`。本批 A6 plan 为 `738a525244bc`，callable 为 `18c1b7c2b4b1`；t0、qkv、t12、Sinkhorn 依次为 `a49b72218457`、`f88201889db0`、`48e129c087d6`、`7da39560a722`。旧包也有相同 plan，应同时核对构建提交号，使用本批压缩包配套的 HBG 运行库。A6 板端完成状态和泳道待黄区实测。

共享构建目录时，在仓库根目录设置 `payload_dir="$PWD"`。分机时可复制构建机 `build/005-core/a6-onboard.tar.gz` 及其 `.sha256` 文件。在两文件所在目录运行以下命令，然后回到本提交的仓库根目录。

```bash
sha256sum -c a6-onboard.tar.gz.sha256 &&
  payload_dir=$(mktemp -d) &&
  tar -xzf a6-onboard.tar.gz -C "$payload_dir"
```

只有 Git checkout 时，在仓库根目录激活本提交对应的项目 venv。按下列命令重建；若提示 Python 扩展的提交号落后，先在此 venv 中执行 `pip install --no-build-isolation -e .`。新的构建目录应尚未包含 bundle。

```bash
set -eo pipefail
source /usr/local/Ascend/cann-9.3.0/set_env.sh
source .venv/bin/activate
export PYTHONNOUSERSITE=1
payload_dir="$PWD"
case_dir=tests/fdwic/a6_dsv41_scheduler
python simpler_setup/build_runtimes.py --platforms a6 --runtime host_build_graph \
  --profiling-dfx 1 --profiling-orch 0 --profiling-sched 0 --profiling-tensormap 0
test "$(git -C build/pto-isa rev-parse HEAD)" = "$(cat pto_isa.pin)"
python -I "$case_dir/prepare.py" build --platform a6 --kernel-set cpp --five-block-t0 \
  --pto-isa build/pto-isa --build-dir build/005-core/a6
```

## A6 单卡 L2 与 L0

在已分配的 A6 单卡会话中，从同版本仓库根目录运行。先做 L2，预热 1 轮、正式 10 轮，每轮由 runner 校验输出。通过后立即导出代表轮泳道，再跑同卡 L0。若首轮超时，命令停下并保留该轮 console 和 plog，供核对最早未完成的任务。

```bash
set -eo pipefail
source /usr/local/Ascend/cann-9.3.0/set_env.sh
source .venv/bin/activate
export PYTHONPATH="$PWD/python:$PWD" PYTHONNOUSERSITE=1
case_dir=tests/fdwic/a6_dsv41_scheduler
replay="$payload_dir/build/005-core/a6"
runtime="$payload_dir/build/lib/a6/onboard"
device=${TASK_DEVICE:?请设置已分配的 A6 逻辑设备号}
out=$(mktemp -d "${TMPDIR:-/tmp}/swa-cpp-a6-XXXXXXXX")
echo "$out"
cp "$replay/build.json" "$out/"
unset SIMPLER_HBG_AICPU_DETAIL_ENABLE SIMPLER_HBG_BIND_BREAKDOWN_ENABLE SIMPLER_HBG_HOST_PHASE_RECORDS_ENABLE
for level in 2 0; do
  step="$out/L$level"
  rank="$step/rank0"
  mkdir -p "$rank/ascend"
  if ! ASCEND_PROCESS_LOG_PATH="$rank/ascend" "$replay/host/native-runner" \
       "$replay/bundle" "$runtime" "$device" 0 "$step/rootinfo" "$rank" "$level" 1 10 \
       --runtime=host_build_graph > "$rank/console.log" 2>&1; then
    tail -n 40 "$rank/console.log"
    exit 1
  fi
  opts=()
  if [[ $level == 2 ]]; then opts+=(--trace "$out/swa-a6-cpp-L2.json.xz"); fi
  python "$case_dir/performance.py" "$step" --platform a6 --five-block-t0 --level "$level" \
    --json "$step/metrics.json" "${opts[@]}" | tee "$step/summary.log"
done
```

回传整个输出目录。成功时包括两份 `result.json`、`metrics.json` 和 `swa-a6-cpp-L2.json.xz`。导出器核对正式轮 645 次执行，选择 Device wall 最接近中位数的一轮。若超时，保留首个未完成任务的 completion、cell phase 和原始异常 PC；若已执行完但数值失败，保留首个不一致的输出缓冲区。[导出与校验](../performance.py)

# 006 待办与 005 A6 复测

## 1. Engram · 对齐 A5、A6 的 L2 泳道，解释两项调度差值

- [x] 归档 A5 的首个正式轮 run1。解压泳道 JSON 后可在 Perfetto 打开，含 64 个量化 V、32 个投影 C、64 个门控 V，以及 AICPU 放行事件。原始包保留预热轮和 10 个正式轮，可逐实例复算。两端对比采用 run1 同类实例均值，差值为 A6 − A5。[A5 run1 泳道图](../results/006-main-case-coverage/a5/engram/engram-a5-L2-run1.json.xz) · [原始采集](../results/006-main-case-coverage/a5/engram/capture.tar.xz) · [指标与构建信息](../results/006-main-case-coverage/a5/engram/metrics.json)
- [ ] 找回 A6 同次采集的原始 L2。仓内的 `a6/engram.tar.xz` 是回放包。如果原采集无法取回，在 A6 上按预热 1 轮、正式 10 轮重采，归档 `run1/chip_swimlane_records.json`、`deps.json`、`source-task-map.txt` 和逐轮指标。标明新轮次，先复算两列，再对齐两端的事件。[006 回放包与用例](../results/006-main-case-coverage/README.zh-CN.md)

| 待解释的差值（µs/实例） | A5 run1 已观测到什么 | A6 取回泳道后核对什么 |
| --- | --- | --- |
| 普通 C「观测前驱」20.390 → 6.761，**−13.629** | 32 个投影 C 都在最后一个量化 V 的完成打点之前绑定。以该打点切开，C 绑定到最后一个 V 完成平均 19.017 µs，之后到 C 观测到前驱满足平均 1.373 µs。 | 对齐 C 绑定、最后一个量化 V 完成、C 观测到依赖满足三个时刻，分别比较两段。前一段含前驱执行等待，后一段也包含调度轮询。 |
| 普通 V「READY→领取」6.448 → 2.505，**−3.943** | 首批 64 个量化 V 平均 11.876 µs，其中 READY 到 AICPU **开始**放行占 8.196 µs。末批 64 个门控 V 均在放行后 READY，平均 1.020 µs。 | 分别计算量化和门控两组。以同轮 AICPU 握手开始为零点，对齐各组 READY、AICPU 开始放行和 AICore 领取，区分放行提前、READY 后移与放行后的领取耗时变化。 |

两端的汇总差值还不能单独量出完成计数从 CntNotify 切为 GM 的影响。若要给出该项收益，需要同卡、同图、同分块，仅切换完成计数后端的对照。

## 2. 006 Attention · 用 005 的四个设备 C++ 核绕过独立 VF helper

- [x] 核对三个原始包。它们共用 `hc_collapse_norm`、`qkv_quant`、`norm_rope_publish`、`mhc_sinkhorn`，函数 ID 依次为 6、8、14、20，各带 6、1、8、1 个 VF helper。四个核对应的张量参数个数、标量值在三个计划中逐项相同。Engram 没有独立 VF helper。[四核 C++ 实现](../kernels/) · [006 用例清单](../results/006-main-case-coverage/README.zh-CN.md#哪些模型用例经过-plreg_scope-的导出路径)
- [x] 在 006 组包入口支持显式选择 `--kernel-set cpp --five-block-t0`。只将本层 HC collapse 从 20 改为 5 个 block，其余分块沿用各自的 006 计划，`c1a_reindex` 继续使用 A6 的 pool-mode top-k 入口。省略五分块参数可在相同 C++ 核上单独对照 20 block。原始 VF 对照沿用 006 默认命令。[组包入口](../prepare.py) · [核选择](../compile_kernels.py) · [005 的 20/5 block 记录](../results/005-swa-a5-baseline-a6-timeouts/issues.zh-CN.md#a6-t0-20-blocks)
- [x] 使用仓库固定版本的 PTO-ISA 离线编出三个 A6 五分块包，分别含 19、19、25 个活跃核。逐包核对确认，独立 VF helper 清单全部为空，输入与参考逐文件一致，相比各自原始 006 计划，只有本层 t0 的 block 数从 20 改为 5。
- [ ] 在 A6 依次运行下表三组的 L0，逐份核对参考。通过后分别采集 L2，预热 1 轮、正式 10 轮，核对每轮实例数并归档泳道。如果仍停在 t0，记录卡在哪个 block，越过 t0 后按本层任务表定位首个未完成任务。

| 用例 | 本层四个源任务 ID（按上列核名排序） | 五分块每轮计划实例 | 待核对的参考输出 |
| --- | --- | ---: | ---: |
| `swa` | 8、12、20、27 | 577 | 25 |
| `c1a_reuse` | 1389、1392、1400、1408 | 466 | 26 |
| `c1a_reindex` | 1575、1578、1586、1602 | 571 | 33 |

在仓库根目录加载 CANN 和项目虚拟环境，按下方 005 步骤准备 A6 运行库和 PTO-ISA。下面以 `c1a_reuse` 为例，另两个用例替换 `case_name` 即可。

```bash
suite=tests/fdwic/a6_dsv41_scheduler
case_name=c1a_reuse
replay=build/006-a6-cpp-$case_name
python -I "$suite/prepare.py" build --stage 006 --platform a6 --case "$case_name" \
  --kernel-set cpp --five-block-t0 --pto-isa build/pto-isa --build-dir "$replay"
out=$(mktemp -d)
python -I "$suite/run.py" --build-dir "$replay" --device "${TASK_DEVICE:?}" --level 0 --output "$out/L0" &&
  python -I "$suite/run.py" --build-dir "$replay" --device "$TASK_DEVICE" --level 2 \
    --warmup 1 --rounds 10 --output "$out/L2"
```

## 005 SWA · 四个 C++ 核的 A6 五 block 回放

默认组包使用 `--kernel-set cpp`。两端共用 005 的 15 个计算任务、19 个活跃核的源码及输入、输出参考。A6 继续使用 54 个 qkv block 和 5 个 t0 block，每轮 645 次执行；A5 原计划为 632 次。

### 回退范围

| 业务核 | 两端共用实现及适配 |
| --- | --- |
| t0 `hc_collapse_norm` | 原 A6 的 C++ 实现扩展到 A5，沿用四路顺序求和、BF16 舍入及 RMSNorm。源自 PyPTO-lib `ad299c7f` |
| t4 `qkv_quant` | 采用 #1870 前的 C++ 量化实现（`873c2452`），保留 005 入口的 atomic mode 复位，按实际 block 数跨步，写 M16 排布的 scales |
| t12 `norm_rope_publish` | 采用 #1810 前的 C++（`31ed39ac`），保留页归属、RMSNorm、RoPE、FP8 打包和两个真实写回。005 的 cache 是二维字节视图，按 `strides[0]` 取每行 544 字节 |
| 源任务 27 `mhc_sinkhorn` | 采用 #1750 前的 C++ 系数计算（`5359e772`），接 005 的 7 个张量和 4 个标量，每组 6 行、20 次迭代、epsilon 为 1e-6 |

这四项覆盖本图所有原来带独立 VF LLVM 文件的核，其余 15 项使用原源码。两个平台均直接用 CCEC 编译 C++，按原 func ID 注册实际生成的 19 个核。每项源码、机器码的 SHA-256 和编译目标见各包的 `build.json` 和 `kernels/summary.json`。历史导出核对照可通过 `--kernel-set 005-export` 组包。[构建选择](../compile_kernels.py) · [导出核超时定位结论](../results/005-swa-a5-baseline-a6-timeouts/issues.zh-CN.md#a6-t12-stall)

### 从源码构建 A6 回放包

在仓库根目录使用项目虚拟环境，加载 CANN 9.3.0，并按仓库的 `pto_isa.pin` 构建。

使用空的组包目录。如果本地 Python 扩展与源码版本不一致，可在项目虚拟环境中运行 `pip install --no-build-isolation -e .`。

```bash
set -eo pipefail
source /usr/local/Ascend/cann-9.3.0/set_env.sh
source .venv/bin/activate
export PYTHONNOUSERSITE=1
case_dir=tests/fdwic/a6_dsv41_scheduler
python simpler_setup/build_runtimes.py --platforms a6 --runtime host_build_graph \
  --profiling-dfx 1 --profiling-orch 0 --profiling-sched 0 --profiling-tensormap 0
test "$(git -C build/pto-isa rev-parse HEAD)" = "$(cat pto_isa.pin)"
python -I "$case_dir/prepare.py" build --platform a6 --kernel-set cpp --five-block-t0 \
  --pto-isa build/pto-isa --build-dir build/005-core/a6
```

### A6 单卡 L2 与 L0

从仓库根目录运行，设置 `TASK_DEVICE` 为已分配的逻辑设备号。L2 采集泳道，L0 测量性能；各等级独立预热 1 轮、测量 10 轮。

```bash
set -eo pipefail
source /usr/local/Ascend/cann-9.3.0/set_env.sh
source .venv/bin/activate
export PYTHONPATH="$PWD/python:$PWD" PYTHONNOUSERSITE=1
case_dir=tests/fdwic/a6_dsv41_scheduler
replay="$PWD/build/005-core/a6"
runtime="$PWD/build/lib/a6/onboard"
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

每个采集等级分别生成 `result.json` 和 `metrics.json`。L2 导出器核对正式轮的 645 次执行，以 Device wall 最接近中位数的一轮生成 `swa-a6-cpp-L2.json.xz`。[导出与校验](../performance.py)

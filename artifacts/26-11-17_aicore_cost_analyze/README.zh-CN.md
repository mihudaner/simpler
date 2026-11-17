# SWA：AICPU 前后耗时与泳道采集膨胀

2026-11-17；A5，HBG AICore 调度，源码 `d3afb63b9b5a845097adf5883eb26250bbcfd2db` 加本目录记录的诊断补丁。选用原 PR 的 `pypto_lib_latest/swa`：16 个计算任务、578 个执行实例、96 个 Worker、5 个 AICPU 线程。

**已有 L3 采集整体把 Device wall 从约 0.406 ms 放大到 1.194 ms；在此基础上补充 AICPU 细分打点，均值增加约 1.23%。已有 L3 包含 AICore 调度的 Scalar 详细采集，不能把这组差额解释成单独“画图”的成本。**

两份主要泳道图（仅本地留存，未推送远端；gzip 解压后导入查看器）：

- [现有 L3 采集](traces/swa-current-L3.json.gz)：AICore 调度、Worker、任务连线、原有 AICPU 生命周期。
- [L3 加 AICPU 细分](traces/swa-detail-L3.json.gz)：额外展开准备、汇合等待、监督、采集汇总及清理。

两份图最上方都有 **Device wall → 计算前／AICore 窗口／计算后** 三段，直接与下面的 `AICPU Lifecycle` 对齐。每份图各取接近本组 Device wall 中位数的真实一次运行，不是平均值拼图。

## 1. 现有采集与新增 AICPU 打点的对照

`r002-swa-pair` 同一张卡、相同运行时二进制和计算核，顺序为 L0、现有 A、详细 A、详细 B、现有 B。每个进程预热 1 次；L0 测 10 次，其他每批测 5 次，合并后每组各 10 次。下表单位 **μs，算术均值**。

| 区间 | L0（关闭） | 现有 L3 | L3 + AICPU 细分 | 现有 L3 / L0 | 新增细分变化 |
| ---- | ---------: | ------: | --------------: | -----------: | -----------: |
| 计算前 | 65.909 | 217.437 | 219.137 | 3.30× | +0.78% |
| AICore 窗口 | 297.227 | 430.560 | 430.828 | 1.45× | +0.06% |
| 计算后 | 43.298 | 545.885 | 558.616 | 12.61× | +2.33% |
| **Device wall** | **406.433** | **1193.882** | **1208.582** | **2.94×** | **+1.23%** |

膨胀倍数 = 候选均值 / 基线均值；变化率 = (倍数 − 1) × 100%。Device wall 的样本范围分别为 392.480–425.358、1126.798–1272.906、1164.721–1284.131 μs。后两组范围重叠，**1.23% 是本次观测差额，不能当成固定打点成本**。

数据：[逐次端点与样本](analysis/r002/samples.csv)、[均值／中位数／范围](analysis/r002/summary.json)、[原始运行记录](runs/r002-swa-pair/run.json)。

### 基础采集还是调度详细采集造成的膨胀？

补充 `r003-swa-levels`：同一张卡重测 L0、L2、L3，每组 10 次；L2／L3 均开启相同的 AICPU 细分打点。L2 已保留任务起止、下发／完成及 AICPU 生命周期；L3 额外启用 Scalar 详细记录与调度相位记录。单位仍为 μs、均值。

| 采集 | 计算前 | AICore 窗口 | 计算后 | Device wall |
| ---- | -----: | ----------: | -----: | ----------: |
| L0 | 62.344 | 299.440 | 42.313 | 404.097 |
| L2 + AICPU 细分 | 204.540 | 318.000 | 498.703 | 1021.243 |
| L3 + AICPU 细分 | 216.589 | 430.712 | 544.910 | 1192.212 |

**整段 Device wall 的膨胀以基础采集为主：L0→L2 增加约 617 μs；L2→L3 再增加约 171 μs（16.74%）。计算窗口则受详细调度记录影响明显：L2→L3 增加约 113 μs（35.44%）。**

L2 就已经有 `swimlane_init` **136.494 μs**、`swimlane_collect` **429.808 μs**；L3 分别为 135.109、439.132 μs。这说明前后段的大幅增长并不依赖 Scalar 详细打点。L3 的退出等待还从 21.539 增至 48.230 μs。L2→L3 同时改变 Scalar 记录、相位记录及其收尾，不能把全部差额精确归给单个打点函数。

Device wall 范围：L0 395.602–412.112、L2 975.117–1058.000、L3 1154.155–1253.989 μs。这一轮独立成组，不与 `r002` 跨卡拼接差额。见 [全部样本](analysis/r003/samples.csv)、[汇总](analysis/r003/summary.json)、[AICPU 阶段](analysis/r003/lifecycle-summary.json)。

## 2. AICPU 前后具体花在哪里

```text
T0  AICPU RunWall 开始
 │  初始化 → 各核握手 → 配置、发布上下文 → 等待 bootstrap → 放行
T1  第一个计算 kernel 开始
 │  AICore 执行计算与调度；AICPU 同时监督任务图完成
T2  最后一个计算 kernel 结束
 │  剩余完成处理 → 退出通知／确认 → 采集汇总 → 清理
T3  AICPU RunWall 结束

Device wall = (T1−T0) + (T2−T1) + (T3−T2)
```

**前后段包括 AICPU 工作及等待其他核的时间；中段包括调度空隙。都不是纯计算指令时间。** Device wall 不含 Host 建图、Host launch 排队及返回后的 Host JSON 导出。多个 AICPU 线程并行，阶段按区间并集统计，不把线程耗时相加。

详细组的关键阶段均值如下；父子阶段存在包含关系，不能将这些行全部相加。

| 位置 | 图中名称 | 均值（μs） | 代码实际做的事 |
| ---- | -------- | ---------: | -------------- |
| 计算前 | `swimlane_init` | 137.638 | `chip_swimlane_aicpu_init()` 初始化采集状态与记录缓冲 |
| 计算前 | `handshake` | 10.054 | 各线程等待其负责的核完成握手 |
| 计算前 | `context_publish` | 8.259 | 发布各 Worker 上下文 |
| 计算前 | `bootstrap_wait` | 47.031 | 等待 AICore 完成启动准备 |
| 计算后 | `exit_wait` | 46.479 | 等待各核退出确认 |
| 计算后 | `swimlane_collect` | 461.895 | 遍历执行记录，构造并发布泳道记录 |
| 计算后 | `deinit` | 0.624 | 清理本次运行状态 |

`swimlane_init` 占前段约 **63%**，包含于 `local_setup`；`swimlane_collect` 占后段约 **83%**，包含于 `diagnostics`。后者由完成汇合的一个 AICPU 线程执行，按任务／block／subtask 遍历本例 578 个执行实例，生成 Worker 记录与 StateProbe／Dispatch／Complete 相位记录，再发布到采集缓冲。**这段不是 Host JSON 序列化，也不是逐条解析全部 Scalar trace。** 尚未进一步拆分其中构造记录和发布各花多少时间。

所以，详细图中很长的 AICPU 收尾，有很大部分是采集工作自身；不能直接据此判断 L0 业务执行也有同样的瓶颈。完整阶段统计及每次原始 cycle 见 [lifecycle-summary.json](analysis/r002/lifecycle-summary.json) 和 [lifecycle-samples.json](analysis/r002/lifecycle-samples.json)。

读码顺序：

1. [aicpu_executor.cpp](../../src/a5/runtime/host_build_graph/aicpu/aicpu_executor.cpp)：`init()` → `run()`／`supervise()` → 完成汇合 → `deinit()`。
2. [aicore_lifecycle.cpp](../../src/a5/runtime/host_build_graph/aicpu/aicore_lifecycle.cpp)：`pre_handshake_init()`、各分区握手／发布／退出、`collect_run_swimlane_records()`。
3. [aicpu_lifecycle_detail.h](../../src/a5/runtime/host_build_graph/aicpu/aicpu_lifecycle_detail.h)：RAII 进入／退出读 cycle，写入各线程独立 GM 记录；不在轮询内逐次打印。
4. [runtime_maker.cpp](../../src/a5/runtime/host_build_graph/host/runtime_maker.cpp) 导出 `detail_intervals`；[转换器](../../simpler_setup/tools/swimlane_converter.py) 将它画到原 AICPU 生命周期泳道。

## 3. 验证与范围

原始 SWA 用例是模型任务及核的 C++ 回放，使用固定零权重夹具和已有输入快照；每轮与 fused-prefix 参考输出逐字节比较。三轮实验共 105 次执行（含预热）全部通过；这不是完整模型或真实权重精度验证。`r001` 是补齐采集初始化／汇总打点前的探索轮，保留原始记录，不与 `r002` 合并计算均值。

两组只切换 `SIMPLER_HBG_AICPU_DETAIL_ENABLE=0/1`；它在 L2 及以上启用额外 AICPU 记录。运行时、输入、计算核、任务图及 L3 级别相同，指纹保存在 `run.json`。当前“现有 L3”指同一诊断版运行时关闭新增记录，不是重跑旧二进制。固定本分支提交进行对照，没有混入远端 main 的后续优化。

20 个 L3 正式样本均为 578 个 kernel，96 条 Scalar stream 无丢弃、无容量截断；L3 本来就会过滤部分短函数，不代表逐指令全量记录。两份图各校验了 578 个原始 cycle 锚点、603 对 flow，gzip JSON 可读，见 [trace-validation.json](analysis/r002/trace-validation.json)。没有额外重测 Chrome importer。

转换器单测 157 项通过，运行时已编译安装。可选 Host 阶段测试因测试环境缺 Torch／另一环境扩展版本不符而未执行；IR 检查已解析部分无发现，但系统 `llvm-dis` 崩溃导致未完整覆盖，不能记为全部通过。

## 4. 复现与保留材料

命令均在仓库根目录执行。先配置 A5 CANN/PTOISA 工具链并激活项目 `.venv`，构建此提交加诊断补丁，准备已有 native runner；详见 [原用例说明](../../tests/fdwic/dsv41_scheduler/README.md)。新增打点仅用于诊断，未修改调度算法。

```bash
export SIMPLER_BUILD_RUNTIMES=host_build_graph CMAKE_BUILD_PARALLEL_LEVEL=4
python -m pip install --no-build-isolation -e .

archive=artifacts/26-11-17_aicore_cost_analyze
mkdir -p outputs/aicore-cost/inputs
tar -xzf "$archive/inputs/swa-bundle.tar.gz" -C outputs/aicore-cost/inputs
task-submit --device auto --device-num 1 --max-time 600 \
  --run 'python artifacts/26-11-17_aicore_cost_analyze/run_pair.py --bundle outputs/aicore-cost/inputs/swa --output artifacts/26-11-17_aicore_cost_analyze/runs/r004-swa-pair'

python "$archive/summarize.py" "$archive/runs/r004-swa-pair" --output "$archive/analysis/r004"
python "$archive/render.py" --analysis "$archive/analysis/r004" --output "$archive/traces/r004"
```

每次使用新的输出目录。输入／参考值／核包在 `inputs/`；原始 Host 日志、逐轮原始采集与输出检查结果在 `runs/`，大 JSON 无损 gzip 压缩；两份直接查看的转换结果在 `traces/`，统计结果在 `analysis/`。没有保存每轮输出张量副本，保留了逐字节检查的结果。

复跑 L0／L2／L3 对照时，在 `run_pair.py` 命令后添加 `--comparison levels`，并换用新输出目录。[诊断补丁](evidence/runtime-detail.patch.gz) 是相对上述 HEAD 的累计补丁，包含未跟踪的新头文件；[执行与验证记录](evidence/provenance.json) 保存任务编号、工具链、构建和检查范围。归档不包含安装环境、构建缓存及原运行时库副本，保留运行时指纹供核对。

按要求，大体积 `.json.gz` 采集只在本地留存，不随 Git 推送；远端包含代码、报告、统计、日志和小输入包。克隆后需自行重新采集或获取本地归档，才能打开泳道图或复跑原始记录解析。补丁需先用 `gzip -dc` 解压；中文泳道标签在 `labels.zh-CN.json`。

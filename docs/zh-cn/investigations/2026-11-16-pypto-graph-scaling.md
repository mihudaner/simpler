# PyPTO Graph 1／10／100 层验证：进展与计时口径

更新日期：2026-11-16。当前简单链两条路线的性能对照、Graph 的 Host 准备分段，以及 SWA Graph 的 HBG 1／10／100 层实测均已完成。

**最新范围：已有 ordinary 数据保留，后续不再增量测试 ordinary；只比较 Graph 下的 HBG 与 Percounter。**

## 当前已经完成什么

本次基线为 Simpler `27fe21756a5230cc4cfe7e44fa360d07d782a111`，启动时与远端
main 一致。HBG 和 Percounter 均在本 worktree 重新构建，PTO-ISA 为仓库指定的
`83b1b2b52ded9ec5d91e02532a57cd95e497ba86`。首轮性能数据使用未修改的 runtime。随后只增加了受现有诊断开关控制的 Host 分段计时，未修改调度算法；诊断数据与主线性能数据分开。
PyPTO 编译器为 `f3fe4058a`，PTOAS 为 0.72；这是显式组合的验证环境，不能称为
PyPTO 原始依赖锁定组合。

| 检查 | 已观测结果 | 能说明什么 |
| ---- | ---------- | ---------- |
| 简单计算链，Graph，10 层，HBG | 128×128 输出全部等于 55，最大误差 0 | 本次输入下逐层计算正确 |
| 实际调度模式 | mode=1 | 确实运行 HBG AICore 路线 |
| Graph 定义／调用实例 | 1／10 | 同一定义在一次 Host 编排内复用 10 次 |
| HBG 展开后节点 | 30：10 ENTER、10 计算、10 EXIT | 设备运行前按实例展开仍存在 |
| 实际计算执行记录 | 10 | Graph 内计算确实执行 |
| 简单链 Percounter | 1／10／100 层普通与 Graph 全部通过，mode=5 | 已覆盖当前 Percounter 路线 |
| 原有单层 SWA | 原 lib 入口编译、设备执行及 5 类输出的 golden 检查通过 | 原算子在当前 HBG 环境可运行 |
| SWA Graph，HBG | 固定 72 tokens；1／10／100 层共 105 次执行通过，mode=1 | 每组首次逐层对照 CPU 参考，随后逐字节复核输出；含 Host 分段实测见文末 |
| 简单链 1／10／100 层性能矩阵 | 12 组，每组 5 次预热＋30 次计时，420 次全部校验通过 | 见下表 |

已通过的运行编号为 `task_20261116_194328_251896626191`。首次冒烟在设备执行前
被旧 PTO-ISA 构建记录检查拒绝；重建 HBG 后上述重试通过。没有将失败算作通过。

小型结构化证据在
[smoke-summary.json](../../../tests/fdwic/dsv41_graph_scaling/evidence/smoke-summary.json)。
原始结果和 L4 记录在本地
`outputs/graph-scaling/smoke/hbg-graph-10-r2/`；该目录被 Git 忽略，所以之前 diff
只显示了三个脚本。现在增加本说明、小型结构证据、逐轮计时数据及汇总 CSV。

## 测的到底是什么

两个用例都从 Python PyPTO 程序编译，入口见
[用例目录](../../../tests/fdwic/dsv41_graph_scaling/README.md)。

```text
Python 普通 inline／@pl.jit.graph
    → PyPTO 生成 Host 编排及计算核
    → CompiledProgram.chip_callable
    → Worker(runtime=host_build_graph 或 percounter)
    → 实际设备执行及输出校验
```

不是把保存过的 task 列表再包一层 Graph。简单链每层向累加器加本层权重，
1／10／100 层期望值分别是 1／55／5050。SWA Graph 按 lib 的 `decode_swa` 业务流程固定 72 tokens 编排，复用 lib 原有计算核；
每层输出接下一层输入，大投影权重共享，缓存按层分开、归一化权重按层变化。
这是重复注意力子层的规模实验，不是完整 100 层模型，也不包含 MoE。

## 后续表格的口径

首轮简单链保留普通／Graph × HBG／Percounter 四组历史数据；新增采集只运行 Graph。实际 mode
分别强制检查为 1／5。每批矩阵串行占用同一张卡，不超过用户要求的两卡上限；本次 SWA 只补 HBG。

| 指标 | 边界 |
| ---- | ---- |
| API 总耗时 | `Worker.run` 调用到返回，排除编译、输入重置和输出校验 |
| Host bind | 仓库 `chip.run.bind` 计时范围，包含设备启动前准备 |
| Device wall | 仓库设备运行时间标记；与计算核窗口分列 |
| AICore 计算窗口 | 首个计算核开始至最后一个结束，含中间空隙 |
| Host Graph 展开 | 另做诊断，定位定义绑定、实例节点展开、调度状态与调用准备；不能拿 Host 总时间冒充 |

主性能运行关闭 L3/L4 采集并预热。结构和依赖检查单独采集；其总耗时含诊断开销，
不会混入性能均值。当前一次 L4 冒烟不提供稳态性能结论。

简单链采用精确参考，SWA 采用 lib 的独立 CPU golden；两者都在计时区间外重置输入、校验输出。

## 简单链首轮实测

运行编号 `task_20261116_195103_290215428890`，同一张卡串行执行，所有组均关闭 L3/L4；每组预热 5 次后取 30 次算术均值。单位统一为 **μs**。Host 是共享机器上的首轮观测，采集期间另有本任务 CPU 编译，不能把微小差异直接归因于 Graph。

| 层数 | 路线 | 形式 | AICore 窗口 | Device wall | Host bind | API 总耗时 |
| ---: | ---- | ---- | ----------: | ----------: | --------: | ---------: |
| 1 | host_build_graph | ordinary | 2.799 | 92.280 | 25.976 | 1343.619 |
| 1 | host_build_graph | graph | 2.920 | 110.623 | 200.987 | 1136.377 |
| 1 | percounter | ordinary | 3.044 | 93.841 | 27.944 | 873.370 |
| 1 | percounter | graph | 3.062 | 95.253 | 142.682 | 894.129 |
| 10 | host_build_graph | ordinary | 64.124 | 157.582 | 34.574 | 1006.739 |
| 10 | host_build_graph | graph | 112.402 | 218.348 | 182.813 | 1188.488 |
| 10 | percounter | ordinary | 39.388 | 138.674 | 57.986 | 843.685 |
| 10 | percounter | graph | 42.188 | 150.068 | 343.990 | 1310.205 |
| 100 | host_build_graph | ordinary | 643.324 | 738.501 | 106.763 | 1699.222 |
| 100 | host_build_graph | graph | 1873.966 | 2171.252 | 287.997 | 3943.455 |
| 100 | percounter | ordinary | 405.301 | 510.659 | 92.787 | 1472.697 |
| 100 | percounter | graph | 432.852 | 561.510 | 334.430 | 1917.467 |

这份小用例每个 Graph 只有一个很小的加法任务。它验证 Graph 复用和层数增长的开销，不代表复杂业务 Graph 的收益；当前 HBG 100 次 Graph 的设备计算窗口比普通方式更长，不能预设 Graph 一定加速。

[汇总 CSV](../../../tests/fdwic/dsv41_graph_scaling/evidence/simple-matrix-r1/timing-summary.csv) 同时保留均值、中位数和最小值；[逐轮原始计时](../../../tests/fdwic/dsv41_graph_scaling/evidence/simple-matrix-r1/timing-samples.json) 保留预热标记。解析命令：

```bash
python tests/fdwic/dsv41_graph_scaling/summarize.py \
  outputs/graph-scaling/matrix-simple-r1 \
  --output tests/fdwic/dsv41_graph_scaling/evidence/simple-matrix-r1
```

## Graph：Host 提前准备随层数的变化

**本节测试对象是简单 add 计算链：每层对 128×128 的累加器加上本层权重，重复调用同一个 Graph 1／10／100 次。**

只比较 Graph。本次运行编号见 `evidence/host-phases-graph-r2/run.json`，同一张卡串行运行 HBG／Percounter，1／10／100 层，每组预热 5 次、采样 30 次，210 次全部通过精确输出检查。

在首轮主线测量之后，新增 5 个仅受 `SIMPLER_HBG_BIND_BREAKDOWN_ENABLE=1` 控制的 Host span，见 [诊断补丁](../../../tests/fdwic/dsv41_graph_scaling/evidence/host-timing.patch)。这批数据**含诊断开销**，用来定位成本，不替换前面的主线性能数据。采集时没有并行运行本任务的 CPU 编译。

单位 μs，以下是 30 次均值。定义绑定包含“节点展开”；调度状态包含“执行参数准备”，父子列不能相加。“—”表示该路线不执行这项 HBG Host 函数，不是测得零耗时。

**Percounter 同样需要展开 Graph 子任务，但在设备端 AICPU 上分批完成；表中的“—”仅表示没有对应的 Host 阶段，当前表尚未覆盖这部分设备端展开耗时。**

各列的含义与关系：

| 列 | 简述 |
| -- | ---- |
| 路线 | HBG 或 Percounter，采用哪条运行时路线 |
| 层数 | 一次调用中，同一个 Graph 连续执行多少次 |
| 完整 Host bind | 本次设备运行前的 bind 全阶段，包含编排、定义绑定、调度状态及其他 bind 准备；不含设备执行 |
| Host 编排 | 执行业务循环，生成本次任务和 Graph 调用记录 |
| 定义绑定（含节点展开） | 将 Graph 定义与本次调用关联，准备实例结构 |
| 其中节点展开 | HBG 给各实例的 ENTER、子任务、EXIT 分配节点身份；包含在定义绑定内 |
| 调度状态（含执行参数） | 根据任务图建立设备调度所需的数据 |
| 其中执行参数准备 | 准备各任务执行时使用的参数；包含在调度状态内 |
| Device L0（AICore 窗口） | 第一个计算核开始到最后一个结束，包含中间调度与等待空隙 |
| 含 Host（API 总耗时） | `Worker.run` 调用到返回，包含 Host 准备、设备执行和完成等待 |

**看提前展开的成本，重点看中间两组 Host 列；看设备执行影响，看 Device L0；看最终总成本，看最后一列。父子列重叠，总耗时又包含设备执行，不能把这些列直接相加。** 中间几列也未覆盖全部 Host 准备，例如图像发布与启动交接仍在其他阶段。

| 路线 | 层数 | 完整 Host bind | Host 编排 | 定义绑定（含节点展开） | 其中节点展开 | 调度状态（含执行参数） | 其中执行参数准备 | Device L0（AICore 窗口） | 含 Host（API 总耗时） |
| ---- | ---: | -------------: | --------: | ---------------------: | -----------: | ---------------------: | ---------------: | -----------------------: | --------------------: |
| host_build_graph | 1 | 410.318 | 259.925 | 30.482 | 0.548 | 24.586 | 1.686 | 2.991 | 1697.373 |
| host_build_graph | 10 | 470.887 | 326.344 | 26.639 | 0.848 | 25.555 | 4.434 | 112.391 | 1552.228 |
| host_build_graph | 100 | 471.598 | 167.681 | 33.088 | 4.461 | 124.005 | 25.348 | 1874.804 | 4113.897 |
| percounter | 1 | 556.084 | 352.930 | 17.773 | — | 32.692 | — | 3.186 | 2064.973 |
| percounter | 10 | 503.116 | 311.750 | 15.032 | — | 33.709 | — | 41.276 | 1748.111 |
| percounter | 100 | 361.747 | 149.012 | 14.198 | — | 88.787 | — | 431.665 | 1681.041 |

**最后两列采用之前 PR 关注的设备计算窗口和含 Host 总耗时，数值均来自本次同一批分段采集，单位仍为 μs。** Device L0 沿用 AICore wall 口径：首个实际 kernel 开始到最后一个结束，包含中间调度和依赖等待。含 Host 本次直接测量 `Worker.run` 调用到返回，包含 Python 调用、Host 准备、设备执行及完成等待，排除编译、输入重置和输出校验；与旧 PR 的 `prepare_native_run` 开始到 `wait_native_run` 返回入口不同，且本批包含 Host 诊断开销。含 Host 已包含设备执行时间，不能再与 Device L0 相加。

**Graph 实例化不等于“其中节点展开”这一小列。** 定义绑定关联每次调用，节点展开分配 ENTER／子任务／EXIT 身份，调度状态再建立实例元数据、整理依赖并准备执行参数。Host 编排时已经记录任务间依赖；Device 运行时还要检查前驱完成状态、推进后继，这部分影响 Device L0。

```text
含 Host（API 总耗时）
├─ 完整 Host bind
│  ├─ Host 编排
│  ├─ 定义绑定
│  │  └─ 其中节点展开
│  ├─ 调度状态
│  │  └─ 其中执行参数准备
│  └─ 其他 bind 准备
├─ 图像发布、设备启动和完成等待
│  └─ Device L0：计算及中间调度、依赖等待
└─ 调用交接、完成确认等
```

以上表示包含关系，不是可逐项相加的完整计时分解。**“含 Host”是整个调用耗时，不是纯 Host CPU 耗时。** 以同批 HBG 100 层为例，三项 Host 父阶段合计 324.774 μs，完整 bind 为 471.598 μs；Device L0 为 1874.804 μs，而 Host 的 `runner_run` 启动至运行返回区间为 3113.998 μs。图像发布另为 172.722 μs，执行准备另为 21.738 μs，整个 API 为 4113.897 μs。因此差额包含未列出的准备、计算窗口之外的设备启动与完成等待、调用交接等；不能全部归因于 Graph 展开，也未逐项完成差额的精确归因。完整 bind 包含其子阶段，不能再与它们相加。

这批数据回答的是：

- **HBG 节点身份展开确实随实例数增加，但本小用例绝对成本很小**：1→100 层从 0.548 增至 4.461 μs，增加 3.913 μs。它只覆盖 `native_graph_plan_nodes()`，不能代表所有准备成本。
- **更明显的增长在调度状态与调用准备**：HBG 从 24.586 增至 124.005 μs，增加 99.419 μs；其中执行参数准备从 1.686 增至 25.348 μs，增加 23.662 μs。参数准备属于调度状态的子区间，不能再相加。
- **Percounter 的 Host 准备也会增长**：调度状态从 32.692 增至 88.787 μs，增加 56.095 μs。但它没有运行上述 HBG 的 Host 节点展开及调用准备函数；不能把破折号解释成整条路线没有 Graph 实例化成本。
- Host 编排的墙钟波动很大，100 层均值甚至低于 1／10 层，因此不能拿 Host bind 总均值直接拟合“每层固定成本”，也不能由此声称 100 层反而更便宜。当前已拆出更稳定、范围明确的准备函数，下一步应单独解释编排中的录制／等待波动。

结构记录已经确认 HBG 1／10／100 层均只有 1 个定义，分别有 1／10／100 个实例、3／30／300 个节点。**定义复用与实例准备随层数增加同时存在。** 见 [1／100 层结构记录](../../../tests/fdwic/dsv41_graph_scaling/evidence/structure-1-100.json) 和前面的 10 层冒烟记录。

[分段汇总 CSV](../../../tests/fdwic/dsv41_graph_scaling/evidence/host-phases-graph-r2/timing-summary.csv) 还保留中位数／最小值；[逐轮数据](../../../tests/fdwic/dsv41_graph_scaling/evidence/host-phases-graph-r2/timing-samples.json) 保留预热样本。解析：

```bash
python tests/fdwic/dsv41_graph_scaling/summarize.py \
  outputs/graph-scaling/host-phases-graph-r2 --host-phases \
  --output tests/fdwic/dsv41_graph_scaling/evidence/host-phases-graph-r2
```

## SWA Graph：HBG 的 1／10／100 层实测

**本节是连续重复 SWA 注意力子层，每层包含归一化、Q/KV 投影、缓存更新、Attention、输出投影和 mHC；不是简单 add，也不是完整模型层。** 本批只运行 HBG，未采集 SWA Percounter。

运行 `task_20261116_203648_106007427173`，同一张卡串行，每组预热 5 次、计时 30 次，使用与前表相同的 Host 诊断补丁，关闭 L3/L4。以下均为 **μs，30 次算术均值**，包含 Host 分段记录开销。

| 路线 | 层数 | 完整 Host bind | Host 编排 | 定义绑定（含节点展开） | 其中节点展开 | 调度状态（含执行参数） | 其中执行参数准备 | Device L0（AICore 窗口） | 含 Host（API 总耗时） |
| ---- | ---: | -------------: | --------: | ---------------------: | -----------: | ---------------------: | ---------------: | -----------------------: | --------------------: |
| host_build_graph | 1 | 807.898 | 526.536 | 47.198 | 1.221 | 79.945 | 13.681 | 952.164 | 3445.125 |
| host_build_graph | 10 | 1126.081 | 483.582 | 54.524 | 3.433 | 434.407 | 120.493 | 9688.625 | 12754.445 |
| host_build_graph | 100 | 5546.551 | 1205.553 | 66.001 | 22.226 | 3997.883 | 1635.647 | 102343.767 | 128453.289 |

**SWA 中增加较多的是调度状态与执行参数准备。** 1→100 层，节点身份展开由 1.221 增至 22.226 μs；调度状态由 79.945 增至 3997.883 μs，其中执行参数准备由 13.681 增至 1635.647 μs。完整 Host bind 从 807.898 增至 5546.551 μs。只看节点展开会漏掉大部分随层数增长的准备成本。Device L0 从约 0.952 ms 增至 102.344 ms，同时包含计算量增长和中间调度等待，不能把这部分增长都解释成 Graph 开销。

每次编排均只有 **1 个 Graph 定义（9792 bytes）**，分别被调用 1／10／100 次；每组 35 次均核对成立，见 [Graph 复用记录](../../../tests/fdwic/dsv41_graph_scaling/evidence/swa-host-phases-r1/graph-reuse.json)。单层独立 L4 采集确认定义内有 17 个计算任务、2 个控制节点，实际执行 331 个计算实例；展开后的 23 个节点还包含 2 个外层已完成控制节点及 Graph ENTER／EXIT，见 [单层结构记录](../../../tests/fdwic/dsv41_graph_scaling/evidence/swa-host-phases-r1/structure-single-layer.json)。多层性能采集未开启 L4，不能将单层的节点映射冒充多层实际逐节点记录。

### SWA 如何适配与校验

新增包装最初遗漏 `MX_B_NN` 声明和动态维度绑定，属于测试适配错误。直接包装原动态实现还会遇到 Graph 对临时张量及任务数的静态要求。因此 [swa.py](../../../tests/fdwic/dsv41_graph_scaling/workloads/swa.py) 中的 `swa_static_step` 固定这次输入为 72 个有效 token、每层 37 个缓存页、32 AIC／64 AIV，明确临时张量尺寸和 SPMD 数量；`swa_graph` 用 `@pl.jit.graph` 包装它，外层 `pl.range(layers)` 连续调用。所有计算仍调用 lib 原有 CANNBotDSL 核，没有修改计算核或生产编译器。72 行全部有效，所以原实现的尾行清零分支不执行。

大投影权重共享，层间独立缓存，归一化权重逐层变化；输入输出存放在预分配的 100 层容量中，每层读取上一层的 hidden／mix。它验证的是固定业务拓扑的 Graph 复用，不代表任意动态 tokens 的原 `decode_swa` 都可以直接加装饰器。

校验由 [swa_validation.py](../../../tests/fdwic/dsv41_graph_scaling/workloads/swa_validation.py) 完成：

- 每组首次运行，逐层用该层实际输入调用 lib 独立 CPU `golden_swa`，比较下一层 hidden、mix、KV 和 scale，沿用 lib 原有容差；累计 111 层通过。以逐层输入作参考是为了避免 100 次 CPU/NPU 舍入差异累积，不是拿设备输出作期望值。
- hidden 容差为 `atol=1e-2, rtol=1/128`，mix 为 `1e-4, 1e-4`，均允许最多 0.5% 元素超差；KV 有效映射位置为 `2^-9, 2^-3`、最多 1% 超差，scale 精确比较。未映射缓存、未执行层和初始输入带必须保持原值。
- 随后每组 34 次执行与这份已通过 CPU 校验的输出逐字节比较，共 102 次，四类可变缓冲区全部一致。全部检查和拷贝在 API 计时外进行；内部 attention_output 未单独导出，覆盖通过最终 hidden 检查传递。

原单层 `l2_decode_swa` 的独立核对也保留：`task_20261116_200538_360978623637`，HBG mode=1，通过原 lib 的五类输出校验，见本地 `outputs/graph-scaling/swa-single/hbg-r1/`。这次 Graph 单层冒烟为 `task_20261116_203503_96219332747`，也通过独立 CPU 校验；其 L4 耗时不参与本表均值。

### 证据与复现

[运行记录](../../../tests/fdwic/dsv41_graph_scaling/evidence/swa-host-phases-r1/run.json)、[逐层验证](../../../tests/fdwic/dsv41_graph_scaling/evidence/swa-host-phases-r1/validation.json)、[汇总 CSV](../../../tests/fdwic/dsv41_graph_scaling/evidence/swa-host-phases-r1/timing-summary.csv)、[逐轮计时](../../../tests/fdwic/dsv41_graph_scaling/evidence/swa-host-phases-r1/timing-samples.json)。原始 Host 日志留在本地 `outputs/graph-scaling/swa-host-phases-r1/`；不归档大型输出张量，固定种子输入生成器及校验代码已保留。

从 runtime 仓库根目录运行，使用安装了本 worktree 的项目环境，设置 `PYPTO_LIB_ROOT`，并构建上述 Host 诊断补丁：

```bash
python tests/fdwic/dsv41_graph_scaling/run.py --compile-only \
  --workload swa --variant graph --layers 1 \
  --build outputs/graph-scaling/build/swa-graph-72

task-submit --device auto --device-num 1 --timeout 1800 --max-time 1800 \
  --run '.claude/skills/onboard-arch-precheck/check.sh a5 && \
    python tests/fdwic/dsv41_graph_scaling/run_graph_matrix.py \
      --workload swa --runtimes host_build_graph --host-phases \
      --build outputs/graph-scaling/build/swa-graph-72 \
      --output outputs/graph-scaling/swa-host-phases-new --device "$TASK_DEVICE"'

python tests/fdwic/dsv41_graph_scaling/summarize.py \
  outputs/graph-scaling/swa-host-phases-new --host-phases \
  --output outputs/graph-scaling/swa-host-phases-new/summary
```

编译发生在申请设备之前；加载时可能因 dirty worktree 的缓存版本检查重新组装生成代码，但不计入采样。每次复跑换新输出目录，保留此次证据。

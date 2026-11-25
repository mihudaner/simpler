# 005　最新主线的 SWA 与 A6 迁移

## 截至 11 月 25 日的问题定位

**005 的 A6 完成记账故障已修复。旧导出核的五分块回放中，稳定阻塞点是 t12。当前首要怀疑是按 A5 调用及同步语义生成的 VF 在 A6 上的兼容性。** 四核 C++ 回退包已在 A5 通过数值校验并采到 L2，A6 包已编译，黄区整图校验和泳道待回传。

| 现场 | 已确认 | 尚待验证 |
| --- | --- | --- |
| A6 完成通知，错误 271 | Host 发布的 CntNotify 映射为空，业务核仍走通知写入路径。改为按映射状态选择 GM 记账后，板端未再报 271 | 后续 site 95 是执行进度看门狗超时，需依同轮任务和核内证据定位 |
| t0 导出核，错误 331 | AIV 报向量指令配置非法，采样 PC 落在 t0 核范围 | 具体哪条指令、哪项配置非法仍未锁定 |
| t0 手写 C++，20 个 block | 两版各一轮均有 block2 被 worker62 领取后未完成。当前 A6 包的 t0 指纹 `a49b72218457` 与其中一版相符。改成五个 block 后，多轮整图越过 t0 | 分片改变了每个 block 的工作分配；当前四核组合在 20 个 block 下能否通过仍待复测 |
| 五分块图中的 qkv 与 t12 | qkv block8 早期曾缺票，原版定点复测的 5 个有效轮次均通过。连续三轮原版整图均越过 qkv、t10，t12 的 12 个 block 全被领取，完成数始终为 0 | t12 已越过 helper5 调用点，去掉 TMOV 后仍超时。最后可见标记在 wait 前，无法确定是 VF 执行、事件交接还是相邻指令阻塞，也没有证据把它和早期单个 worker 缺票归为同因 |

**A5 能跑通的源码依据。** 005 固定的 PyPTO-lib 在 A5 CI 指定 PyPTO `3db18db128`。该版代码生成器要求 VF 位于 A5 AIV 函数，生成调用时明确依赖“A5 VF 退出时寄存器指令已完成”这一语义。PTOAS 据调用方的读写信息安排搬运事件，并处理 VF 内部依赖。005 的 A6 导出核对照从已导出的调用方 C++ 与 helper LLVM IR 开始，替换目标 CPU、移除 A5 特性并适配标量移位指令，再按 A6 编译；该过程没有重新针对 A6 规划调用边界上的同步。这解释了为何 A5 的通过不能直接推广到 A6，具体阻塞机制仍需设备证据。[A5 CI 版本](https://github.com/hw-native-sys/pypto-lib/blob/4cb74422616359b3f95c598b1f9cdd31cf4e4173/.github/workflows/ci.yml#L264) · [VF 的目标与完成语义](https://github.com/hw-native-sys/pypto/blob/3db18db1286bdbb44266179e3aedae659174b711/src/codegen/pto/vf_codegen.cpp#L295-L298) · [A6 编译适配](../../compile_kernels.py#L49)

**t12 的静态核对。** 6 行分支的 helper5 接收一个 UB 基址。按 LLVM 元素宽度换算后，scales、weight、input、cos 和 sin 的地址均与调用方的 tile 分配相符。本机 CANN 9.3.0 离线反汇编也显示，两端都生成了 VF 启动指令。这降低了“静态偏移算错”和“漏编 helper”的排查优先级；尚未取得挂起当时的 AIV 指令和事件状态。[调用方](../../../dsv41_scheduler/kernels/pypto_lib_latest/vendor/aiv/norm_rope_publish.cpp#L1721) · [helper5 的指针计算](../../../dsv41_scheduler/kernels/pypto_lib_latest/vendor/vf/norm_rope_publish/__pypto_vf_norm_rope_publish_5.ll#L86)

**黄区下一步。** 先用 A6 五分块 C++ 包（callable `18c1b7c2b4b1`，plan `738a525244bc`）核对 25 份参考并采集 L2。若整图通过，单独切回旧 t12 可检验它是否足以复现；单独把 t0 恢复为 20 个 block 可检验早期缺票是否仍在。两项分开测。若五分块仍超时，先按本轮最早未完成任务重新定位。[黄区命令](../../doc/a6-environment.zh-CN.md#a6-单卡-l2-与-l0)

## 11 月 24 日整图复测与 C++ 对照

以下诊断数字来自当时的板端回传，标记值只适用于当时的诊断版本。旧包在 `5ee50f4` 重建时，baseline/stages 的 callable 分别为 `4380c66badb0`、`d602273fb073`，t12 为 `85561d2e9865`、`f46138a6362b`。两包的 qkv 为 `035cbc9add2d`，plan 为 `738a525244bc`。构建机早一批的 callable 分别为 `14984c9de251`、`d8737dbb9dfc`。

| 对照 | 实际观察 | 定位结论 |
| --- | --- | --- |
| qkv 原版、NOP、PIPE_V | 各 5 个拿到 block8 探针的轮次均为 63/63/63；完整图中原版、屏障版均能越过 qkv | 早期 63/0/0 间歇出现。该 A/B 不足以证明缺屏障、参数错误或 AIV43 硬件异常 |
| 原版五个 t0 block，连续 3 个有效轮次 | t0、t11 完成，t4 含 block8 完成，t10 有 64 份贡献。t12 的 12 个 block 全部 CLAIMED，remaining=12、debt=12，完成 0 份。后续未启动 | 稳定复现在 t12 已领取后的执行区间。单轮 t10 block20 的 AIV 未领取现象在重复对照中未持续出现 |
| t12 stages、stages2、stages3 | 第一轮所有 block 的最后阶段为 37。细分后可见 37、60，个别到 62，均未见 63。37 在 helper5 调用之后，60、62 在 TMOV 链内 | 标量控制流已越过调用点；阶段写入不能证明 VF 已完成 |
| t12 direct、direct2、direct3 | 保留 helper5 计算、目标 GM、事件与两次 TSTORE，去掉四级 TMOV；各版均未返回。direct3 看到 64/65，未见 66（wait 前）、67（wait 后） | 去掉 TMOV 不足以恢复完成；现有探针不能证明已经执行到 wait，更不能定性根因为丢事件 |

### 共享 C++ 核的整图实测

每组独立预热 1 轮、正式 10 轮，耗时为正式轮算术均值，单位 µs。表内为本轮 C++ 组的数据。

| 平台与配置 | 等级 | 执行数/轮 | 核窗口 | Device wall | 输出校验 |
| --- | --- | ---: | ---: | ---: | --- |
| A5，源分片 | L0 | 632 | 156.774 | 243.592 | 通过，25 份参考 |
| A5，源分片 | L2 | 632 | 172.356 | 595.582 | 通过，25 份参考 |
| A6，5 个 t0 block | L0 / L2 | 645（计划） | 待测 | 待测 | 待黄区实测 |

**实测提交与产物**　A5 构建记录的 HEAD 为 `5ee50f41a652`，当时工作树已包含四核 C++ 回退。实测包的 19 个核源文件 SHA-256 均与实现提交 `a07367697ac8` 一致；A5 callable 为 `75e9251b3fa1`，plan 为 `8b64fd725d79`。单卡设备 1，任务 `task_20261124_233121_1908163154`。L2 代表轮 run6，Device wall 594.098 µs。[本次 A5 代表轮泳道](swa-a5-cpp-L2.json.xz)

表下提交号按实测时的构建记录保留。整理后的四核实现为 `72ffa134378d`。从该提交重建的 A6 五分块回放与原包（`a07367697ac8`）的 19 个业务核机器码、plan、callable 均相同。临时工作核及 t12 阶段标记已从运行时和业务核移除，黄区复测使用新包配套的运行库；A6 性能栏待整图数值验证后填写。

## 11 月 23 日导出核对照的 A5 性能

Ascend950DT_9581，设备 1，任务 `task_20261123_155831_271358730317`。一次分卡顺序跑两版 L0、L1 和 L2，共六组；每组独立预热 1 轮、正式 10 轮，表中为正式轮均值，单位 µs。两版共用同一 native runner、callable、输入和 25 个可写 Device 缓冲区参考，各加载自己的 Host、AICPU、AICore 运行库。A6 空栏留作后续同口径复测。

| 设备与运行时 | 计算前 | L0 核窗口 | 计算后 | Device wall | L1 同步约束下界 | L0 距下界 |
| ------------ | -----: | --------: | -----: | ----------: | --------------: | --------: |
| A5 纯主线 `48fd8fef3` | 53.392 | 156.784 | 30.140 | 240.316 | 112.270 | 39.65% |
| A5 迁移版 `ad69fb740` | 55.451 | 156.190 | 31.778 | 243.419 | 111.770 | 39.74% |
| A6 迁移版（待复测） | | | | | | |

上表实测 commit 为纯主线 `48fd8fef3`、迁移版 `ad69fb740`，以下历史 L1/L2 表沿用同一批次。两组 L0 的十轮范围分别为 154.643–159.657 µs 和 154.342–159.597 µs。两组范围重叠，本次同卡复测未观察到合并前后 A5 的 L0 计算性能有明显差异。

L0 核窗口从首个业务核开始到最后一个结束。计算前和计算后取同轮设备系统计数器端点，60 个正式样本均核对了 1 GHz 频率和四端点顺序。每版 L1 按实测核体、依赖、MIX、同步启动和 32C/64V 容量建模，10 轮均求得最优值。距下界取 L0 核窗口除以本版 L1 下界再减 1。[计数器接口](../../../../../src/common/platform/include/aicpu/device_time.h) · [下界模型](../../../dsv41_scheduler/BOUND.md)

主线历史记录有两组可对照。套件表在 `88226709a` 记录新版 SWA HBG **198.426 µs**、下界 **108.480 µs**。随后 #3208 在 A5 设备 5 同卡 A/B/B/A 记录 **175.835 → 156.258 µs**。005 的同卡比较以上表为准。004 的 A6 **290.068 µs** 来自 16 任务旧图。[套件历史表](../../../dsv41_scheduler/RESULTS.md) · [#3208 的逐段实测](https://github.com/hw-native-sys/simpler/pull/3208#issuecomment-7089359401) · [004 旧图](../004-a6-swa-output-tiles/README.zh-CN.md)

## L2 泳道与采集开销

两版都采集了 HBG L2。#3189 把调度打点映射到物理 lane，#3208 继续减少 L2 采集开销。Worker View 的条带给出单次业务核执行，调度 lane 给出领取与交接。归档保留纯主线 run2，它的 Device wall 最接近该组十轮的中位数。解压后可在 Perfetto 中查看 632 次业务核执行。[纯主线 run2 泳道](swa-a5-main-hbg-L2.json.xz) · [#3189](https://github.com/hw-native-sys/simpler/pull/3189) · [#3208](https://github.com/hw-native-sys/simpler/pull/3208)

| 设备与运行时 | L0 核窗口 | L2 核窗口 | 核窗口增幅 | L0 Device wall | L2 Device wall | Device 倍数 | L2 全卡计算空隙 |
| ------------ | --------: | --------: | ---------: | -------------: | -------------: | ----------: | --------------: |
| A5 纯主线 | 156.784 | 167.483 | 6.82% | 240.316 | 628.106 | 2.61× | 15.924 |
| A5 迁移版 | 156.190 | 168.339 | 7.78% | 243.419 | 621.586 | 2.55× | 15.121 |
| A6 迁移版 | | | | | | | |

以纯主线为例，开启 L2 后，计算前增加 140.013 µs，核窗口增加 10.699 µs，计算后增加 237.078 µs。采集对整次设备调用的影响主要落在业务核前后。全卡计算空隙是首末业务核之间所有核均未执行计算的时间；对所有核的执行区间取并集后计算。

### AICPU 生命周期

| L2 设备 | 计算前 | 握手 | 拓扑配置 | 发布上下文 | bootstrap 等待 | 释放启动寄存器 | 计算后 | 退出信号 | 退出等待 |
| ------- | -----: | ---: | -------: | ---------: | -------------: | -------------: | -----: | -------: | -------: |
| A5 纯主线 | 193.405 | 8.195 | 5.638 | 8.643 | 24.549 | 1.344 | 267.217 | 0.862 | 22.068 |
| A5 迁移版 | 191.025 | 7.858 | 5.301 | 7.171 | 24.731 | 1.185 | 262.223 | 0.885 | 20.819 |
| A6 迁移版 | | | | | | | | | |

每个子项取同一阶段在各 AICPU 线程上活动区间的并集，再算十轮均值；不同阶段可能交叠。L2 原生记录覆盖表中七项，计算前后还包含没有独立时间戳的工作。两版均关闭额外的 AICPU 生命周期细分开关。

### Host 调用

| 设备与等级 | bind | 发布镜像 | 准备执行 | 进入观察之前 | 观察设备完成 | 观察返回至 runner 结束 | 完整 chip.run |
| ---------- | ---: | -------: | -------: | -----------: | -----------: | ---------------------: | ------------: |
| A5 纯主线 L0 | 405.071 | 46.635 | 21.670 | 201.687 | 355.663 | 111.258 | 1331.731 |
| A5 纯主线 L2 | 446.249 | 41.064 | 29.786 | 312.381 | 700.180 | 50314.633 | 52256.573 |
| A5 迁移版 L0 | 484.904 | 49.471 | 21.016 | 198.450 | 330.182 | 168.092 | 1372.635 |
| A5 迁移版 L2 | 466.493 | 42.554 | 26.667 | 267.874 | 720.065 | 61181.775 | 63097.239 |
| A6 迁移版 L0 | | | | | | | |
| A6 迁移版 L2 | | | | | | | |

单位 µs。Host `chip.run` 包含设备执行和 Host 等待。三列观察相关时间都在 `runner_run` 内，使用同线程、同次派发的开始/返回事件配对。纯主线 L2 观察设备完成花费 700.180 µs，观察返回至 runner 结束花费 50.315 ms。后一段包含诊断回收、采集器收尾和记录导出，当前日志只能给出这段的合计。正式业务性能取 L0。

### 任务号、核体时间与分片

耗时取 **L1 单个 block 在一个 C 核或 V 核上的执行时间**，先按任务和核类型求单轮实例均值，再取 10 个正式轮次的均值。第一列的 t 号对应上方 **A5 纯主线 L2 run2** 泳道，括号内是原始 forward 的任务号。两版 A5 已实测；A6 实例数取自已编译计划，耗时和比值留待上板回填。比值用同一行的 A6 迁移版耗时除以 A5 迁移版耗时。

| A5 泳道任务（源码号） | 核类型 | A5 实例/轮 | A6 计划实例/轮 | A5 主线 µs | A5 迁移版 µs | A6 迁移版 µs | A6/A5 迁移版 |
| --------------------- | -----: | ---------: | -------------: | ---------: | -----------: | -----------: | -----------: |
| t14 _gather_sparse_vf_rows_aic（源 t22） | C | 24 | 48 | 16.448 | 16.111 | | |
| t14 _gather_sparse_vf_rows_aiv（源 t22） | V | 48 | 48 | 13.804 | 13.735 | | |
| t22 _quant_o_vf（源 t30） | V | 64 | 54 | 5.721 | 5.481 | | |
| t25 _o_proj_a_aic（源 t33） | C | 32 | 54 | 11.218 | 11.220 | | |
| t25 _o_proj_a_aiv（源 t33） | V | 64 | 54 | 15.193 | 15.647 | | |
| t26 _o_proj_b_hc_post_aic（源 t34） | C | 32 | 54 | 17.257 | 17.336 | | |
| t26 _o_proj_b_hc_post_aiv（源 t34） | V | 64 | 54 | 18.361 | 18.812 | | |

例如 gather（源 t22）在 A5 上每轮有 24 次 C、48 次 V，在 A6 上计划为 48 次 C、48 次 V。各行比较一次对应核执行的平均耗时。要看整个任务在某类核上从首个 block 开始到末个 block 结束用了多久，请看 CSV 的 `mean_span_us` 对应列。CSV 覆盖全部 19 项。[逐核 CSV](swa-l1-kernel-times.csv) · [A6 采集与回填](../../doc/a6-environment.zh-CN.md)

## A6 改动与验收边界

新版 SWA 来自主线固定的 PyPTO-lib `4cb7442261`，t34 已融合 O-B 和 mHC post。15 个计算任务使用 19 个业务核。A5 的分片共 632 次核执行。A6 为 54 个 1C1V 核组，将以下五项改成匹配物理核数的工作划分；每一行的每轮核执行数等于 block 数乘有效 C/V 角色数，全图合计 660。[任务表](../../../dsv41_scheduler/workloads/pypto_lib_latest/swa/tasks.tsv) · [计划适配](../../prepare_plan.py)

| 源码任务 | A5 分片 | A6 分片 | 每轮核执行 A5 → A6 |
| -------- | ------: | ------: | -----------------: |
| t12 QKV 量化 | 64 V | 54 V | 64 → 54 |
| t22 Attention gather | 24 × 1C2V | 48 × 1C1V | 72 → 96 |
| t30 输出量化 | 64 V | 54 V | 64 → 54 |
| t33 O-A 投影 | 32 × 1C2V | 54 × 1C1V | 96 → 108 |
| t34 O-B + mHC post | 32 × 1C2V | 54 × 1C1V | 96 → 108 |

末尾向量任务填满物理 V 核；在依赖闭合且两项 MIX 都填满核组时，调度器可提前绑定后两个任务的 C/V 与 block。A5 仍使用既有满宽规则。A6 以 54 个物理核组判宽，使用原组号。按半区异或的放置只用于满足其二次幂条件的组数。协议保留 C、V0、V1 三个逻辑位置，A6 的 V1 空置。[HBG 运行时说明](../../../../../src/a5/runtime/host_build_graph/docs/RUNTIME_LOGIC.md)

### 旧图的纯 C 投影和尾部第二批在 005 中的位置

**旧图用不满 C 核的是 O-B。** 004 的回放 t21（源 t29）是独立的纯 C 投影，原来只有 32 个 block。004 把 5120 列拆为 52 块 × 96 列和 2 块 × 64 列，让 54 个 C 核各有一块。005 保留了这套列切分，位置在融合后的回放 t26（源 t34）：每个 block 由一个 C 做 O-B、一个 V 做 mHC post。本例 80 行落在一个 128 行的行块内，共 54 个列块，恰好对应 54 组 1C1V。[004 同卡实验](../004-a6-swa-output-tiles/README.zh-CN.md) · [005 融合核](../../../dsv41_scheduler/kernels/pypto_lib_latest/vendor/external/o_proj_b_hc_post.cpp)

**005 仍有三个纯 C 任务沿用主线分片。** 按源码号，t16 Q-A、t19 KV 投影、t26 HC linear 分别是 20、8、4 个 C block，各自最多同时用 20、8、4 个 C 核。上表五项改动中，C 核分片的变化体现在 MIX 任务里。各纯 C 任务的实际耗时、以及改变分片是否有收益，仍需 A6 实测。[源码任务表](../../../dsv41_scheduler/workloads/pypto_lib_latest/swa/tasks.tsv)

**旧图的“尾部两轮”指同一个任务分两批领 block。** 00 的 A6 泳道里，输出量化 t17 和末尾 HC post t27 各有 64 个 V block，54 个 V 核中有 10 个要领第二次。005 尾部的三个任务（源 t30、t33、t34）各提交 54 个 block。t30 输出量化和 t33 O-A 仍各有 64 个计算 tile，分给 54 个 block 后，10 个 block 在同一次核调用内各多算一个 tile。末尾 t34 已融合 HC post，54 个 block 各处理一个列块。按计划，这三项都能由 54 组一批接下；实际启动是否齐整、核内负载是否拖尾，留给 A6 泳道核验。[旧图两批的逐核观测](../00-baseline/README.zh-CN.md#合并前的-device-wall-增量落在哪些区间) · [输出量化](../../../dsv41_scheduler/kernels/pypto_lib_latest/vendor/external/o_quant_vf.cpp) · [O-A 列切分](../../../dsv41_scheduler/kernels/pypto_lib_latest/vendor/external/o_proj_a.cpp)

图前部还有一个容量例外：源 t9 补零仍提交 80 个 V block，在 54 个 V 核上至少分两批执行。本例只给行号 72–79 补零（从 0 编号）。上板时可用源码号区分这项与输出尾部的三项。[补零核](../../../dsv41_scheduler/kernels/pypto_lib_latest/vendor/aiv/zero_bf16_padding.cpp)

### A6 完成计数故障 271

2026-11-23，A6 的 005 回放完成组包（15 个计算任务、计划每轮 660 次核执行、30 个缓冲区准备完成）。L0、L1、L2 各自在 run 0 返回 507018，20 s 后超时，0/108 个 worker 获得退出确认。三组均无 `result.json`，本次没有可归档的 A6 性能或 L2 泳道。L0 原始证据位于板上用例目录下的 `build/005-a6-QeZpqDMb/L0/rank0/ascend/debug/plog/plog-4077897_20261123170320381.log:58`，以下寄存器和反汇编来自同次板端采集。

| 核对项 | 板端证据 |
| ------ | -------- |
| Host 映射 | `planned_chains=4 mapped_chains=0 mapped_tasks=0`，Host 发布 `completion_counters_offset=0` |
| 首发异常 | die 0 的 AIC core 1 报 271；入口 PC 为 `0x120055e0022c`，原始 current 为 `0x120055eef410` |
| 触发指令 | SU 校正 PC 为 `0x120055eef2c4`。板上 ELF 的 `.text+0xef2c4` 为 `ST_DEV.b32 X26, [X3], #0`；`X3=0`、`X26=1`，即往地址 0 写 1 |
| 失败镜像 | 常驻 `aicore_kernel.o` 的 SHA-256 为 `8f71914174e16eb06cefdebac59307b0c53a9210cf34f3bf0307a0fb93281934` |

**根因与修复。** 主线 #3208 让 A5 真机在编译时假定 Host 已映射 CntNotify。A6 共用这段设备代码，Host 却用零偏移表示应走 GM。业务 block 返回时，常驻调度器跳过零偏移检查，误读计数器描述符的 `add_address`，最终在 `scheduler_notify_add` 写零地址。修复把“必有 CntNotify”的编译期假设限定在 A5 真机；A6 的普通完成、MIX 和异步完成分支共同遵循 Host 发布的映射状态。无映射时用已有 GM 完成状态记账。IPC0/IPC4 继续用于整轮启停和退出回执。[Host 发布偏移](../../../../../src/a5/runtime/host_build_graph/host/runtime_maker.cpp) · [设备端选择](../../../../../src/a5/runtime/host_build_graph/runtime/scheduler/scheduler_memory.h) · [完成记账](../../../../../src/a5/runtime/host_build_graph/runtime/scheduler/scheduler_completion.h) · [IPC 选址依据](../../doc/a6-migration.zh-CN.md#9-ipc-寄存器与退出协议)

**离线验证。** 对生产代码的零偏移路径分别用 A5 和 A6 的 CCE 参数编译 C/V 探针，检查 `scheduler_execution_uses_counter(scheduler_execution_counter_at(base, 0, task))`。修复前两端的 C/V 都返回 1；修复后 A6 的 C/V 返回 0，A5 的 C/V 仍返回 1。两端的 HBG 完整运行库均已重编，A5 常驻 AICore 镜像与修复前逐字节相同。

**复测口径。** 使用修复后的 HBG 运行库和同一份 005 回放包，先确认 A6 L0 生成 `result.json` 且数值通过，再采 L1 和 L2；L1 每个正式轮应覆盖 660 次业务核执行。[A6 复测命令](../../doc/a6-environment.zh-CN.md)

### A6 复测在 bootstrap 超时

板端反馈，修复 271 后的首次复测在 run 0 报 `bootstrap timeout: workers=108 dispatch_arrived=0 bootstrap_complete=0`，未生成 `result.json` 或 L2 泳道。AICPU 在放行业务核之前读到全局到达数为 0。A6 每组的 V0 先初始化组内信号，C 准备好首批任务后置位，V0 等组内就绪后才把全局到达数加 2。这个计数只反映已上报的完整核组，无法区分组内哪一步停住。本轮停在首次业务完成记账之前。[启动与组内计数](../../../../../src/a5/runtime/host_build_graph/aicore/resident_scheduler_impl.h)

`7f0d4fe57` 改动的开关也用于首批任务准备。无待发布的 MIX、无计数映射且协议跟踪关闭时，A6 的 V0 会检查组内 MIX 描述符。现有超时日志无法判断核是否停在这里。后续板端重新 prepare 并使用配套 runner 和修复版运行库后通过了 bootstrap。板端将前一次失败归因于产物混用，具体不匹配的文件尚无两次板端指纹可对照。[首批任务准备](../../../../../src/a5/runtime/host_build_graph/runtime/scheduler/scheduler_dispatch.h) · [MIX 描述符检查](../../../../../src/a5/runtime/host_build_graph/runtime/scheduler/scheduler_cluster_mix.h)

**修复前后组包对照。** 本地在 `7f0d4fe57` 重新 prepare，与留存的 `ad69fb740` 版 005 逐文件比对。回放包内全部 119 个文件（含计划、callable、输入和参考）、`native-runner` 和 `libreplay.so` 均逐字节一致。板端可先核对实际 runner 和回放包的指纹，再独立核对该进程加载的 Host、AICPU、AICore 和 dispatcher。注册日志里的 `aicore_image_hash` 覆盖 callable 内的业务核，常驻调度器镜像需核对 `aicore_kernel.o`。[005 包指纹](metrics.json) · [runner 加载入口](../../../dsv41_scheduler/production/runner.cpp) · [业务核指纹范围](../../../../../src/common/task_interface/chip_callable_layout.h)

### A6 重新组包后执行超时（site 95）

板端重新 prepare 并使用修复版运行库后通过 bootstrap，未再报 271，未见 AICore 异常。Host 仍为 `mapped_chains=0 mapped_tasks=0`。本轮设备日志为 `/tmp/opencode/005fix2-1qhy/rank0/ascend/debug/device-0/device-224035_20261123203901140.log`。`site=95` 对应 AICPU 执行进度看门狗。两次快照之间，15 个未完成任务的计数和领号字段均无变化。以下采用同轮完整日志，原先转述的 `task=18 total=32` 已由原始行校正。[15 行快照](metrics.json) · [超时快照字段](../../../../../src/a5/runtime/host_build_graph/aicpu/aicpu_executor.cpp)

| 回放任务（源码） | 核类型 | 已记完成 / 总数 | next_block |
| ---------------- | ------ | --------------: | ---------: |
| t0（源 t8）hc_collapse_norm | V | 0 / 20 | 20 |
| t8（源 t16）Q-A | C | 0 / 20 | 20 |
| t11（源 t19）KV 投影 | C | 0 / 8 | 8 |
| t18（源 t26）hc_linear | C | 3 / 4 | 4 |
| t10（源 t18）Q-B | C+V0 | 0 / 64 | 0 |

`source-task-map.txt` 按“源码号 回放号”写出，两行 `18 10`、`26 18` 与上表一致。快照合计 660 份中已记 3 份，全部来自回放 t18。它的 4 个普通 C block 已全部领号，每次成功返回向 GM 记 1 份，余数为 1；快照中没有缺失的 block 编号。Q-B 的 64 份计数全在，现有日志没有任何 MIX proxy 或 MIX members 行。MIX 的 V0 回执不能解释纯 C 任务 t18 的余数。[回放映射写入](../../../dsv41_scheduler/production/replay.cpp) · [普通返回记账](../../../../../src/a5/runtime/host_build_graph/runtime/scheduler/scheduler_completion.h)

005 留存的迁移版 A5 依赖图显示，两条支路的 t0 和 t18 均无业务前驱。t8、t11 虽已领号，执行仍依赖 t4，而 t4 经 t1 依赖 t0。排查应同时观察 t0 首批 V block 和 t18 四个 C block 的实际进入、返回及记账。按本轮任务顺序和 660 项计划，t0 的 prepared cell 索引为 0–19，t18 为 374–377，分别对应 block 0–3。在 CPU 上用 A6 的 54 组 1C1V、零 CntNotify 和 4 个纯 C block 做对照，3 个 block 记账后，第 4 个从尚未进入到空核函数已返回、尚未记账，两次读数都是 `total=4 remaining=1 debt=1 next_block=4`，其共享状态均为 `CLAIMED`。提交第 4 份完成后余数归零。全局超时的默认快照对每种状态最多列 8 项。[领号逻辑](../../../../../src/a5/runtime/host_build_graph/runtime/scheduler/scheduler_issue.h) · [执行前等待](../../../../../src/a5/runtime/host_build_graph/runtime/scheduler/scheduler_execution_tokens.h) · [超时逐项记录](../../../../../src/a5/runtime/host_build_graph/aicpu/aicore_scheduler_error.h)

**同轮 atrace 将排查优先级指向 t0。** 板端只打印了 t0 的 cell 0–7，均为 V0 的 `CLAIMED`。多颗 AIV 的 `CURRENT_PC` 落在板端标注的 func 6 `hc_collapse_norm` 地址段；按该地址归属，采样时已有 V 核进入业务代码。单次 PC 快照不能区分仍在执行和卡在具体指令。板端没有 t18 的 cell 374–377，也未报告落在 `hc_linear` 内的 PC。两条支路各自可启动，现有记录无法把 t18 缺的一份归因于 t0。[板端 PC 和 cell 摘录](metrics.json)

**板端 func 6 反汇编。** 以加载入口 `0x12000003b920` 为基准，多颗 AIV 的 `CURRENT_PC=0x12000003c2bc` 对应代码偏移 `+0x99c`、板端 ELF 地址 `0x199c`。附近依次为 `0x1988 WAIT_FLAGI_V.MTE3 #2`、`0x198c BAR.ALL`、从 `0x1990` 开始的返回现场恢复和 `0x19cc RET`。采样点在屏障之后 16 字节、RET 之前 48 字节。同轮另一个 AIV（core 0）的 `CURRENT_PC=0x12000003cafc` 位于该核 VF 辅助函数范围（`+0x11dc`）。这些样本将 t0 的首要排查范围缩到业务核内；现有快照没有流水线事件状态，无法锁定哪一个 wait，也无法由一条 PC 判定屏障已经完成。源码尾部依次等待事件 0、1、2，每组涵盖 V→MTE2、MTE3→MTE2、MTE3→V，再执行全流水线屏障。005 计划下每个 block 处理 4 行，现有采集没有各流水线事件的硬件状态。上述指令位置来自同轮板端反汇编。[t0 算子源码](../../../dsv41_scheduler/kernels/pypto_lib_latest/vendor/aiv/hc_collapse_norm.cpp) · [板端采样](metrics.json)

**004 对照。** 004 通过 A6 数值校验时，源 t8 使用 `_hc_collapse`（func 8，10 个 V block），其实现同样含 `pipe_barrier(PIPE_ALL)`。005 的源 t8 已换成 `hc_collapse_norm`（func 6，20 个 V block），编译时还单独链接六个 VF 辅助函数。004 验证的是旧核及其流水线顺序，不能据此判定新版哪个事件未满足。[004 验收](../004-a6-swa-output-tiles/README.zh-CN.md) · [005 任务表](../../../dsv41_scheduler/workloads/pypto_lib_latest/swa/tasks.tsv) · [005 核清单](../../../dsv41_scheduler/kernels/pypto_lib_latest/manifest.json)

### A6 的 t0 向量指令故障 331

**板端定位。** 首次 005 的 AIV 原始日志报 `core id=0, error code=331, current=0x12000003c2bc`。CANN 将 331 定义为 `VEC_INSTR_ILLEGAL_CFG_T0`，即硬件拒绝了一条 VF 指令的参数。该 PC 落在回放 t0（源 t8，func 6）`hc_collapse_norm` 内。另一次仅将 t0 减为 1 个 V block，仍为 `next_block=1 remaining=1`，采样 PC 对应 ELF `0x17f4`，位于调用辅助函数 `_2` 前的参数准备处。单个 t0 block 即可复现未完成。两次记录能把故障定位到 t0 的向量执行路径，尚不能判定哪项指令参数非法或哪条循环没有退出。AIC 的 271 已单独修复。[271 记录](#a6-完成计数故障-271) · [板端摘录和本地组包指纹](metrics.json)

**合并带入的变化。** 上游先在 #1803 统一四路 FP32 的相加顺序、BF16 舍入和 RMSNorm，并把归一化分块改为每块 4 行。随后 #1862 把这段 C++ 改写为 PyPTO 的 `pl.reg_scope()`。005 随 Simpler #3179 引入导出物，t0 的 C++ 入口需要链接六个 A5 VF 辅助函数。A6 的构建脚本修改 LLVM 目标属性再编译这些辅助函数。A5 已通过固定参考校验，A6 可以编译和链接，但上板报告了上述 331。[数值与分块变更 #1803](https://github.com/hw-native-sys/pypto-lib/pull/1803) · [RegScope 改写 #1862](https://github.com/hw-native-sys/pypto-lib/pull/1862) · [SWA 导入 #3179](https://github.com/hw-native-sys/simpler/pull/3179)

**A6 规避。** 取 #1862 父提交 `ad299c7f` 的 C++ 归一化分支，接到 005 的五参数入口（gamma、mix、输入、输出、token 数），由 A6 CCEC 直接编译。80 行仍分为 20 个 V block，四路依次相加、舍入到 BF16 再做 RMSNorm。A5 继续用主线导出物。新 A6 ELF 内由 C++ 生成一个本地向量函数，构建清单里 func 6 的 `vf_llvm` 为空。[上游 C++](https://github.com/hw-native-sys/pypto-lib/blob/ad299c7fc0c57091ae24ff17d52b0ae0506d5273/models/deepseek_v4_1_flash/kernels/hc_collapse.cpp#L95-L173) · [A6 核实现](../../kernels/hc_collapse_norm.cpp) · [构建选择](../../compile_kernels.py)

**验证进度（2026-11-24）。** A6 已离线重新 prepare。同一工具链下，19 个活跃核中仅 func 6 的指令区变化，回放包共 119 个文件，仅 `callable.bin` 变化，计划、输入和 25 份参考均逐字节一致。A5 也重新 prepare，19 个活跃核与原快照逐字节匹配。夹具与性能统计的 6 项离线测试通过。这次组包的 C++ t0（`392fae8b8`）作为本轮对照。

**C++ 核尾部超时。** 带 marker 的运行中，worker62（物理核 43）最后可见 stage35，下一条关键指令是 `BAR.ALL`。marker 覆盖了 premix 第 75–79 行，读端对最后一次写入的可见性也未验证，因而屏障是否返回仍未确定。无 marker 的寄存器归约候选保留了求和顺序和原有等待，离线核对两个最终 callable 只有 func 6 的机器码不同。黄区同卡 P0 各跑 1 轮，板端 func 6 指纹前缀分别为 `9e02d4ab`（原版）和 `a49b7221`（寄存器归约版）。两组均在 t0 block 2、owner 62 停在 CLAIMED，未完成 25 个输出校验。去掉 UB 散写不足以恢复整层执行。

**5-block t0 板端结果。** 5-block 计划组包校验通过，15 个任务、645 次核执行。无标记 L2 首轮 t0 通过，随后纯 V 回放 t4 `qkv_quant` 停在 `total=54 remaining=1`，缺的是 `block=8 owner=62`，prepared cell 为 `CLAIMED`。25 项输出校验未执行，无 result.json、L2 泳道和 L0 数据。004 的 worker62 跑过 qkv_quant block 18，其 t0 未分到 worker62。临时改 worker context 的实验在 t0 读到三个 0，没有取得这次 t4 的有效对照。

### 合并范围

合并提交 `cef3736bf` 的两个父提交是原适配分支 `1a89a12b4` 和主线 `48fd8fef3`。相对第一个父提交有 996 个变更文件，其中包括主线同期更新。相对第二个父提交有 96 个文件，84 个已出现在原 A6 分支的差异中。按目录计，独立 A6 用例、夹具、文档和历史结果 43 个，共用 SWA 套件 11 个，平台与 HBG 运行时 25 个，构建与分析工具 10 个，测试与 lint 7 个。#2978 与既有适配重叠 7 个文件，合并保留了公共任务 ID、共享运行资源与 A6 的生命周期明细偏移。后续运行器修复改在已有的 5 个文件内，005 报告及测量文件另计。

原始双卡 forward 需要每 rank 4,218,097,664 字节的激活空间。#2978 合入后的首轮准备在 2 GiB 限制处返回 -1004。只为完整双卡 HBG forward 配置 4 GiB 后重新从原始 forward 生成输入。两版单卡 SWA 复测仍使用 2 GiB 和同一个 runner。

正式归档的夹具有 118 个文件，逐个 SHA256 与本次原始 forward 导出的 SWA 匹配。两端从随仓夹具重新组包，A5 保留全部 81 个注册核的位置，A6 编出全部 19 个活跃核，二者使用相同的 25 份输出参考。A5 独立入口还在设备 0 通过单独的 1 次预热和 10 次正式轮校验，任务为 `task_20261123_160428_296472426588`。这批独立入口数据另作正确性验证。[快照指纹](../../fixtures/fixture.json)

### e56 三阶段读回

黄区在 `e56ed1cea` 的同一轮 A6 L2 回传了以下四行。Host 已启用 `worker=62 cells=645`。每列非零值是实际逻辑 worker 编号加一；0 表示快照未观察到该标记。

| 回放任务 | block | worker | pre | post | complete |
| -------- | ----- | ------ | --- | ---- | -------- |
| t4 qkv_quant | 8 | 62 | 63 | 0 | 0 |
| t4 qkv_quant | 0 | 54 | 55 | 55 | 55 |
| t4 qkv_quant | 1 | 55 | 56 | 56 | 56 |
| t1 zero_bf16_padding | 50 | 62 | 63 | 63 | 63 |

t4 block 8 已通过入口许可，最后可见的是调用前标记。e56 在间接调用返回后执行 `dsb(DSB_DDR)`，越过它才写 `post`。本轮足以将缺票缩到调用前标记和返回后标记之间，单凭这三个值还定位不到业务核内的指令。t1 仅清零第 72–79 行，block 50 跳过向量填充及 TSTORE，经过核尾和调度器后正常完成。t4 的两个正常 block 则实际经过同一套量化逻辑。此次仍因超时没有整层 L2 泳道；这里保存的是板端回传摘录。[调度器调用](../../../../../src/a5/runtime/host_build_graph/aicore/resident_scheduler_impl.h) · [补零条件](../../../dsv41_scheduler/kernels/pypto_lib_latest/vendor/aiv/zero_bf16_padding.cpp#L102) · [当前回放步骤](../../doc/a6-environment.zh-CN.md)

源 t12（func 8）使用导出的 C++ 和 `__pypto_vf_qkv_quant_0`。72 个有效行、80 个补齐行共排 100 个 tile，54 个 block 跨步取 tile。按零起算，block 8 的两个 tile 为 8 和 62，输入起点分别是第 0 行第 2048 列、第 48 行第 512 列，每个都读取 16 行 × 256 列。block 0 和 1 的两次迭代同样都是满块。地址和数据内容随 tile 变化，源码循环次数和有效行数相同。现有读回无法确定问题随数据分片还是执行它的 worker 状态变化。[A6 计划标量](../../adapt_plan.cpp) · [量化核分块](../../../dsv41_scheduler/kernels/pypto_lib_latest/vendor/aiv/qkv_quant.cpp#L356)

## 复测与产物

在项目虚拟环境中加载匹配 CANN，按使用说明编译纯主线与合并版的运行时，并在合并版构建同一 ABI 的 native runner；纯主线提供完整模型和测试 gate。以下变量分别指向这两个 checkout 和新的本地实验目录。EP2 capture 采用主线测试 gate，单卡 SWA 输入准备使用其对应的原始运行库。两套 HBG 都使用 DFX 构建，关闭额外编排、调度和 TensorMap 打点。[构建与 A6 单卡验收](../../doc/usage.zh-CN.md) · [配对采集脚本](collect-pair.sh)

```bash
driver="$migrated_repo/tests/fdwic/a6_dsv41_scheduler/results/005-main-swa/collect-pair.sh"
export PYTHONNOUSERSITE=1 SIMPLER_HBG_AICPU_DETAIL_ENABLE=0
bash "$driver" prepare "$main_repo" "$migrated_repo" "$gated_main_runtime" "$experiment/prepared"
bash "$driver" collect "$main_repo" "$migrated_repo" \
  "$experiment/prepared/cases/pypto_lib_latest/swa" "$experiment/same-card"
```

`metrics.json` 保存各轮 Host、设备和同步约束下界，以及测试二进制指纹。复测时，采集脚本在本地输出目录保留 console、Host 端点、运行结果、各轮任务映射、L1/L2 的采集记录与依赖，可据此重新生成汇总和泳道。随仓单卡快照包含实测输入及参考，可直接转到 A6 组包。

SWA 快照离线校验 3 项均通过。DSV4.1 扩展回归 63 项通过、1 项跳过，TMR 的 L0 计时补丁无法套用到更新后的 TMR 源文件。相同失败已在纯主线 `48fd8fef3` 复现。

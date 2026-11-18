# A6 SWA 迁移状态与适配说明

[返回索引](../README.zh-CN.md) · [当前交给 A6 端的任务](a6-environment.zh-CN.md) · [构建与复现命令](usage.zh-CN.md)

## 完成状态索引

**目标：单卡、生产 HBG 路线跑通独立 SWA，全流程不调用 PyPTO／PTOAS。当前已生成目标核和转换后的单卡回放包，组内拓扑与 SSBUF 已按 1C1V 修改；A6 HBG 和完整 SWA 尚未运行通过。** percounter、跨卡通信和性能优化不在首轮范围内。

- [x] [提取独立 SWA 与 A5 基线](#1-独立用例与依赖边界)：固定输入、参考、19 个核和生产回放入口已具备，A5 校验通过。
- [x] [接入 A6 核编译](#2-目标编译与构建隔离)：19／19 个核通过本地编译、链接和机器码提取；A5 机器码不变。
- [x] [适配输出投影的 1C1V 分工](#3-输出投影-t28由两个-v-改为一个-v)：修改列分片与同步，待 A6 数值验证。
- [x] [适配 Attention 的 1C1V 分工](#4-attention-t22拆分-head-与调整缓冲)：修改 head 分工、UB 和事件，待 A6 数值验证。
- [x] [实现 plan 校验与转换](#5-tensorplan-abi只改两处-mix-描述)：本地核对 2735 条记录，转换后 16 个任务、570 个执行实例。
- [x] [验证 MIX 启动与镜像内子核调用](#6-启动格式独立-mix-入口与计算核要分开)。两个独立编译的子核通过函数指针读参、写出 6／7 并返回。
- [x] [核对 SSBUF 容量、KFC 写入范围和 C/V 共享](#7-ssbuf调度区必须重排)。偏移 1792 的 96 B 状态完成 4 组并行、每组 8 轮握手。
- [x] [完成多 block 身份采样](#8-核编号与寄存器映射仍是平台缺口)。blockDim 1／2／4／27／54 各收到 2 × blockDim 条记录。
- [x] [校准 AICore 的 SYS_CNT](#9-计时采用-sys_cnt不使用-cube-主频)。此次实测约 1 GHz。
- [ ] [确认核身份与 CP1 窗口映射](#8-核编号与寄存器映射仍是平台缺口)。核对 C 入口原始读数与分组表的来源，取得寄存器偏移并验证启动／退出握手。
- [x] [适配 HBG 的双 lane 状态](#7-ssbuf调度区必须重排)。双 lane 状态为 120 B，使用偏移 1792；生产设备行为随 SWA 验收。
- [x] [生成 A6 原生回放包](#5-tensorplan-abi只改两处-mix-描述)。同一入口配套组装目标核、转换后的 plan、固定输入和参考。
- [ ] [接通 A6 HBG 并验收 SWA](#验收要求)：直接执行单卡 SWA，检查完整输出和正常退出。

本页按适配点维护结论、改动和证据，更新至 **2026-11-18**。A6 端只在 [任务单的回答区](a6-environment.zh-CN.md#本轮回答区) 填写并返回一份 MD，关键代码／命令／日志以内嵌片段提供。收到结果后归入本页对应条目，更新勾选状态，再清空回答区、刷新未解决任务。勾选“代码／离线适配完成”不代表设备验收完成。

## 适配点与核实结论

### 1. 独立用例与依赖边界

**问题：原流程要跑双卡完整 forward 捕获任务，容易被误认为 SWA 本身也需要两卡和 PyPTO。**

**已做：** 固化 [输入、plan 和参考](../fixtures/fixture.json)，只编译 SWA 的 19 个核，复用生产 C++ runner、HBG 和原 PR 统计器。C++ 源码在 [vendor](../../dsv41_scheduler/kernels/pypto_lib_latest/vendor/)，入口为 [prepare.py](../prepare.py) 和 [run.py](../run.py)。已有用例无需重新捕获：编译不占卡，独立 SWA 执行只用一张卡。

解除的是 PyPTO／PTOAS 的代码生成依赖；C++ 仍需 CANN、PTO-ISA 编译成 AICore 机器码，执行仍需适配 A6 的 Simpler。新 PyPTO 算子的生成流程见 [执行原理](execution.zh-CN.md)。

**验证：** A5 HBG／percounter 各 11 轮通过，每轮检查 30 个可写 Device buffer；L0 AICore 均值为 **0.267843／0.185173 ms**，见 [A5 结果](a5-results-2026-11-17.zh-CN.md)。本轮 A6 沿用已有零权重夹具，不新增局部非零用例。SWA 覆盖 MIX／sync_start，不覆盖跨卡通信或 defer_wait。

### 2. 目标编译与构建隔离

**问题：A5 目标、SDK 自带 PTO 与仓库 pin 混用，不能得到可核查的 A6 核。核能编译也不等于运行时已支持 A6。**

**已做：** [compile_kernels.py](../compile_kernels.py) 使用 `dav-920r1-cube/vec`，逐核执行 ccec → `ld.lld -e kernel_entry` → `.text` 合法性检查。优先使用仓库 pin 的 PTO-ISA `83b1b2b52ded9ec5d91e02532a57cd95e497ba86`；A5／A6 输出和缓存分开，失败不继续组包。

| 适配项 | 处理与依据 |
| ------ | ---------- |
| 原始核 17／19 通过 | 两个 AIC 核的 `DualModeSplitM/N` 被 A6 拒绝；对应 AIV 的分工也必须一起改，见第 3、4 项 |
| PTO 头文件优先级 | 修正 include 顺序，避免误用 SDK 自带 PTO；此前错误顺序的编译不计入原核基线 |
| `-fno-jump-tables` | 保留。[elf_parser.py](../../../../simpler_setup/elf_parser.py) 只装载 `.text`，拒绝外置已分配数据；开关检查观察到 `.rodata` 差异 |
| VF AA 选项 | 保留 `-mllvm -cce-vf-aa-between-iters=true`；已检查的 4 个核开关前后 `.text` 相同，不推广为所有核都无影响 |
| 三种编译目标 | Host 用 x86_64 工具，AICPU 用 aarch64 交叉工具，AICore 用 ccec；三者不能混用 |
| 项目构建环境 | 沿用当前 Makefile 的 `DEPFILE` 构建路径需 CMake ≥3.20；项目 `.venv` 提供工具，不要求升级系统。命令见 [使用方法](usage.zh-CN.md) |

**验证：** 适配后 A6 **19／19** 通过本地编译、链接和机器码提取；A5 的 19 个 `.text` 指纹与改动前逐一相同。证据见 [checks.json](../results/2026-11-17-a6-offline/checks.json)。这是目标编译结果；A6 SDK 复核、设备参数 ABI 和运行结果仍待验证。

### 3. 输出投影 t28：由两个 V 改为一个 V

**问题：A5 一次算 256 列，分别交给 V0、V1；A6 只有一个 V，不能只把两次搬运都改成 `SingleModeVec0`。** 同 pin PTO-ISA 的 `include/pto/npu/a6/SyncAll.hpp` 提供 1C1V 依据，独立 MIX 探针也与之相符。

**已改：** [o_proj_a.cpp](../../dsv41_scheduler/kernels/pypto_lib_latest/vendor/external/o_proj_a.cpp) 在 A6 每次计算 128 列，增加内部列循环；单 V 量化、写回后继续另一半。READY／RELEASE／STORE_DONE 与生产者等待同步改为一个消费者。

```text
A5 一个 block：C 算 256 列 → V0 前 128 列 + V1 后 128 列
A6 一个 block：C 算 128 列 → V 处理 → 列循环继续另一半
```

32 个 block 保持不变，执行实例 **96 → 64**；量化与写回算法保留，没有新增 GM 中转或工作区。编译已通过，A6 同步与数值结果待验证。

### 4. Attention t22：拆分 head 与调整缓冲

**问题：原一个 block 的 C 计算 64 个 head，由两个 V 分担；单 V 不能直接承接原分工和双目标搬运。**

**已改：** [sparse_gather_vf.cpp](../../dsv41_scheduler/kernels/pypto_lib_latest/vendor/external/sparse_gather_vf.cpp) 用两个 1C1V block 分担原来的 head。核内 `block/2`、`blocks/2` 保留 token、区间和 partial 槽位，`block%2` 选择 head 的前后半。

```text
A5：b    → C(64 heads) + V0(32 heads) + V1(32 heads)
A6：2b   → C(前 32 heads) + V(完整 KV、前 32 heads)
    2b+1 → C(后 32 heads) + V(完整 KV、后 32 heads)
```

| 变化 | 具体处理 |
| ---- | -------- |
| block／实例 | 24 → 48 个 block，72 → 96 个执行实例；输入、输出和工作区大小不变 |
| 数据搬运 | 单 V gather 从 32 扩至 64 条，C 算 32 行并向单 V 搬运；保留 softmax、PV 累积和分片合并算法 |
| UB | raw／NZ 缓冲增大后为 **333184 B（325.375 KiB）**，低于查询得到的 376 KiB |
| 事件编号 | 修正初版超出 0–7 的编译错误：NZ 的 MTE3↔V 用 5／6／2／3，P staging 用 7；MTE2↔V 的 raw 事件属于另一管线对 |

编译已通过，A6 计算与同步正确性待验证。两个 block 会重复读取 KV，因此后续跨代性能比较包含分片变化，不能都归为调度收益。其余独立 AIV 任务的 80／64／64 个逻辑 block 保留，需要运行时支持多波次推进。

### 5. Tensor／plan ABI：只改两处 MIX 描述

**问题：** [record.h](../../dsv41_scheduler/production/record.h) 直接保存 `Header`、`Operand` 和 `TensorData`，不是跨 Host 架构的自描述格式；A5 的 1C2V plan 也不能直接驱动 A6 核。

**已改：** [prepare_plan.py](../prepare_plan.py) 在目标 Host 编译原生解码和转换工具，先核对全部 **2735 条记录**的规范化语义指纹，再由 [adapt_plan.cpp](../adapt_plan.cpp) 转换 t22／t28。任何非预期差异立即报错；原始夹具不覆盖。

| 检查对象 | 转换要求／结果 |
| -------- | -------------- |
| t22 | 24 个 1C2V block → 48 个 1C1V block |
| t28 | 32 个 1C2V block → 32 个 1C1V block |
| 总量 | 16 个任务不变；执行实例 **578 → 570** |
| 其余字段 | Tensor 字段、shape／stride／offset、别名、buffer 标识、标量、依赖和其他任务逐项保持一致 |
| 重复转换 | 非零退出且不创建输出，防止 Attention block 再次翻倍 |

本地 aarch64 Host 解码／转换已验证，见 [plan-conversion.json](../results/2026-11-17-a6-offline/plan-conversion.json)。A6 的 x86_64 Host 仍需执行同一检查；通过只说明 Host 记录格式可用，设备参数传递还需第 6 项的实际调用验证。本地已通过 `prepare.py build --platform a6` 完整组包，生产 runner 能读回相同的 19 个子核 ID、参数签名及编排签名。构建结果保存 plan 与 callable 的 SHA256，单卡入口在执行前核对两者。[构建与运行](usage.zh-CN.md#单卡-a6-swa)

### 6. 启动格式：独立 MIX 入口与计算核要分开

**已核实：** 11-18 探针结果给出以下启动差异，最小核已不再卡在最初的二进制版本错误。

| 被测路径 | 结果 |
| -------- | ---- |
| 将 `dav-920r1-vec` 的 ELF 直接交给 ACL 启动 | 报告的 `e_flags=0xa50000`；失败 507015，设备错误 259：`binary version does not match` |
| 通用 `dav-920r1` 的 MIX ELF | 报告的 `e_flags=0xa60000`；`aclrtBinaryLoadFromFile` → `aclrtBinaryGetFunction` → `aclrtLaunchKernelWithHostArgs` 执行成功 |
| 单 block MIX | GM 原子计数为 2；AIV 的 `get_subblockdim()` 为 1，支持 1C1V 结论 |
| 成功样例的链接参数 | `ld.lld -Ttext=0 -static -n -e probe`，该样例不需要 `-m aicorelinux` |

**外层和子核的调用已经在同一镜像内分两步验证。** 通用 MIX 目标生成 C/V 两个入口。按第二轮的编译期标记，每个入口分别走 `__DAV_CUBE__` 或 `__DAV_VEC__` 分支。

| 调用方式 | 构建与寻址 | 单 block 结果 |
| -------- | ---------- | ------------- |
| 静态链接 | `sub_c` 用 `dav-920r1-cube`，`sub_v` 用 `dav-920r1-vec`。通过 `sub_c.cube` 和 `sub_v.vector` 符号别名与外层链接 | C/V 写出 `CCUBE`／`VECTOR`。V 读到 coreid 35，C 读到 0 |
| 镜像内函数指针 | `sub_c2`／`sub_v2` 分别以 `-Ttext=0 -e <入口>` 链接，用 `llvm-objcopy --only-section=.text` 提取各 24 B，以 256 B 对齐放入同一可执行镜像 | 输入 `x=5`，结果 `out_c=6, out_v=7, C_done=1, V_done=1`。两个子核均读到参数并返回外层 |

第二步由外层按 `(PC - pc_offset) + blob_offset` 得到入口。该镜像反汇编给出 C/V 的 `pc_offset` 为 `0x114/0x294`，两个 blob 偏移为 `0x300/0x400`。这些参数描述本次链接布局。探针覆盖了这两段机器码的提取、给定对齐下的间接调用、参数传递和返回。

**SWA 直接沿用生产装载。** 保留 cube／vec 子核的 `.text`，由 HBG 上传整个 `ChipCallable` 后解析入口并调用。已测镜像内入口按 256 B 对齐；生产对象的子项偏移按 `CALLABLE_ALIGN=64` 排列，子核入口的 ABI 对齐保证是 `CALLABLE_CHILD_ALIGN=16`。目前没有 A6 要求 256 B 的依据。镜像外取指随 SWA 首跑覆盖，如实际出现取指错误，优先核对该子核的入口、对齐和装载方式。[装载布局](../../../../src/common/task_interface/arg_direction.h) · [Host 上传](../../../../src/common/platform/onboard/host/device_runner_base.cpp) · [调用入口](../../../../src/a5/runtime/host_build_graph/aicore/resident_scheduler_impl.h)

### 7. SSBUF：调度区必须重排

常量下标探针以 `__ssbuf__` 逻辑基址 0 访问，偏移 0、4、1020、1024、2040、2044 写入并读回 `0x2222`。偏移 2048、3072、4096 报 507015，设备错误 271（internal buffer out of bounds）。A6 此入口的边界为 **2048 B**。A5 运行时在 `[2048,3072)` 预留调度区，迁移时必须改址。[调度状态定义](../../../../src/a5/runtime/host_build_graph/runtime/scheduler/scheduler_cluster_signal.h)

| 项目 | 核实结果与适配依据 |
| ---- | ------------------ |
| KFC 结构 | `MIX_NUM=1` 时，`sizeof(KfcMsg)=128`、`sizeof(MsgMatmulL1Addr)=32`、`sizeof(TCubeTiling)=200`、`sizeof(TilingInfo)=208`、`sizeof(SsbufWorkspaceDesc)=1488`，单位 B |
| KFC 清零范围 | `dav_9201/kfc/kfc_comm.h` 的 `ClearSSbufImpl()` 在消息区外还显式写偏移 1536 和 1744 的 32 位字。最高一次写覆盖 `[1744,1748)`。仅按这段代码计算，其后的尾部 `[1748,2048)` 有 300 B |
| 代码使用的调度区 | 双 lane 类型经编译断言为 120 B，`anchor_state` 偏移 72。选择 `[1792,1912)`，低端距已知 KFC 清零边界 44 B，高端距 SSBUF 末尾 136 B。A5 三 lane 仍为 136 B、偏移 2048 |
| 实际握手 | 在偏移 1792 放入 **96 B 探针状态**。4 个 block 同时运行，每组 8 轮，`bad=0`。C/V 往返的数据和序号均通过校验，测试期间未见串组 |
| 探针记录限制 | 报告指出 C 的整行 `dcci` 覆盖了同一 GM cache line 上 V 的完成标记。此项以 SSBUF 往返校验为依据。后续 C/V 写回记录分用独立 cache line |

通过的同步序列如下，flag 和管线按实测写法保留。

```text
C 写 payload、seq → dsb(DSB_ALL) → set_intra_block(PIPE_S, 13)
V wait_intra_block(PIPE_S, 13) → 校验 → 写 response、ack
V dsb(DSB_ALL) → set_intra_block(PIPE_MTE3, 12)
C wait_intra_block(PIPE_S, 12) → 校验 ack、response
```

生产 HBG 的状态布局和访问入口按平台 lane 数选择区域。A6 板上已通过的是 96 B 状态、flag 配合 DSB 的握手。120 B 状态在生产调度循环中的可见性随 SWA 执行验证；沿用非阻塞调度，未把探针使用的阻塞 flag 插入调度循环。[共享布局](../../../../src/common/host_build_graph/cluster_signal_layout.h) · [调度访问入口](../../../../src/a5/runtime/host_build_graph/runtime/scheduler/scheduler_cluster_signal.h)

### 8. 核编号与寄存器映射仍是平台缺口

**采样完整性已验证。** Host 预填 `0xDEADBEEFDEADBEEF`，C/V 用编译期入口标记区分，各自原子领取独立 GM 槽、写回原始身份并执行 `dcci`。blockDim 取 1、2、4、27、54，计数均为 `2 × blockDim`，无缺失。第二轮报告两入口的 `get_subblockdim()` 都为 1，角色应按入口标记区分。

| 报告中的分组 | C 的编号范围 | V 的编号范围 | 本轮列出的 local 值 |
| ------------ | ------------ | ------------ | ------------------- |
| die 0 | 0–34 | 35–69 | 0–8、10–21、23、24、26、27、33、34 |
| die 1 | 70–104 | 105–139 | 0–6、9–14、16–27、33、34 |

每行列出 27 个 local，共 54 对。报告按同一 block 配对后列出 `V=C+35`、跨 die 编号区间相差 70。HAL 数据为 54 AIC、54 AIV、`DIE_NUM=2`、`IN_USED=54`、`ERROR_MAP=0`，AICPU 8、`OCCUPY=0x7f8`、`ts_num=1`。这批 local 的跳号不提供屏蔽原因或 `res_id` 对应关系。

**C 原始 ID 的来源仍有歧义。** 报告一处写 54 block 有 108 个不同 coreid，另一处写 ACL 探针及子核里的 AIC `get_coreid()/get_block_idx()` 均为 0。若 54 条 C 记录原始 ID 全为 0，同一批 C/V 最多只有 55 个不同原始 ID。单 block 得到 0 本身正常。优先用已有记录区分多 block 与单 block 的读数、直接读取与按配对推算的列，再决定 C 侧解码。早期未分组的 AIV 样本含 2 等值，也应以带入口标记的样本为准。已列编号均在 `0x0FFF` 范围内，掩码是否适用于 A6 仍待核对。

**CP1 控制窗口仍需平台依据。** `halResMap(RES_AICORE, PROCESS_CP1)` 对 `res_id 0..69` 返回成功，保持映射时 70 个 VA 各异，每窗 `0x200000`（2 MiB），测试的 70 及以上返回 17。其他被测进程类型、A3 式 `halMemCtl` Host 直映射均返回 `0xfffe NOT_SUPPORT`。映射 VA 属于 CP1。有效计算组与 `res_id` 的对应关系、窗内 C/V 起点、`DATA_MAIN_BASE/COND` 的偏移、宽度和访问方仍缺。11-18 的计算探针只写 GM 和 SSBUF，寄存器启动／退出握手待验证。

### 运行时还缺什么

当前分支有 A6 核编译目标，尚无可执行的 A6 HBG 平台实现。需要补齐以下契约后接入，复用已确认兼容的公共逻辑，并集中隔离硬件差异。

| 接口 | 当前 A5 代码 | A6 待确定／修改 |
| ---- | ------------ | --------------- |
| 身份与窗口 | [host_regs.cpp](../../../../src/a5/platform/onboard/host/host_regs.cpp)：按 2 die、每 die 18 个 C 和 C／V0／V1 布局计算索引 | 逻辑配对已有 1C1V 依据；需要上报物理 ID 到 `res_id` 及窗内 C/V 基址的对应关系 |
| 控制寄存器 | [platform_config.h](../../../../src/a5/platform/include/common/platform_config.h)：定义 `DATA_MAIN_BASE`、`COND` 等偏移 | A6 的 C/V 窗口、寄存器偏移、访问宽度和读写方；据平台资料或已有实现接入，由 SWA 的启动与退出覆盖 |
| 组内协同 | [scheduler_cluster_mix.h](../../../../src/a5/runtime/host_build_graph/runtime/scheduler/scheduler_cluster_mix.h) 与 SSBUF 状态 | 双 lane 布局和逻辑组队已改；准备／完成与退出随 SWA 验收 |
| 构建与执行入口 | [platform_info.py](../../../../simpler_setup/platform_info.py)、[build_runtimes.py](../../../../simpler_setup/build_runtimes.py)、[prepare.py](../prepare.py)、[run.py](../run.py) | 用例已接单卡入口；尚需构建 A6 的 Host、AICPU、AICore 和 dispatcher 运行库 |

**已改的逻辑拓扑。** AICPU 组队接受每个 C 配一个或两个 V；Host 共享状态按平台 block 上限预留组数；AICore 的准入检查按实际 V 数校验同组 worker。例：54 个 block 的紧凑启动下，逻辑组 7 是 C worker 7 和 V worker 61。这个例子可以确定如何派活；找到这两个核的寄存器仍需物理窗口表。[组队](../../../../src/a5/runtime/host_build_graph/aicpu/aicore_lifecycle.cpp) · [准入](../../../../src/a5/runtime/host_build_graph/runtime/scheduler/scheduler_admission.h)

**剩余平台输入**集中在[当前任务单](a6-environment.zh-CN.md)。取得映射与寄存器协议后，由本仓接目标平台构建、MIX 外层与 dispatcher，直接用同一包执行 SWA。已有 SSBUF、核调用及计时结论沿用。

### 9. 计时：采用 SYS_CNT，不使用 Cube 主频

**已核实：** SYS_CNT 差值 `2000136085`，对应 Host 间隔 `2.000147 s`，测得 **999.994 MHz，约 1 GHz**。这支持当前 A6 探针使用与 A5 相同的 1000 MHz 换算；Cube／Vector 的 1800 MHz 不是该计时器频率。`DEV_OSC_FREQUE` 查询不支持，不再等待它给出静态值。

这解决 AICore 时间换算依据；AICPU 自身计时与跨处理器时间原点对齐仍需后续核对，不作为本轮 SWA 功能验收前提。

## 环境与证据

| 项目 | 已核对的信息 |
| ---- | ------------ |
| 目标与 Host | Ascend960DT_966B7／Ascend960DT；x86_64、Ubuntu 20.04.6 |
| 存储 | L1 512 KiB、L0A/B 各 64 KiB、L0C 256 KiB、UB 376 KiB、L2 128 MiB；可见 HBM 175.88 GiB |
| CANN／驱动 | CANN 9.3.0，组件时间戳 `20261103_000323501`；驱动 `7.12.T0.0.B280`、ascendhal `7.35.23` |
| AICore 工具链 | ccec clang／LLD 15.0.5；目标宏 `__NPU_ARCH__=9201`、`__CCE_AICORE__=920`；`dav-9201-*` 不是可用目标名 |
| Host／AICPU 工具链 | 查询数据为 Host g++ 9.4.0、AICPU 交叉 g++ 14.3.0；不要把交叉编译器用于 Host plan 工具 |
| 构建环境初始查询 | Python 3.11.14／3.14.8、CMake 3.16.3，未配置 Ninja／项目 venv；按 [使用方法](usage.zh-CN.md) 准备后记录实际生效版本 |
| 版本边界 | 初始环境查询对应 `4b2d9ca4b501c57abeea4a9dc86e0f6d08bedab4`，不包含后续适配；离线核与 plan 的版本以各自 provenance 为准。11-18 探针的已知构建条件与数值见第 6–9 项 |

环境与编译查询细节保存在 [查证数据](a6-env-reprot.md) 和 [数据明细](a6-evidence-2026-11-17)。初始查询未取得 die 数，后续 `halGetDeviceInfo` 已补为 2；不能把 query 中固定打印的“2 AIV per cluster”当作 A6 配对证据。

| 验证材料 | 结果与范围 |
| -------- | ---------- |
| [A5 归档](../results/2026-11-17-a5/) | HBG／percounter 各 11 轮的运行、输出比较和 L0 样本；本次整理未重测 |
| [A6 离线检查](../results/2026-11-17-a6-offline/checks.json) | 19／19 编译／链接／提取通过、A5 机器码相同、拒绝重复转换；设备执行与数值检查均为 `not_run` |
| 本轮代码回归 | A6 回放包完成目标编译与原生组包，16 任务、570 实例；A5 原生组包通过。A5 HBG 调度契约 36 项及固定夹具 2 项通过。A6 单卡输出待验证 |
| [plan 转换](../results/2026-11-17-a6-offline/plan-conversion.json) | 2735 条记录解码、约定字段转换及其他字段不变；原夹具的两项检查也通过 |
| [版本与参数](../results/2026-11-17-a6-offline/provenance.json) | 离线检查在 aarch64 Host 执行；同目录保留前后汇总、源码／工具指纹与失败日志。最终编译起止见 `*-after-run.json`，早期基线精确起止未知 |
| 11-18 硬件探针结果 | 第 6–9 项按接口归入两轮查证结果及第 12 节调用补测。身份取自分组汇总，未附逐槽流水。子核补测使用 `outer4.cpp`、`sub_c2.cpp`、`sub_v2.cpp`、`link.ld`、`dumpX2.cpp` |

仅保留当前待补材料在 [任务单](a6-environment.zh-CN.md)；已有证据文件不随任务单覆盖。编译产物留在 `build/`，不提交大二进制。

## 验收要求

1. **生产路径可用：** A6 Host 建图、AICPU 启动／握手、AICore HBG 调度与完成真实执行。直接通过 SWA 执行两处 MIX 任务，覆盖上传、调度、完成与退出。
2. **SWA 完整执行：** 使用本分支转换的 16 任务／570 实例计划和对应 A6 核；多波次、MIX 依赖与退出正常，沿用全部 30 个可写 Device buffer 的检查。出现误差先定位，不静默放宽比较器。
3. **结果可复核：** 记录实际提交、SDK／工具、编译／链接／启动命令和失败阶段；确认没有调用 PyPTO／PTOAS、没有误用 A5 缓存。代码和离线修改由本仓维护，A6 端返回编译／单卡验证结果；后续按构建、平台、核、组包边界拆分中文提交。
4. **结论范围明确：** 零权重夹具通过不代表真实权重精度；首轮不要求 percounter 或性能对比。后续计时分列 AICore 窗口、Device wall，并说明硬件、Host、SDK 与分片差异；L3 不混入 L0。

本切片不验证 MoE。后续若扩展，需区分固定回放与 native Host 编排；原 `pypto_lib_latest/moe` 标记 `numerical_validation: false`，不能沿用 SWA 的数值校验结论，见 [原用例说明](../../dsv41_scheduler/README.md)。

# A6 SWA 迁移状态与适配说明

[返回索引](../README.zh-CN.md) · [当前交给 A6 端的任务](a6-environment.zh-CN.md) · [构建与复现命令](usage.zh-CN.md)

## 完成状态索引

**目标：单卡、生产 HBG 路线跑通独立 SWA，全流程不调用 PyPTO／PTOAS。当前已完成核与 plan 的离线适配，独立硬件探针已有结果；A6 HBG 和完整 SWA 尚未运行通过。** percounter、跨卡通信和性能优化不在首轮范围内。

- [x] [提取独立 SWA 与 A5 基线](#1-独立用例与依赖边界)：固定输入、参考、19 个核和生产回放入口已具备，A5 校验通过。
- [x] [接入 A6 核编译](#2-目标编译与构建隔离)：19／19 个核通过本地编译、链接和机器码提取；A5 机器码不变。
- [x] [适配输出投影的 1C1V 分工](#3-输出投影-t28由两个-v-改为一个-v)：修改列分片与同步，待 A6 数值验证。
- [x] [适配 Attention 的 1C1V 分工](#4-attention-t22拆分-head-与调整缓冲)：修改 head 分工、UB 和事件，待 A6 数值验证。
- [x] [实现 plan 校验与转换](#5-tensorplan-abi只改两处-mix-描述)：本地核对 2735 条记录，转换后 16 个任务、570 个执行实例。
- [x] [查明独立 MIX 探针的启动格式](#6-启动格式独立-mix-入口与计算核要分开)：通用 `dav-920r1` ELF 已执行，支持 1C1V；尚未覆盖生产 HBG 调用链。
- [x] [取得 SSBUF 边界与计时结果](#7-ssbuf调度区必须重排)：被测入口的 SSBUF 可访问边界为 2 KiB，SYS_CNT 约 1 GHz。
- [ ] [完成 SSBUF 适配](#7-ssbuf调度区必须重排)：核对实际占用、C/V 共享与屏障，重排调度区并验证真实访问代码。
- [ ] [补齐核编号与寄存器映射](#8-核编号与寄存器映射仍是平台缺口)：关联 C/V、物理 ID、`res_id` 与控制窗口。
- [ ] [验证外层 MIX 调用计算核](#6-启动格式独立-mix-入口与计算核要分开)：验证独立核的函数地址、参数传递和返回。
- [ ] [接通 A6 HBG 并验收 SWA](#验收要求)：验证最小任务链、完整输出和正常退出。

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

本地 aarch64 Host 解码／转换已验证，见 [plan-conversion.json](../results/2026-11-17-a6-offline/plan-conversion.json)。A6 的 x86_64 Host 仍需执行同一检查；通过只说明 Host 记录格式可用，设备参数传递还需第 6 项的实际调用验证。A6 包重新编译核，不携带 A5 机器码。

### 6. 启动格式：独立 MIX 入口与计算核要分开

**已核实：** 11-18 探针结果给出以下启动差异，最小核已不再卡在最初的二进制版本错误。

| 被测路径 | 结果 |
| -------- | ---- |
| 将 `dav-920r1-vec` 的 ELF 直接交给 ACL 启动 | 报告的 `e_flags=0xa50000`；失败 507015，设备错误 259：`binary version does not match` |
| 通用 `dav-920r1` 的 MIX ELF | 报告的 `e_flags=0xa60000`；`aclrtBinaryLoadFromFile` → `aclrtBinaryGetFunction` → `aclrtLaunchKernelWithHostArgs` 执行成功 |
| 单 block MIX | GM 原子计数为 2；AIV 的 `get_subblockdim()` 为 1，支持 1C1V 结论 |
| 成功样例的链接参数 | `ld.lld -Ttext=0 -static -n -e probe`，该样例不需要 `-m aicorelinux` |

**对适配的影响：外层可启动 ELF 与被调度的计算核 `.text` 是两层。** 当前核编译脚本生成 `kernel_entry(__gm__ int64_t *args)`，供运行时函数指针调用；它不是直接交给 ACL 的顶层入口。不能据此把全部 SWA 核改成通用 MIX，也不能把独立探针成功等同于 HBG 成功。

```text
独立探针：Host ACL → MIX ELF 的 C/V 入口 → 写 GM → 返回
生产路径：Host 注册运行时 ELF → AICPU 启动／握手 → HBG AICore 调度器
                                              → 调用核 .text → 完成任务
```

**待适配／验证：** 按 A6 成功样例处理运行时外层 ELF 的编译、链接、入口和启动参数；再用外层 C/V 入口分别调用独立编译的简单核，核对参数、输出与返回后的完成标记。参考 [运行时构建](../../../../src/a5/platform/onboard/aicore/CMakeLists.txt)、[Host 启动](../../../../src/common/platform/onboard/host/device_runner_base.cpp) 和 [核调用](../../../../src/a5/runtime/host_build_graph/aicore/resident_scheduler_impl.h)。这项可以先做最小探针，不必等完整 HBG。

### 7. SSBUF：调度区必须重排

**已核实：** `__ssbuf__` 以 0 为逻辑基址。常量下标探针在偏移 **0、4、1020、1024、2040、2044** 写入并读回 `0x2222`；偏移 **2048、3072、4096** 报 507015／设备错误 271（internal buffer out of bounds）。这些结果支持被测入口 **2 KiB 可访问边界**；自写自读尚不能证明 C/V 共享及不同配对之间的隔离。

**明确要改：** A5 的 [scheduler_cluster_signal.h](../../../../src/a5/runtime/host_build_graph/runtime/scheduler/scheduler_cluster_signal.h) 把调度区放在 `[2048, 3072)`，在上述边界外。当前 A5 状态结构为 136 字节、预留 1 KiB；改为两个 lane 后还要重新计算结构大小、字段偏移及静态断言。

| 适配点 | 处理要求与当前状态 |
| ------ | ------------------ |
| 调度区位置 | 在 2 KiB 内选择空闲区，**尚未确定偏移**；不能直接占用 KFC 自 0 开始的区域 |
| SDK／核的占用 | 按实际编译宏核对 `asc/impl/basic_api/dav_9201/kfc/kfc_comm.h` 的 `SsbufWorkspaceDesc`、`ClearSSbufImpl` 及实际调用路径。`MIX_NUM` 影响结构，清零代码还含固定数量访问，不能只用 `sizeof` 判空闲 |
| C/V 可见性 | 待做 C 写→V 读→C 收到确认的序号握手；验证发布／读取屏障及多配对隔离，再用于调度状态 |
| 访问代码 | 探针报告动态偏移写法失败、常量结构下标成功。需补源与反汇编，并验证真正的 `scheduler_cluster_signal_at`／字段访问；尚不能泛化为所有动态指针都有编译器缺陷 |

PTO-ISA／KFC 使用相似结构不代表 A5 的 3 KiB 布局可直接复用。容量结果已足以确定需要改址，尚不足以确定新地址与屏障。

### 8. 核编号与寄存器映射仍是平台缺口

**已核实的数据：**

| 项目 | 结果 | 可以据此判断什么 |
| ---- | ---- | ---------------- |
| 资源与 die | AIC 54、IN_USED 54、ERROR_MAP 0、AIV 54、DIE_NUM 2；AICPU 8、OCCUPY `0x7f8`、ts_num 1 | 核数与查询到的错误图已知；不能推出物理编号连续或每 die 的具体映射 |
| AIV 原始 ID | 采样到 2、35、37、38、70、74、76、83、84、87、92、105 等 | 需要解码与关联；这些值都在 `0x0FFF` 内，**不能据此认定 A5 的掩码错误** |
| AIC 身份 | 探针读到 `get_coreid()`／`get_block_idx()` 为 0 | 单 block 的逻辑 block 0 正常；物理 ID 是否正确须多 block、独立输出槽复核，不能直接判定 ACL 未初始化身份 |
| `halResMap` | `RES_AICORE / PROCESS_CP1` 的 `res_id 0..69` 成功，70+ 返回 17；每个窗口 `len=0x200000`，保持映射时 VA 各异 | 映射接口可用；70 个可映射槽不等于 70 个有效计算组 |
| 访问方 | 其他被测进程类型返回 `0xfffe NOT_SUPPORT`；A3 的 Host 直映射接口也不支持 | 返回 VA 属于 CP1／AICPU，不能由 Host 解引用；这与 A5 的 AICPU 访问方式一致，不要求新增 Host 直映射 |

这里的 **2 MiB 是寄存器映射窗口长度，2 KiB 是 SSBUF 访问边界**，不是同一块存储。

### 运行时还缺什么

当前分支有 A6 核编译目标，尚无可执行的 A6 HBG 平台实现。需要补齐以下契约后接入，复用已确认兼容的公共逻辑，并集中隔离硬件差异。

| 接口 | 当前 A5 代码 | A6 待确定／修改 |
| ---- | ------------ | --------------- |
| 身份与窗口 | [host_regs.cpp](../../../../src/a5/platform/onboard/host/host_regs.cpp)：按 2 die、每 die 18 个 C 和 C／V0／V1 布局计算索引 | 原始核 ID → C/V 配对 → worker → `res_id` 的关联；有效资源筛选 |
| 控制寄存器 | [platform_config.h](../../../../src/a5/platform/include/common/platform_config.h)：定义 `DATA_MAIN_BASE`、`COND` 等偏移 | A6 的 C/V 窗口、寄存器偏移、访问宽度和读写方；由资料或已工作的实现确认，再做握手验证 |
| 组内协同 | [scheduler_cluster_mix.h](../../../../src/a5/runtime/host_build_graph/runtime/scheduler/scheduler_cluster_mix.h) 与 SSBUF 状态 | 1C1V 的 lane mask、准备／完成／退出协议，以及第 7 项的内存布局与可见性 |
| 构建与执行入口 | [platform_info.py](../../../../simpler_setup/platform_info.py)、[build_runtimes.py](../../../../simpler_setup/build_runtimes.py)、[prepare.py](../prepare.py)、[run.py](../run.py) | Host、AICPU、AICore 和 dispatcher 成套构建；接入 A6 HBG 单卡入口，隔离 A5 缓存 |

寄存器验证不应写成“等 HBG 跑通再验证”。可从 [AICPU 查询示例](../../../../tools/cann-examples/aicpu-device-query/README.md) 准备独立的 AICPU 小程序，先证明启动与 GM 返回，再按**已确认的**偏移关联窗口与 C/V。当前不能猜偏移后扫描／试写 MMIO。

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
| 版本边界 | 初始环境查询对应 `4b2d9ca4b501c57abeea4a9dc86e0f6d08bedab4`，不包含后续适配；离线核与 plan 的版本以各自 provenance 为准。11-18 探针的关键实现与生效参数待在任务单回答区补齐 |

环境与编译查询细节保存在 [查证数据](a6-env-reprot.md) 和 [数据明细](a6-evidence-2026-11-17)。初始查询未取得 die 数，后续 `halGetDeviceInfo` 已补为 2；不能把 query 中固定打印的“2 AIV per cluster”当作 A6 配对证据。

| 验证材料 | 结果与范围 |
| -------- | ---------- |
| [A5 归档](../results/2026-11-17-a5/) | HBG／percounter 各 11 轮的运行、输出比较和 L0 样本；本次整理未重测 |
| [A6 离线检查](../results/2026-11-17-a6-offline/checks.json) | 19／19 编译／链接／提取通过、A5 机器码相同、拒绝重复转换；设备执行与数值检查均为 `not_run` |
| [plan 转换](../results/2026-11-17-a6-offline/plan-conversion.json) | 2735 条记录解码、约定字段转换及其他字段不变；原夹具的两项检查也通过 |
| [版本与参数](../results/2026-11-17-a6-offline/provenance.json) | 离线检查在 aarch64 Host 执行；同目录保留前后汇总、源码／工具指纹与失败日志。最终编译起止见 `*-after-run.json`，早期基线精确起止未知 |
| 11-18 硬件探针结果 | 第 6–9 项保存已返回的值与错误码；关键代码／命令／日志片段待补齐。完整材料由 A6 端留存，本文不作为完整探针复现包 |

仅保留当前待补材料在 [任务单](a6-environment.zh-CN.md)；已有证据文件不随任务单覆盖。编译产物留在 `build/`，不提交大二进制。

## 验收要求

1. **生产路径可用：** A6 Host 建图、AICPU 启动／握手、AICore HBG 调度与完成真实执行。先通过普通 AIV／AIC、依赖链及 MIX 最小验证，再运行 SWA；独立 ACL 探针不能代替这一项。
2. **SWA 完整执行：** 使用本分支转换的 16 任务／570 实例计划和对应 A6 核；多波次、MIX 依赖与退出正常，沿用全部 30 个可写 Device buffer 的检查。出现误差先定位，不静默放宽比较器。
3. **结果可复核：** 记录实际提交、SDK／工具、编译／链接／启动命令和失败阶段；确认没有调用 PyPTO／PTOAS、没有误用 A5 缓存。代码和离线修改由本仓维护，A6 端返回编译／单卡验证结果；后续按构建、平台、核、组包边界拆分中文提交。
4. **结论范围明确：** 零权重夹具通过不代表真实权重精度；首轮不要求 percounter 或性能对比。后续计时分列 AICore 窗口、Device wall，并说明硬件、Host、SDK 与分片差异；L3 不混入 L0。

本切片不验证 MoE。后续若扩展，需区分固定回放与 native Host 编排；原 `pypto_lib_latest/moe` 标记 `numerical_validation: false`，不能沿用 SWA 的数值校验结论，见 [原用例说明](../../dsv41_scheduler/README.md)。

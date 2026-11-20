# SWA 独立用例

**A5 和 A6 都已通过单卡 HBG 的 SWA 输出校验。用已有 C++ 核、固定输入和参考输出即可构建和复测，全流程不调用 PyPTO／PTOAS。**

| 问题 | 当前结论 |
| ---- | -------- |
| 测什么 | DSV4.1 的 SWA 注意力子层，含 mHC、量化、Q/KV 投影、缓存更新、Attention 和输出投影 |
| 规模 | 16 个计算任务，19 个计算核。A5 有 578 个执行实例，A6 迁移基线有 570 个，004 的 A6 默认分片有 616 个 |
| A5 结果 | 11 月 17 日 HBG 和 percounter 均逐轮校验通过，后续 HBG 同口径数据见复测报告 |
| 已完成的提取 | 只编 SWA 所需核，随目录保存固定输入和参考，复用生产 runner 与原 PR 统计器 |
| A6 状态 | 004 默认组合通过 30／30 个可写缓冲区校验。L0 核窗口 290.068 µs、Device wall 377.707 µs，较同批对照分别缩短 8.37% 和 6.51%。[004 性能表](results/004-a6-swa-output-tiles/README.zh-CN.md) |
| 依赖边界 | 仍需 CANN、PTO-ISA 和匹配的 Simpler；解除的是 PyPTO／PTOAS 的代码生成依赖 |

SWA 包含 MIX／sync_start 协同，但本切片没有跨卡通信和 deferred 等待。因此它适合验证计算与调度，双卡 MoE／defer_wait 需要后续独立验证。

## 文档索引

| 要看什么 | 文档 | 内容 |
| -------- | ---- | ---- |
| A6 单卡 SWA 目前做到哪一步 | [迁移进展简报](doc/a6-swa-progress.zh-CN.md) | 逐项适配清单、输出校验和 A5／A6 单卡性能总表 |
| A6 用什么环境、核对了什么 | [环境与适配核对表](doc/a6-evidence-2026-11-17) | 芯片与工具版本、1C1V 编译约束、控制窗口和 SWA 校验结果 |
| 怎么构建、运行和复测 | [使用方法](doc/usage.zh-CN.md) | 命令、参数、输出位置、修改后需要重编什么 |
| 为什么不依赖 PyPTO／PTOAS | [执行原理](doc/execution.zh-CN.md) | 已有材料、真实执行路径、依赖边界、全新算子的生成流程 |
| A6 迁移完成了什么、怎样适配 | [迁移状态与适配说明](doc/a6-migration.zh-CN.md) | 开头勾选索引；逐项说明问题、改动、核实结论、验证范围和剩余缺口 |
| 如何复测 A6 | [同口径复测](doc/a6-environment.zh-CN.md) | 同口径复测命令、待查问题和回答区 |
| 性能优化到了哪个阶段 | [性能优化阶段索引](doc/a6-optimization.zh-CN.md) | 各阶段的改动、报告、指标 JSON 与可归档的泳道 |
| 优化开始时 A5 和 A6 的性能如何 | [A5／A6 性能复测报告](results/00-baseline/README.zh-CN.md) | PR 的 L0 数据、Host 耗时、L3 的 AICPU 前后段拆解和详细泳道 |

平台适配结论归入迁移说明，性能实验按阶段归入 `results/`，并在优化索引登记。

## 代码与数据

| 位置 | 用途 |
| ---- | ---- |
| [prepare.py](prepare.py) | 解包输入，编译 SWA 核与原生工具，组装运行包 |
| [compile_kernels.py](compile_kernels.py) | 独立检查 A6 的 19 个核：编译、链接、提取机器码；不启动设备 |
| [prepare_plan.py](prepare_plan.py)、[adapt_plan.cpp](adapt_plan.cpp) | 按选定的 A6 分片生成计划，逐条核对原始记录与允许的改动 |
| [run.py](run.py) | A5 单卡性能复测；A6 单卡 HBG 功能验收入口 |
| [test_fixture.py](test_fixture.py) | 离线检查输入包与参考覆盖 |
| [fixtures/](fixtures/) | 固定输入、plan、参考与来源清单 |
| [performance.py](performance.py) | 统计 PR 指标与 AICPU 生命周期耗时，导出详细泳道 |
| [A5 详细泳道](results/00-baseline/swa-a5-hbg-L3-detail.json.xz) | 单卡 HBG 的 L3 泳道，含 AICPU 生命周期细分 |

使用说明和阶段索引在 `doc/`，性能报告及泳道在 `results/<阶段>/`。构建产物写入 `build/`，测试工作目录由 `--output` 指定。

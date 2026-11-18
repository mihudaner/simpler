# SWA 独立用例

**A5 的独立 SWA 已跑通；已有 C++ 和输入足以完成构建、执行与校验，全流程不调用 PyPTO／PTOAS。A6 原生 SWA 回放包已生成，1C1V 组队与 SSBUF 布局已改；A6 首跑已到设备组内初始化，SWA 输出待验。首轮只跑 HBG，percounter 与性能后续再考虑。**

| 问题 | 当前结论 |
| ---- | -------- |
| 测什么 | DSV4.1 的 SWA 注意力子层，含 mHC、量化、Q/KV 投影、缓存更新、Attention 和输出投影 |
| 规模 | 16 个计算任务：13 个单核任务、3 个 MIX 任务各用 C/V 两段程序，合计 19 段不同的计算核代码。按 block 展开后，A5 为 578 个执行实例，A6 为 570 个 |
| A5 结果 | HBG／percounter 均逐轮校验通过；L0 AICore 均值分别为 0.267843／0.185173 ms |
| 已完成的提取 | 只编 SWA 所需核，随目录保存固定输入和参考，复用生产 runner 与原 PR 统计器 |
| A6 状态 | 窗口映射与 IPC 接口已核实，108 个 worker 已报到。组内初始化仍按 1C2V 等待，CP1 尚未发出启动值。退出回执另有寄存器读写不一致，修正后需复跑 SWA |
| 依赖边界 | 仍需 CANN、PTO-ISA 和匹配的 Simpler；解除的是 PyPTO／PTOAS 的代码生成依赖 |

SWA 包含 MIX／sync_start 协同，但本切片没有跨卡通信和 deferred 等待。因此它适合验证计算与调度，双卡 MoE／defer_wait 需要后续独立验证。

## 文档索引

| 要看什么 | 文档 | 内容 |
| -------- | ---- | ---- |
| 怎么构建、运行和复测 | [使用方法](doc/usage.zh-CN.md) | 命令、参数、输出位置、修改后需要重编什么 |
| 为什么不依赖 PyPTO／PTOAS | [执行原理](doc/execution.zh-CN.md) | 已有材料、真实执行路径、依赖边界、全新算子的生成流程 |
| A6 迁移完成了什么、怎样适配 | [迁移状态与适配说明](doc/a6-migration.zh-CN.md) | 开头勾选索引；逐项说明问题、改动、核实结论、验证范围和剩余缺口 |
| 本轮交给 A6 端查什么 | [当前查证任务](doc/a6-environment.zh-CN.md) | 优先级、未解决项与回答区；只返回此 MD，内嵌关键代码／日志 |
| A5 跑出了什么结果 | [2026-11-17 复测报告](doc/a5-results-2026-11-17.zh-CN.md) | 性能与波动、校验范围、版本、失败记录、复现与证据 |

**维护方式：A6 端填写任务单回答区 → 结论和适配归入迁移说明 → 清空回答区、刷新剩余待办。已有证据文件保留不覆盖。**

## 代码与数据

| 位置 | 用途 |
| ---- | ---- |
| [prepare.py](prepare.py) | 解包输入，编译 SWA 核与原生工具，组装运行包 |
| [compile_kernels.py](compile_kernels.py) | 独立检查 A6 的 19 个核：编译、链接、提取机器码；不启动设备 |
| [prepare_plan.py](prepare_plan.py)、[adapt_plan.cpp](adapt_plan.cpp) | 校验原 plan 的 Host 解码结果，只转换两处 MIX 任务描述 |
| [run.py](run.py) | A5 单卡性能复测；A6 单卡 HBG 功能验收入口 |
| [test_fixture.py](test_fixture.py) | 离线检查输入包与参考覆盖 |
| [fixtures/](fixtures/) | 固定输入、plan、参考与来源清单 |
| [results/2026-11-17-a5/](results/2026-11-17-a5/) | A5 逐轮数据、日志和校验和清单 |
| [results/2026-11-17-a6-offline/](results/2026-11-17-a6-offline/) | A6 编译前后、A5 机器码不变、plan 转换的离线证据；不含设备结果 |

文档集中在 `doc/`；构建产物写入 `build/`，新的测试输出由 `--output` 指定。

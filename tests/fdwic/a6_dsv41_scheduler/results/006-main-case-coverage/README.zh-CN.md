# 006　A6 单卡原始 VF 回放：Engram 与三种 Attention

截至 2026-11-25，官方主线 `a6e2a87b9` 有 **7 个模型用例，其中 5 个可单卡回放、2 个需要双卡通信**。默认测量矩阵还包含 1 个单卡合成用例，共 8 项。006 选择 Engram、SWA、C1A reuse 和 C1A reindex。主线七项中的 C2A full 列在范围表中，留待后续测试。[主线测量入口](https://github.com/hw-native-sys/simpler/blob/a6e2a87b988dc409e2ecf42aa2d02bc1b066cb1b/tests/fdwic/dsv41_scheduler/production/list_cases.py) · [主线用例定义](https://github.com/hw-native-sys/simpler/blob/a6e2a87b988dc409e2ecf42aa2d02bc1b066cb1b/tests/fdwic/dsv41_scheduler/README.md#cases)

## 整图性能

每轮实例数取自对应平台的 006 计划，MIX 的 C、V 成员分别计数。实测栏留空待填，时间单位为 µs。输出校验填“通过数/参考数”；同一用例的 A5、A6 使用相同参考。

| 配置                  | 每轮实例（计划） |   输出校验 | 计算前 | L0 核窗口 | 计算后 | L0 Device wall | L0 同步约束下界（据 L1 估算） | L0 距下界 |
| --------------------- | ---------------: | ---------: | -----: | --------: | -----: | -------------: | ----------------------------: | --------: |
| A5 · `engram` | 160 | 17/17 | 70.423 | 121.335 | 34.436 | 226.194 | — | — |
| A6 · `engram`      |              160 |      17/17 | 71.744 |   177.119 | 33.885 |        282.748 |                            — |        — |
| A5 · `swa`         |              632 |         — |     — |        — |     — |             — |                            — |        — |
| A6 · `swa`         |              592 | 失败（t0） |     — |        — |     — |             — |                            — |        — |
| A5 · `c1a_reuse`   |              577 |         — |     — |        — |     — |             — |                            — |        — |
| A6 · `c1a_reuse`   |              481 | 失败（t0） |     — |        — |     — |             — |                            — |        — |
| A5 · `c1a_reindex` |              730 |         — |     — |        — |     — |             — |                            — |        — |
| A6 · `c1a_reindex` |              586 | 失败（t0） |     — |        — |     — |             — |                            — |        — |

L0 Device wall = 计算前 + 核窗口 + 计算后。下界针对核窗口，用同平台、同配置的 L1 逐核耗时和计划中的同步约束求解。L0 距下界 =（L0 核窗口 / 下界 − 1）× 100%。[下界模型](../../../dsv41_scheduler/BOUND.md)

## L2 核侧调度与执行

[A5 Engram run1 泳道图](a5/engram/engram-a5-L2-run1.json.xz) · [Engram 两项差值分析与三个 Attention 的 C++ 回放待办](../../doc/a6-environment.zh-CN.md)

按用例、平台和成员类型统计单次执行各阶段的平均耗时（µs）。实例/轮列为计划数，Engram 仅有普通 C/V。两张表回填时一并记录实测提交、预热轮数和正式轮数；若 L2 仅取代表轮，则注明轮次。

| 平台与成员或任务                | 实例/轮（计划） | 领取或绑定 | 观测前驱 | 就绪及发布 | READY→领取 | 入核准备 | 业务核体 | 核返回→观察完成 | 本地完成与释放 |
| ------------------------------- | --------------: | ---------: | -------: | ---------: | ----------: | -------: | -------: | ---------------: | -------------: |
| A5 · `engram` · 普通 C | 32 | 2.131 | 20.390 | 0.367 | 0.788 | 0.651 | 53.454 | 0.598 | 0.442 |
| A6 · `engram` · 普通 C      |              32 |      3.370 |    6.761 |      0.406 |       0.985 |    0.768 |   77.950 |            1.460 |          0.387 |
| A6 − A5 · `engram` · 普通 C | — | +1.239 | -13.629 | +0.039 | +0.197 | +0.117 | +24.496 | +0.862 | -0.055 |
| A5 · `engram` · 普通 V | 128 | 2.072 | 35.751 | 0.432 | 6.448 | 0.524 | 7.997 | 0.564 | 0.493 |
| A6 · `engram` · 普通 V      |             128 |      3.045 |   45.742 |      0.385 |       2.505 |    0.656 |   10.299 |            1.258 |          0.269 |
| A6 − A5 · `engram` · 普通 V | — | +0.973 | +9.991 | -0.047 | -3.943 | +0.132 | +2.302 | +0.694 | -0.224 |
| A5 · `swa` · 普通 C         |              32 |         — |       — |         — |          — |       — |       — |               — |             — |
| A6 · `swa` · 普通 C         |              32 |         — |       — |         — |          — |       — |       — |               — |             — |
| A5 · `swa` · 普通 V         |             272 |         — |       — |         — |          — |       — |       — |               — |             — |
| A6 · `swa` · 普通 V         |             272 |         — |       — |         — |          — |       — |       — |               — |             — |
| A5 · `swa` · MIX C          |             120 |         — |       — |         — |          — |       — |       — |               — |             — |
| A6 · `swa` · MIX C          |             144 |         — |       — |         — |          — |       — |       — |               — |             — |
| A5 · `swa` · MIX V          |             208 |         — |       — |         — |          — |       — |       — |               — |             — |
| A6 · `swa` · MIX V          |             144 |         — |       — |         — |          — |       — |       — |               — |             — |
| A5 · `c1a_reuse` · 普通 C   |              32 |         — |       — |         — |          — |       — |       — |               — |             — |
| A6 · `c1a_reuse` · 普通 C   |              32 |         — |       — |         — |          — |       — |       — |               — |             — |
| A5 · `c1a_reuse` · 普通 V   |             193 |         — |       — |         — |          — |       — |       — |               — |             — |
| A6 · `c1a_reuse` · 普通 V   |             193 |         — |       — |         — |          — |       — |       — |               — |             — |
| A5 · `c1a_reuse` · MIX C    |             128 |         — |       — |         — |          — |       — |       — |               — |             — |
| A6 · `c1a_reuse` · MIX C    |             128 |         — |       — |         — |          — |       — |       — |               — |             — |
| A5 · `c1a_reuse` · MIX V    |             224 |         — |       — |         — |          — |       — |       — |               — |             — |
| A6 · `c1a_reuse` · MIX V    |             128 |         — |       — |         — |          — |       — |       — |               — |             — |
| A5 · `c1a_reindex` · 普通 C |              36 |         — |       — |         — |          — |       — |       — |               — |             — |
| A6 · `c1a_reindex` · 普通 C |              36 |         — |       — |         — |          — |       — |       — |               — |             — |
| A5 · `c1a_reindex` · 普通 V |             198 |         — |       — |         — |          — |       — |       — |               — |             — |
| A6 · `c1a_reindex` · 普通 V |             198 |         — |       — |         — |          — |       — |       — |               — |             — |
| A5 · `c1a_reindex` · MIX C  |             176 |         — |       — |         — |          — |       — |       — |               — |             — |
| A6 · `c1a_reindex` · MIX C  |             176 |         — |       — |         — |          — |       — |       — |               — |             — |
| A5 · `c1a_reindex` · MIX V  |             320 |         — |       — |         — |          — |       — |       — |               — |             — |
| A6 · `c1a_reindex` · MIX V  |             176 |         — |       — |         — |          — |       — |       — |               — |             — |

### A5 / A6 `engram` 单卡对比

2026-11-26 在 A5 Ascend950DT_9582 设备 5 补跑，队列任务 `task_20261126_193147_24163167166`。A5 使用 `a6-migrate-case@98c141a26` 的 HBG 和本机 CANN 9.3.0 自带的 PTO-ISA。Host 构建仅为旧版通信工作区接口做了适配；Engram 单 rank、通信窗口为零。三个业务核取自 006 的 A5 快照，计划、输入和 17 份参考输出与 A6 组包逐项一致。A5 的 L0（无预热，单轮）与 L2（预热 1 轮，正式 10 轮）均通过数值校验。[A5 逐轮指标及构建信息](a5/engram/metrics.json) · [A5 原始泳道、计时端点及校验结果](a5/engram/capture.tar.xz)

上表对齐两端 L2 的首个正式轮 run1，每项取同类实例的均值。差值为 **A6 − A5**，正值表示该阶段 A6 耗时更长。A6 数字沿用 006 已记录的 run1 均值，仓内回放包只提供输入、参考和执行文件。

- **普通 C（32 个投影实例）**：A6 观测前驱少用 13.629 µs，业务核体多用 24.496 µs。领取或绑定、核返回到观察完成分别多用 1.239 和 0.862 µs。
- **普通 V（64 个量化、64 个门控实例）**：A6 从 READY 到领取少用 3.943 µs，观测前驱多用 9.991 µs，业务核体多用 2.302 µs。前驱观测包含依赖等待，不同实例的区间可以重叠。
- **整轮计时**：L2 run1 核窗口为 A5 98.909、A6 160.566 µs，Device wall 为 A5 446.807、A6 419.074 µs。窗口外耗时分别为 347.898 和 258.508 µs。A5 的 10 个正式轮核窗口均值为 99.051 µs，Device wall 均值为 448.018 µs。

### A6 `engram` 实测归档

`engram` 使用当前 A6 `build/006-a6-engram`，3 个业务核，无独立 VF helper。已归档：

- [L0](a6/engram/L0/result.json)：首次单轮，输出校验通过。
- [L2](a6/engram/L2/result.json)：预热 1 轮、正式 10 轮，`passed=true`、`numerical_validation=true`；17 份输出参考通过。
- 原始 L2 泳道记录位于 `a6/engram/L2/run1` 至 `run10` 的 `chip_swimlane_records.json`，以及对应 Host/`deps.json`。
- [汇总数据](a6/engram/metrics.json)
- 组包清单见 `a6/engram/L2/build.json`。

L0 填首次通过轮，L2 填 run1 的代表轮数据；L2 的 10 轮核窗口/Device wall 已汇总到 `a6/engram/metrics.json`。`swa`、`c1a_reuse`、`c1a_reindex` 均先停在 t0，未进入 L2。
**本轮判读：** A6 上仅 `engram` 通过校验并进入 L2；L0 单轮核窗口 177.119 µs、Device wall 282.748 µs。L2 代表轮 run1 的核窗口 160.566 µs、Device wall 419.074 µs；L2 核窗口低于单次 L0 是首轮/轮次波动，不宜当作性能下降。`engram` 只有普通 C/V，C 核体 77.950 µs，V 核体 10.299 µs，前驱等待 V 侧 45.742 µs 明显高于 C 侧 6.761 µs。

A6 三个 Attention 用例都在 t0 `hc_collapse_norm` 阻塞，因此 `c1a_reuse`/`c1a_reindex` 新增核没有得到执行机会；当前数据不能说明新算子通过或失败，只能说明它们被同一个 20-block t0/原始 VF 早期路径挡住。A5 本次仅补跑 Engram，三个 Attention 用例仍待采集。

## 主线用例范围

| 模型用例         | 正式运行卡数 | 跨卡通信                    | A6 复现范围                                                                                                                                        |
| ---------------- | -----------: | --------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| `swa`          |            1 | 无                          | 第 0 层滑窗注意力。005 的共享 C++ 五分块配置已通过 25/25 份参考，可作复用起点。[005 实测](../005-swa-a5-baseline-a6-timeouts/README.zh-CN.md)       |
| `engram`       |            1 | 无                          | 第 1 层量化、投影、门控。仅 3 个任务，均为普通 AIV 或 AIC，可首先验证新切片的打包与输出。                                                          |
| `c1a_reuse`    |            1 | 无                          | 第 21 层复用索引。15 个任务，按计算核名与 SWA 重合 16 个，新增 3 个。适合首先扩展 Attention。                                                      |
| `c1a_reindex`  |            1 | 无                          | 第 24 层刷新索引。19 个任务，相对 SWA 新增 9 个核名，覆盖索引投影、打分和 top-k。                                                                  |
| `c2a_full`     |            1 | 无                          | 第 2 层完整 C2A。26 个任务，相对 SWA 新增 15 个计算核名，其中 `_c2a_compress__2`、`idx_k_norm_rope_publish` 另外链接 VF helper。               |
| `moe`          |            2 | EP2 dispatch / combine      | 原生入口保留 Host token 数读取、向对端发布及等待。完整用例需要两个 rank，主线明确拒绝冻结成单卡回放。                                              |
| `layers_19_21` |            2 | 层内 MoE dispatch / combine | 三层共 144 个任务，含 `dispatch_push`、`combine_notify` 和远端等待。可单测其中的局部 Attention，例如已单列的 `c1a_reuse`；完整三层仍需双卡。 |

核名按各切片的 `tasks.tsv` 拆分 MIX 成员后去重，排除无计算核的 `control`。核名重合表示可复用已有适配经验，分块、参数与输出仍须按各自计划验证。合成用例 `synthetic/full_wave_mix_chain` 无跨卡通信，原计划含 1C2V 的 MIX 满波；A6 的 1C1V 拓扑需要另行适配。[模型任务表](../../../dsv41_scheduler/workloads/pypto_lib_latest/) · [主线合成用例](https://github.com/hw-native-sys/simpler/blob/a6e2a87b988dc409e2ecf42aa2d02bc1b066cb1b/tests/fdwic/dsv41_scheduler/README.md#cases)

## 哪些模型用例经过 `pl.reg_scope()` 的导出路径

按主线任务表中的活跃核名核对导出清单的 `vf_llvm` 字段。下表统计需要链接独立 VF helper 的**业务核数**。同一业务核可链接多个 helper，设备 C++ 内部使用向量寄存器另计。[模型核清单](../../../dsv41_scheduler/kernels/pypto_lib_latest/manifest.json) · [独立 MoE 核清单](../../../dsv41_scheduler/kernels/native_moe/manifest.json)

| 用例                                    | 带独立 VF helper 的核数 | 与 005 的关系                                                                                                                                                                 |
| --------------------------------------- | ----------------------: | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `engram`                              |                       0 | 三个活跃核均不依赖这条导出路径。                                                                                                                                              |
| `swa`、`c1a_reuse`、`c1a_reindex` |                    各 4 | 都是 `hc_collapse_norm`、`qkv_quant`、`norm_rope_publish`、`mhc_sinkhorn`。005 以设备 C++ 替换了这四个核。006 的三个 Attention 包均链接原来 6、1、8、1 个 VF helper。 |
| `c2a_full`                            |                       6 | 除上述四核，还包括 `_c2a_compress__2`（2 个 helper）和 `idx_k_norm_rope_publish`（1 个 helper）。这两处超出了 005 四核 C++ 的覆盖范围。                                   |
| `moe`                                 |                       5 | 独立 MoE 清单包含 HC collapse、Sinkhorn 和三个路由核。                                                                                                                        |
| `layers_19_21`                        |                      10 | 除 SWA 四核，还涉及 HC collapse、Sinkhorn 的另一版本，三个路由核和索引发布核。                                                                                                |

## 006 对照与输入

**源码与组包提交 `26e7946e6`。四套 A6 包均已离线编译，板端结果见上表。** 板端要检验的是原始 VF 导出路径在 A6 上能否完成计算、通过对应层的输出校验。三个 Attention 都保留 20 个 HC collapse block、64 个 QKV block 和原始 VF；MIX 使用 A6 的一个 C 和一个 V，单 V 覆盖 A5 原先由两个 V 完成的工作。005 的 5-block 和四核 C++ 结果另列为历史对照。[005 问题与证据](../005-swa-a5-baseline-a6-timeouts/issues.zh-CN.md)

| 006 用例                            | 原始层与源任务范围   | 任务数 | A6 计划成员执行数 | 输出参考数 | 其中的 `mhc_sinkhorn`    |
| ----------------------------------- | -------------------- | -----: | ----------------: | ---------: | -------------------------- |
| [engram](a6/engram.tar.xz)           | 第 1 层，71–73      |      3 |               160 |         17 | 无，只有量化、投影和门控   |
| [swa](a6/swa.tar.xz)                 | 第 0 层，8–34       |     15 |               592 |         25 | 源任务 27，12 个 V block   |
| [c1a_reuse](a6/c1a_reuse.tar.xz)     | 第 21 层，1389–1415 |     15 |               481 |         26 | 源任务 1408，12 个 V block |
| [c1a_reindex](a6/c1a_reindex.tar.xz) | 第 24 层，1575–1609 |     19 |               586 |         33 | 源任务 1602，12 个 V block |

三个 Attention 在各自的层调用同一份 `mhc_sinkhorn` 计算混合系数，也共用 HC collapse、QKV 量化和 norm/RoPE 等核。每个包读取该层的真实边界输入，和原始前缀加切片产生的参考逐项比较。C1A reuse 使用已有索引，C1A reindex 还执行索引投影、打分和 top-k。Engram 作为独立对照，用于检验不含这四个 VF 核的普通 C/V 回放路径。[第 21 层任务表](../../../dsv41_scheduler/workloads/pypto_lib_latest/c1a_reuse/tasks.tsv) · [模型层类型定义](https://github.com/hw-native-sys/pypto-lib/blob/4cb74422616359b3f95c598b1f9cdd31cf4e4173/models/deepseek_v4_1_flash/decode_layer.py#L508)

## A6 拉取与运行

从 fork 的 `a6-migrate-case` 分支拉取。在已分配单卡的 A6 主机加载 CANN 9.3.0，沿用 005 的 HBG 运行库（默认 `build/lib/a6/onboard`）。每个随仓压缩包包含本用例的 A6 callable、计划、参考输出和 Host runner。首次各跑一次 L0，保留每个用例自己的 `rank0/console.log` 和 `result.json`。

```bash
git fetch origin a6-migrate-case
git switch --detach FETCH_HEAD
source /usr/local/Ascend/cann-9.3.0/set_env.sh
suite=tests/fdwic/a6_dsv41_scheduler
phase=$suite/results/006-main-case-coverage
work=$(mktemp -d)
case_name=c1a_reuse
tar -xJf "$phase/a6/$case_name.tar.xz" -C "$work"
python3 -I "$suite/run.py" --build-dir "$work/$case_name" \
  --device "${TASK_DEVICE:?请设置已分配的 A6 单卡编号}" --output "$work/$case_name-L0"
```

其余包将 `case_name` 改为表中的名称，在同一终端重复解压和运行两行。需要 L2 原始采集时，改传 `--level 2 --output "$work/$case_name-L2"`。如果观测到超时，用该轮日志与任务完成计数定位；只有核内位置或设备错误也吻合时，才能判断是否复现了 005 的某个故障。

从源码重新组包可运行以下命令，默认读取随仓快照。每次选择空的构建目录。

```bash
python -I "$suite/prepare.py" build --stage 006 --platform a6 --case "$case_name" \
  --pto-isa build/pto-isa --build-dir "build/006-a6-$case_name"
```

# 002　单卡 96 核访问同一个 32 位地址

96 核同址读的第 96 名均值（GM 普通读／GM atomic／CntNotify）为 A5 **1.660／16.387／1.199 µs**，A6 **0.503／0.990／1.225 µs**。[阶段索引](../../doc/a6-optimization.zh-CN.md) · [用例源码](../../probes/same_address/)

## 测的六组操作

| 路径                | 32 位读                        | 32 位写，随后执行 DSB_DDR |
| ------------------- | ------------------------------ | ------------------------- |
| GM ld/st_dev        | `ld_dev(GM)`                 | `st_dev(1, GM)`         |
| GM atomic           | `atomicAdd(GM, 0)`，取返回值 | `atomicExch(GM, 1)`     |
| CntNotify ld/st_dev | `ld_dev(SET/read)`           | `st_dev(1, SET/read)`   |

每一组中，所有核访问同一个地址。GM 两种路径复用同一分配。CntNotify 地址由 CANN 分配并通过 `rtGetDevResAddress` 取得。这个用例比较 SET/read；生产 HBG 还会用 ADD 命令递增计数。A6 合并版的生产 HBG 使用 GM 完成计数，其中整轮计数宽度为 64 位。这六组 32 位数据可用于比较访问方式，整网收益另用 SWA L0 测量。[HBG 读写实现](../../../../../src/a5/runtime/host_build_graph/runtime/scheduler/scheduler_memory.h) · [CntNotify 资源映射](../../../../../src/a5/platform/onboard/host/scheduler_done_notifications.cpp) · [A6 的 GM 路径](../../doc/a6-migration.zh-CN.md#16-合入主线双槽调度)

每组预热 1 轮、正式 192 轮。硬件 `SYNCALL<Mix>()` 对齐起跑，每核只访问一次，使用 SYS_CNT 记开始和结束。读操作先消费返回值再记结束，写操作先执行 `dsb(DSB_DDR)` 再记结束。第二次同步、读回校验和记录写回均在计时区间外。[计时核](../../probes/same_address/kernel.cpp)

## A5 实测

Ascend950DT_9581，设备 2，32C＋64V，2026-11-19，任务 `task_20261119_171246_186161116119`。每个场景有 18,432 条正式记录，六组均通过槽位、读值和最终写值校验。原子交换每轮还检查恰有一个核读到旧值 0。六组的平均起跑偏差均约 0.041 µs。构建基于 Simpler `9764aeb37` 和 PTO-ISA `6065c782e`，测试用例归档于 `061950f72`。

| 场景    | 路径         | 第 1 名 µs | 第 48 名 µs | 第 96 名 µs | 第 96 名 P10–P90 µs | 平均相邻间距 ns | 原图第 96 名 µs |
| ------- | ------------ | ----------: | -----------: | -----------: | --------------------: | --------------: | ---------------: |
| 读      | GM ld/st_dev |       0.073 |        0.866 |        1.660 |          1.625–1.703 |            16.7 |            1.530 |
| 读      | GM atomic    |       0.207 |        8.236 |       16.387 |        16.277–16.581 |           170.3 |           16.946 |
| 读      | CntNotify    |       0.133 |        0.616 |        1.199 |          1.181–1.218 |            11.2 |            1.203 |
| 写＋DSB | GM ld/st_dev |       0.064 |        4.516 |        8.931 |          8.852–8.987 |            93.3 |            9.231 |
| 写＋DSB | GM atomic    |       0.208 |        8.238 |       16.385 |        16.278–16.531 |           170.3 |           16.956 |
| 写＋DSB | CntNotify    |       0.207 |        0.735 |        1.447 |          1.431–1.464 |            13.1 |            1.463 |

两次 A5 测量里，读和写的最后完成名次均为 CntNotify 最早、GM atomic 最晚。原图未附实现，本次选择的 atomic 和 SET 操作以上表为准。每轮取最早开始 tick 为零点，按结束 tick 从小到大排序，再跨轮对同一名次求均值、P10 和 P90。平均相邻间距为每轮 `(第 96 名 − 第 1 名) / 95` 的均值。完整 96 个名次及两份可重算的原始记录已归档。[逐名次 JSON](a5-ranks.json) · [GM 原始 CSV](a5-gm.csv.xz) · [CntNotify 原始 CSV](a5-cnt-notify.csv.xz)

## A6 同址读写

| 场景    | 路径               | 第 1 名 µs | 第 48 名 µs | 第 96 名 µs | 第 96 名 P10–P90 µs | 平均相邻间距 ns | 平均起跑偏差 µs | 第 96 名 A6 − A5 µs |
| ------- | ------------------ | ----------: | -----------: | -----------: | --------------------: | --------------: | ---------------: | --------------------: |
| 读      | GM ld/st_dev       |       0.111 |        0.186 |        0.503 |          0.498–0.509 |           4.125 |           0.0458 |               −1.157 |
| 读      | GM atomic          |       0.224 |        0.723 |        0.990 |          0.974–1.008 |           8.069 |           0.0458 |              −15.397 |
| 读      | CntNotify SET/read |       0.159 |        0.697 |        1.225 |          1.216–1.234 |          11.223 |           0.0458 |                +0.026 |
| 写＋DSB | GM ld/st_dev       |       0.110 |        1.124 |        1.786 |          1.416–2.238 |          17.640 |           0.0457 |               −7.145 |
| 写＋DSB | GM atomic          |       0.236 |        0.727 |        0.993 |          0.977–1.006 |           7.965 |           0.0458 |              −15.392 |
| 写＋DSB | CntNotify SET      |       0.223 |        0.772 |        1.328 |          1.279–1.371 |          11.625 |           0.0458 |               −0.119 |

## A6 完成计数

初值 0，96 个核各加 1，期望终值 96。

| 每核操作                  | 第 1 名 µs | 第 48 名 µs | 第 96 名 µs | 第 96 名 P10–P90 µs | 终值校验                                        | AICPU 读回 |
| ------------------------- | ----------: | -----------: | -----------: | --------------------: | ----------------------------------------------- | ---------- |
| GM 64 位 `atomicAdd(1)` |       0.251 |        0.774 |        1.051 |          1.035–1.072 | 193／193 通过，AICore 0 读回 96                 | 未测       |
| CntNotify 32 位 ADD       |          — |           — |           — |                    — | 未通过，向 `SET + 0x08` 写入 96 次 1 后读回 0 | 未测       |

| CntNotify 入口                                      | 映射返回码 | 读写结果                              |
| --------------------------------------------------- | ---------: | ------------------------------------- |
| SET/read · `RT_RES_TYPE_STARS_CNT_NOTIFY_RECORD` |          0 | 资源创建、映射成功；SET 写 1 后读回 1 |
| ADD · `RT_RES_TYPE_STARS_CNT_NOTIFY_ADD`         |     507899 | `rtGetDevResAddress` 映射失败       |
| `SET + 0x08`                                      |         — | 使用 SET 映射，期望 96，读回 0        |

### HBG 如何上报整轮完成数

在本阶段使用的双槽 HBG 中，Host 在设备启动前选定整轮计数后端，AICore 和 AICPU 使用同一份计数。

| 启动前的选择                  | 每完成一个逻辑任务，AICore 做什么                 | AICPU 从哪里读进度                   |
| ----------------------------- | ------------------------------------------------- | ------------------------------------ |
| 取得可用的 CntNotify ADD 映射 | 向 STARS 通知计数器发一次加一命令                 | 从同一计数器的 SET/read 地址读当前值 |
| 使用 GM（本次 A6）            | 对 GM 中的 64 位整轮计数执行一次 `atomicAdd(1)` | 直接读这个 GM 变量                   |

整个运行期间读写双方沿用选定的后端，无需查询另一份计数或在 STARS 与 GM 之间拷贝。这里统计的是整张图已完成的逻辑任务数；后继能否执行，另查它自己的前驱完成状态。[Host 选择后端](../../../../../src/a5/runtime/host_build_graph/host/runtime_maker.cpp) · [A6 映射策略](../../../../../src/a5/platform/onboard/host/device_runner.cpp)

**A6 选 GM 的直接原因是 CntNotify ADD 入口未验证通过。** 同址微测给出了保留 GM 的性能依据。96 核各执行一次 32 位 `atomicAdd(0)`，全部完成的平均用时从 A5 的 16.387 µs 降至 A6 的 0.990 µs，A6 用时约为 A5 的 1/16.6。A6 的 64 位 `atomicAdd(1)` 同口径为 1.051 µs。这说明 A5 上希望通过 CntNotify 避开的同址 GM 原子竞争，在 A6 上的实测代价已小很多。现有数据缺少 A5 STARS ADD(1) 的同口径计时，也缺少 A6 同卡切换后端的 SWA 对照，因此还不能给出这两种加一方式的快慢或切换后端的整层收益。

## A6 单卡 SWA L0

逻辑设备 0，预热 1 轮、正式 10 轮，耗时取正式轮算术均值。

| 运行配置                                     | 提交        | 完成计数后端      | 输出校验    | AICore 窗口 µs | Device wall µs |
| -------------------------------------------- | ----------- | ----------------- | ----------- | --------------: | --------------: |
| [00 迁移基线](../00-baseline/README.zh-CN.md) | `9161810` | —                | 30／30 通过 |         370.307 |         463.159 |
| 2026-11-20 · HBG                            | `0d76a7d` | `GM-FAA`        | 30／30 通过 |         328.139 |         414.771 |
| CntNotify 对照                               | —          | `CntNotify-INC` | 未运行      |              — |              — |

## A6 六组同址读写复测命令

在仓库根目录加载对应的 CANN 环境，准备与仓库 pin 一致的 PTO-ISA，仅编译这个小用例。两端的构建目标分别是 A5 的 `dav-c310` 和 A6 的 `dav-920r1`。

```bash
p=tests/fdwic/a6_dsv41_scheduler/probes/same_address
mkdir -p build
out=$(mktemp -d "$PWD/build/002-a6-XXXXXXXX")
bash "$p/build.sh" a6 build/pto-isa "$out/bin"
```

在**已独占的一张 A6 卡**上运行，`device` 取分配的逻辑 ID。A6 以 48 组 1C1V 发起 96 个参与者，剩余 6 对核不参与这个对照。A5 复跑则用上一步的 `a5` 构建，下面两次启动的 block 数都换为 32，统计参数换成 `--blocks 32 --vectors 64`。

```bash
set -e
set -o pipefail
device=${TASK_DEVICE:-0}
"$out/bin/probe" "$device" 48 gm "$out/gm.csv" 2>&1 | tee "$out/gm.log"
captures=("$out/gm.csv")
if "$out/bin/probe" "$device" 48 cnt_notify "$out/cnt_notify.csv" 2>&1 | tee "$out/cnt_notify.log"; then
    captures+=("$out/cnt_notify.csv")
fi
python3 "$p/ranks.py" "${captures[@]}" --blocks 48 --vectors 48 \
    --clock-hz 1000000000 --output "$out/ranks.json"
```

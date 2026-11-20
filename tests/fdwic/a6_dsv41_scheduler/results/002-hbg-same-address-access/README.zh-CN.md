# 002　单卡 96 核访问同一个 32 位地址

96 核同址读的第 96 名均值（GM 普通读／GM atomic／CntNotify）为 A5 **1.660／16.387／1.199 µs**，A6 **0.503／0.990／1.225 µs**。[阶段索引](../../doc/a6-optimization.zh-CN.md) · [用例源码](../../probes/same_address/)

## 测的六组操作

| 路径 | 32 位读 | 32 位写，随后执行 DSB_DDR |
| ---- | ------- | ------------------------- |
| GM ld/st_dev | `ld_dev(GM)` | `st_dev(1, GM)` |
| GM atomic | `atomicAdd(GM, 0)`，取返回值 | `atomicExch(GM, 1)` |
| CntNotify ld/st_dev | `ld_dev(SET/read)` | `st_dev(1, SET/read)` |

每一组中，所有核访问同一个地址。GM 两种路径复用同一分配。CntNotify 地址由 CANN 分配并通过 `rtGetDevResAddress` 取得。这个用例比较 SET/read；生产 HBG 还会用 ADD 命令递增计数。A6 合并版的生产 HBG 使用 GM 完成计数，其中整轮计数宽度为 64 位。这六组 32 位数据可用于比较访问方式，整网收益另用 SWA L0 测量。[HBG 读写实现](../../../../../src/a5/runtime/host_build_graph/runtime/scheduler/scheduler_memory.h) · [CntNotify 资源映射](../../../../../src/a5/platform/onboard/host/scheduler_done_notifications.cpp) · [A6 的 GM 路径](../../doc/a6-migration.zh-CN.md#16-合入主线双槽调度)

每组预热 1 轮、正式 192 轮。硬件 `SYNCALL<Mix>()` 对齐起跑，每核只访问一次，使用 SYS_CNT 记开始和结束。读操作先消费返回值再记结束，写操作先执行 `dsb(DSB_DDR)` 再记结束。第二次同步、读回校验和记录写回均在计时区间外。[计时核](../../probes/same_address/kernel.cpp)

## A5 实测

Ascend950DT_9581，设备 2，32C＋64V，2026-11-19，任务 `task_20261119_171246_186161116119`。每个场景有 18,432 条正式记录，六组均通过槽位、读值和最终写值校验。原子交换每轮还检查恰有一个核读到旧值 0。六组的平均起跑偏差均约 0.041 µs。构建基于 Simpler `9764aeb37` 和 PTO-ISA `6065c782e`，测试用例归档于 `061950f72`。

| 场景 | 路径 | 第 1 名 µs | 第 48 名 µs | 第 96 名 µs | 第 96 名 P10–P90 µs | 平均相邻间距 ns | 原图第 96 名 µs |
| ---- | ---- | ---------: | ----------: | ----------: | ------------------: | --------------: | --------------: |
| 读 | GM ld/st_dev | 0.073 | 0.866 | 1.660 | 1.625–1.703 | 16.7 | 1.530 |
| 读 | GM atomic | 0.207 | 8.236 | 16.387 | 16.277–16.581 | 170.3 | 16.946 |
| 读 | CntNotify | 0.133 | 0.616 | 1.199 | 1.181–1.218 | 11.2 | 1.203 |
| 写＋DSB | GM ld/st_dev | 0.064 | 4.516 | 8.931 | 8.852–8.987 | 93.3 | 9.231 |
| 写＋DSB | GM atomic | 0.208 | 8.238 | 16.385 | 16.278–16.531 | 170.3 | 16.956 |
| 写＋DSB | CntNotify | 0.207 | 0.735 | 1.447 | 1.431–1.464 | 13.1 | 1.463 |

两次 A5 测量里，读和写的最后完成名次均为 CntNotify 最早、GM atomic 最晚。原图未附实现，本次选择的 atomic 和 SET 操作以上表为准。每轮取最早开始 tick 为零点，按结束 tick 从小到大排序，再跨轮对同一名次求均值、P10 和 P90。平均相邻间距为每轮 `(第 96 名 − 第 1 名) / 95` 的均值。完整 96 个名次及两份可重算的原始记录已归档。[逐名次 JSON](a5-ranks.json) · [GM 原始 CSV](a5-gm.csv.xz) · [CntNotify 原始 CSV](a5-cnt-notify.csv.xz)

## A6 同址读写

| 场景 | 路径 | 第 1 名 µs | 第 48 名 µs | 第 96 名 µs | 第 96 名 P10–P90 µs | 平均相邻间距 ns | 平均起跑偏差 µs | 第 96 名 A6 − A5 µs |
| ---- | ---- | ---------: | ----------: | ----------: | ------------------: | --------------: | --------------: | ------------------: |
| 读 | GM ld/st_dev | 0.111 | 0.186 | 0.503 | 0.498–0.509 | 4.125 | 0.0458 | −1.157 |
| 读 | GM atomic | 0.224 | 0.723 | 0.990 | 0.974–1.008 | 8.069 | 0.0458 | −15.397 |
| 读 | CntNotify SET/read | 0.159 | 0.697 | 1.225 | 1.216–1.234 | 11.223 | 0.0458 | +0.026 |
| 写＋DSB | GM ld/st_dev | 0.110 | 1.124 | 1.786 | 1.416–2.238 | 17.640 | 0.0457 | −7.145 |
| 写＋DSB | GM atomic | 0.236 | 0.727 | 0.993 | 0.977–1.006 | 7.965 | 0.0458 | −15.392 |
| 写＋DSB | CntNotify SET | 0.223 | 0.772 | 1.328 | 1.279–1.371 | 11.625 | 0.0458 | −0.119 |

## A6 完成计数

初值 0，96 个核各加 1，期望终值 96。

| 每核操作 | 第 1 名 µs | 第 48 名 µs | 第 96 名 µs | 第 96 名 P10–P90 µs | 终值校验 | AICPU 读回 |
| -------- | ---------: | ----------: | ----------: | ------------------: | -------- | ---------- |
| GM 64 位 `atomicAdd(1)` | 0.251 | 0.774 | 1.051 | 1.035–1.072 | 193／193 通过，AICore 0 读回 96 | 未测 |
| CntNotify 32 位 ADD | — | — | — | — | 未通过，向 `SET + 0x08` 写入 96 次 1 后读回 0 | 未测 |

| CntNotify 入口 | 映射返回码 | 读写结果 |
| -------------- | ---------: | -------- |
| SET/read · `RT_RES_TYPE_STARS_CNT_NOTIFY_RECORD` | 0 | 资源创建、映射成功；SET 写 1 后读回 1 |
| ADD · `RT_RES_TYPE_STARS_CNT_NOTIFY_ADD` | 507899 | `rtGetDevResAddress` 映射失败 |
| `SET + 0x08` | — | 使用 SET 映射，期望 96，读回 0 |

## A6 单卡 SWA L0

逻辑设备 0，预热 1 轮、正式 10 轮，耗时取正式轮算术均值。

| 运行配置 | 提交 | 完成计数后端 | 输出校验 | AICore 窗口 µs | Device wall µs |
| -------- | ---- | ------------ | -------- | -------------: | -------------: |
| [00 迁移基线](../00-baseline/README.zh-CN.md) | `9161810` | — | 30／30 通过 | 370.307 | 463.159 |
| 2026-11-20 · HBG | `0d76a7d` | `GM-FAA` | 30／30 通过 | 328.139 | 414.771 |
| CntNotify 对照 | — | `CntNotify-INC` | 未运行 | — | — |

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

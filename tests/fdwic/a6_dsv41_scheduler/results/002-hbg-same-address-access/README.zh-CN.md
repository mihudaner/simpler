# 002　单卡 96 核访问同一个 32 位地址

**A5 上，96 个核各读一次，全部完成平均用时为 GM 普通读 1.660 µs、GM atomic 读 16.387 µs、CntNotify 读 1.199 µs。** A6 用同一用例测 48C＋48V，可以直接比较第 1、48、96 名。两端并发数相同，C/V 比例不同。该实验测硬件访问，不需要运行整层 SWA。[阶段索引](../../doc/a6-optimization.zh-CN.md) · [用例源码](../../probes/same_address/)

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

## A6 怎么跑

在仓库根目录加载对应的 CANN 环境，准备与仓库 pin 一致的 PTO-ISA，仅编译这个小用例。两端的构建目标分别是 A5 的 `dav-c310` 和 A6 的 `dav-920r1`。下面的 A6 目标已在本地交叉编译。

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

单独启动 CntNotify 进程，只申请一个资源，并访问 API 返回的 32 位 SET/read 基址。记录创建、取 ID、映射及读写校验中首个失败步骤和返回码。该组失败时仍可汇总四组 GM 数据，CntNotify 的计时格留空。计时采用已有 A6 SYS_CNT 约 1 GHz 的实测结论。[计时依据](../../doc/a6-migration.zh-CN.md#10-设备计时)

## A6 回填区

只需回传本节 Markdown。前三个名次列均填 192 轮均值；第 96 名的 P10、P90 取自 `ranks.json` 各场景的最后一项。原始 CSV 留在本地。

| 场景 | 路径 | 第 1 名 µs | 第 48 名 µs | 第 96 名 µs | 第 96 名 P10–P90 µs | 平均相邻间距 ns | 平均起跑偏差 µs |
| ---- | ---- | ---------: | ----------: | ----------: | ------------------: | --------------: | --------------: |
| 读 | GM ld/st_dev | | | | | | |
| 读 | GM atomic | | | | | | |
| 读 | CntNotify | | | | | | |
| 写＋DSB | GM ld/st_dev | | | | | | |
| 写＋DSB | GM atomic | | | | | | |
| 写＋DSB | CntNotify | | | | | | |

| 需要回答 | A6 实测回答 |
| -------- | ----------- |
| 提交、芯片、CANN 版本、逻辑设备、日期／任务号、SYS_CNT 频率？ | |
| 日志中的可用 C/V 数和实际启动 C/V 数？各场景是否通过 193 轮 × 96 核校验（含预热）？ | |
| CntNotify 是否能申请、映射、读回 1、写入并读回 1？失败时贴首条错误和返回码。 | |
| 相比 A5，哪条路径的第 96 名变化最大？平均相邻间距和起跑偏差分别是多少？ | |

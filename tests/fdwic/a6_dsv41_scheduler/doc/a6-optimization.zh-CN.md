# 单卡 SWA 性能优化阶段索引

后续优化以迁移完成时 A6 的 **370.307 µs** 为起点。主指标取生产 HBG 的 L0 首个计算核开始到末个计算核结束，单卡预热 1 轮、正式 10 轮取均值。A5 提供跨代对照。[复测方法](a6-environment.zh-CN.md) · [迁移记录](a6-migration.zh-CN.md)

| 阶段 | 改动与对照 | A6 L0 窗口 | A6 Device wall（L0） | 报告与数据 |
| ---- | ---------- | ---------: | -------------------: | ---------- |
| [00 优化前基线](../results/00-baseline/) | A6 已完成 1C1V 迁移，A5 保留 1C2V。A5 对照窗口为 269.286 µs | 370.307 µs | 463.159 µs | [阶段报告](../results/00-baseline/README.zh-CN.md) · [指标 JSON](../results/00-baseline/metrics.json) · [A5 L3 泳道](../results/00-baseline/swa-a5-hbg-L3-detail.json.xz) |
| [001 合入主线 HBG](../results/001-hbg-main-merge-swa/) | 同一张 A5 上，纯主线 219.287 µs，合并版 218.050 µs。A6 使用 GM 完成计数，待单卡回填 | | | [阶段报告](../results/001-hbg-main-merge-swa/README.zh-CN.md) · [指标 JSON](../results/001-hbg-main-merge-swa/metrics.json) · [A5 L3 泳道](../results/001-hbg-main-merge-swa/swa-a5-hbg-L3-detail.json.xz) |
| [002 同址访问](../results/002-hbg-same-address-access/README.zh-CN.md) | 单卡 96 核比较 GM、GM atomic 和 CntNotify。A5 已测，A6 待回填 | | | [测试步骤与回填表](../results/002-hbg-same-address-access/README.zh-CN.md#a6-回填区) · [A5 逐名次数据](../results/002-hbg-same-address-access/a5-ranks.json) |

**待测的分片改动**是把输出量化（回放 t17／源码 t25）的工作从 64 个 V block 重新分给 54 个。基线下至少 10 个 block 要等 V 核空出。是否值得改，取决于每个 block 多做的工作和省下的等待，可用同卡 L0 及 30 个缓冲区的输出校验判定。[基线分片与空隙统计](../results/00-baseline/README.zh-CN.md#54-个-v-的影响有多大)

## 追加一个阶段

在 `results/` 下按顺序新建目录，例如 `003-<改动名>/`。该目录的 `README.zh-CN.md` 记录改了什么、对照哪一阶段、实测差值和输出校验。`metrics.json` 保存同口径的汇总值。A6 原始泳道及含 A6 的重建图保存在阶段内的 `local-traces/`，仅供本地分析。完成实测后在上表追加一行，链接本阶段报告和指标 JSON。各阶段保留各自的提交号、采集等级与轮次，方便复核收益。

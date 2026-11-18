# A6 单卡 SWA 复跑任务

[用例索引](../README.zh-CN.md) · [已确认的接口与首跑定位](a6-migration.zh-CN.md#单卡-swa-首跑)

- [ ] **P0　使 1C1V 启动掩码真正编译为 3，复跑同一个 SWA。**
- [ ] **P0　让退出确认的读写双方使用同一寄存器，检查正常退出与输出。**

| 修改 | 同一次单卡 SWA 返回什么 |
| ---- | ----------------------- |
| 在 `scheduler_types.h` 用 C++ 常量表达式组合 `INIT \| AIV0_DONE \| (PLATFORM_CORES_PER_BLOCKDIM == 3 ? AIV1_DONE : 0)`（沿用源码完整常量名）。A6 编译用 `static_assert` 验证 DONE 为 3，A5 保持 7。重建并确认 runner 加载新 resident 产物。 | 记录构建标识、是否观察到 `bootstrap_complete=1`、是否放行及启动计算。仍停在 bootstrap 时，附 54 个组就绪字中 0、1、3、其他值各有几组，以及首错 site。 |
| 在 `acknowledge_aicore_cond_nonce_and_wait` 通过平台写接口回报本轮退出值，使 A6 写 IPC4，与 CP1 的读地址配对。保留 CP1 验证本轮回执、关窗并放行核返回的顺序。 | 正常退出情况、30 个可写 buffer 的校验结果。若仍失败，附最早错误及所在阶段。 |

## 本轮回答区

- 构建标识、组内就绪与启动结果：
- 退出与输出校验：

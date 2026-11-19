/*
 * Copyright (c) PyPTO Contributors.
 * This program is free software, you can redistribute it and/or modify it under the terms and conditions of
 * CANN Open Software License Agreement Version 2.0 (the "License").
 * Please refer to the License for details. You may not use this file except in compliance with the License.
 * THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
 * INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
 * See LICENSE in the root of the software repository for the full text of the License.
 * -----------------------------------------------------------------------------------------------------------
 */

#include "inner_kernel.h"

#include <gtest/gtest.h>

#include <array>
#include "hbg_scheduler_test_support.h"
#include "aicore/resident_scheduler_impl.h"

volatile uint8_t *sim_get_reg_base() {
    alignas(64) static std::array<uint8_t, SIM_REG_TOTAL_SIZE> regs{};
    return regs.data();
}

TEST(HbgPairedBootstrap, LastCubeReleasesFiftyFourSingleVectorClusters) {
    constexpr uint32_t pairs = 54;
    constexpr uint32_t workers = 2 * pairs;
    scheduler_test::FixtureStorage storage(1, workers, 1, SchedulerSpmdRequirements{workers, pairs, 0, 0});
    scheduler_test::BasicGraphBuffer<1> graph(1);
    graph.executable(0, 0);
    auto *base = storage.scheduler_state->base();
    auto *run = storage.run_control;
    storage.prepare_catalog();
    ASSERT_TRUE(scheduler_init_spmd_task_records(base, storage.layout, 59));
    ASSERT_TRUE(storage.prepare_calls(graph.graph()));
    run->expected_task_count = 1;
    run->scheduler_timeout_cycles = PLATFORM_PROF_SYS_CNT_FREQ;
    auto *gates = scheduler_state_at<SchedulerBootstrapCluster>(base, storage.layout.bootstrap_clusters_offset);

    // With no MIX task the host has already published INIT for every pair.
    for (uint32_t pair = 0; pair < pairs; ++pair) {
        for (uint32_t worker : {pair + pairs, pair}) {
            auto &context = storage.contexts[worker];
            context.cluster_index = pair;
            context.core_type = static_cast<int32_t>(worker == pair ? CoreType::AIC : CoreType::AIV);
            context.type_rank = pair;
            context.cluster_worker_ids[0] = pair;
            context.cluster_worker_ids[1] = pair + pairs;
            storage.test_graphs[worker] = graph.graph();
            auto *local = storage.local_context(&context);
            SchedulerWorkerStats stats{};
            ASSERT_TRUE((bootstrap_ready_graph<false, false>(graph.graph(), base, local, run, workers, &stats, 0)));
            ASSERT_EQ(gates[pair].state, 3u);
            const uint64_t arrived = 2 * (pair + (worker == pair ? 1u : 0u));
            EXPECT_EQ(run->bootstrap_arrived_count, arrived);
            EXPECT_EQ(run->bootstrap_complete, arrived == workers);
        }
    }
}

TEST(HbgPairedProtocol, SyncMixRecordsBothPhysicalAcksAndAnEmptyThirdSlot) {
    constexpr LaneMask mask{true, true, false};
    scheduler_test::FixtureStorage storage(1, 4, 4, SchedulerSpmdRequirements{4, 2, 1, 1, 1}, true);
    scheduler_test::BasicGraphBuffer<1> graph(1);
    graph.mixed(0, mask);
    auto &meta = storage.metadata[0];
    meta.active_mask = mask;
    meta.kernel_ids[1] = 1;
    meta.logical_block_num = 2;
    meta.flags = SCHEDULER_TASK_EXECUTABLE | SCHEDULER_TASK_MIX | SCHEDULER_TASK_SYNC_START | SCHEDULER_TASK_SPMD;
    auto *base = storage.scheduler_state->base();
    ASSERT_TRUE(scheduler_init_spmd_task_records(base, storage.layout, 1));

    SchedulerAdmissionLocalState admission{};
    admission.epoch = 1;
    admission.current_task_ref = 0;
    admission.current_block_num = 2;
    admission.current_flags = meta.flags;
    admission.current_active_mask = admission.current_resource_mask = mask;
    admission.gm_mix.group_seq = 7;
    admission.gm_mix.mailbox_offset = storage.layout.group_mailboxes_offset;
    auto *mailbox = scheduler_state_at<SchedulerGroupMailbox>(base, admission.gm_mix.mailbox_offset);
    mailbox->descriptor = {};
    mailbox->descriptor.run_epoch = 1;
    mailbox->descriptor.task_ref = 0;
    mailbox->descriptor.group_seq = 7;
    SchedulerClusterSignal signal{};
    auto *block = scheduler_state_at<SchedulerProtocolBlockTrace>(base, storage.layout.protocol.blocks_offset);
    auto *workers = scheduler_state_at<SchedulerProtocolWorkerTrace>(base, storage.layout.protocol.workers_offset);
    for (int lane = 0; lane < PLATFORM_CORES_PER_BLOCKDIM; ++lane) {
        mailbox->lanes[lane].arrived_seq = 7;
        mailbox->lanes[lane].released_seq = 7;
    }
    for (unsigned lane : {0u, 1u}) {
        auto &context = storage.contexts[lane];
        context.cluster_worker_ids[0] = 0;
        context.cluster_worker_ids[1] = 1;
        auto *local = storage.local_context(&context);
        ASSERT_TRUE(scheduler_protocol_bind(base, local));
        local->admission = &admission;
        local->cluster_signal = &signal;
        if (lane == 0) scheduler_protocol_block_claim(base, local, 0, 1, 2);
        scheduler_protocol_group_descriptor(base, local, &mailbox->descriptor);
        ASSERT_EQ(workers[lane].error_flags, 0u);
        bool all = false;
        ASSERT_TRUE(scheduler_gm_mix_arrivals_ready(graph.graph(), base, local, storage.run_control, &all));
        ASSERT_TRUE(all);
        EXPECT_NE(block->lanes[lane].arrivals_observed.sequence, 0u);
        if (lane == 0) {
            ASSERT_TRUE(scheduler_gm_mix_check_acks(graph.graph(), base, local, storage.run_control, true, &all));
            ASSERT_TRUE(all);
            EXPECT_NE(block->owner.releases_observed.sequence, 0u);
        }
        for (unsigned slot = 0; slot < SUBTASK_SLOT_COUNT; ++slot) {
            EXPECT_EQ(block->lanes[lane].arrived_seq[slot], slot < 2 ? 7u : 0u);
            EXPECT_EQ(block->owner.released_seq[slot], slot < 2 ? 7u : 0u);
        }
        EXPECT_EQ(workers[lane].error_flags, 0u);
    }
}

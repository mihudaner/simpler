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

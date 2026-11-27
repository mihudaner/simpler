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

#include "runtime_types.h"
#undef SPIN_WAIT_HINT
#include "inner_kernel.h"

uint64_t get_aicore_report_epoch();
#include "lane_loop.h"
#include "host/calendar_image.h"

#include <gtest/gtest.h>

#include <array>
#include <atomic>
#include <thread>

namespace {
using namespace simpler::percounter;

alignas(64) std::array<uint8_t, PLATFORM_SSBUF_SIZE> ssbuf;
thread_local void *invocation_context = nullptr;

struct Results {
    int64_t input{11};
    std::atomic<int64_t> ordinary{0};
    std::atomic<int64_t> cube{0};
    std::atomic<int64_t> vector{0};
    std::atomic<int64_t> output{0};
    std::array<std::atomic<int>, 4> calls{};
};

template <int stage>
void kernel(int64_t *args) {
    auto &data = *reinterpret_cast<Results *>(args[0]);
    ++data.calls[stage];
    if (get_block_idx(args) != 0 || get_block_num(args) != 1 || get_sub_block_id(args) != 0) return;
    if constexpr (stage == 0) data.ordinary = data.input + 1;
    if constexpr (stage == 1) data.cube = data.ordinary.load() * 2;
    if constexpr (stage == 2) data.vector = data.ordinary.load() * 3;
    if constexpr (stage == 3) data.output = data.cube.load() + data.vector.load();
}

TEST(A6CalendarExecution, RunsOrdinaryMixAndDependentOrdinaryOnOneCubeVectorPair) {
    const std::array<int32_t, 2> dependencies{0, 1};
    std::vector<TaskInput> tasks(3);
    tasks[0].active_mask = 1;
    tasks[1].active_mask = 3;
    tasks[1].is_mix = true;
    tasks[1].subtask_count = 2;
    tasks[1].fanin_ids = &dependencies[0];
    tasks[1].fanin_count = 1;
    tasks[2].active_mask = 2;
    tasks[2].core_type_index = 1;
    tasks[2].fanin_ids = &dependencies[1];
    tasks[2].fanin_count = 1;

    std::vector<CalendarPhase> phases;
    ASSERT_TRUE(plan_calendar_phases(tasks, {}, &phases));
    auto plan = std::make_shared<CalendarPlan>();
    ASSERT_TRUE(build_static_calendar(phases.front().tasks, 1, {}, plan.get()));
    RangeCalendarImage image;
    ASSERT_TRUE(build_range_calendar({{&phases.front(), plan, false}}, {}, 3, 1, &image));
    PercounterLayout layout{};
    ASSERT_TRUE(plan_layout(3, 3, &layout, 1, {}, 4));

    struct alignas(128) Sector {
        std::array<uint8_t, 128> bytes{};
    };
    const auto total = layout.total_size + image.bytes.size();
    std::vector<Sector> region((total + sizeof(Sector) - 1) / sizeof(Sector));
    void *base = region.data();
    ASSERT_TRUE(build_tables(tasks, layout, base, {0, tasks.size()}, {}));
    auto *control = region_at<PercounterControl>(base, layout.control_offset);
    control->calendar_offset = layout.total_size - layout.control_offset;
    control->image_bytes = total;
    control->cluster_count = 1;
    control->aiv_per_cluster = 1;
    Results data;
    DispatchPayload args{};
    args.args[0] = reinterpret_cast<uint64_t>(&data);
    auto *counters = region_at<PercounterCounter>(base, layout.counters_offset);
    counters[0].function_addresses[0] = reinterpret_cast<uint64_t>(&kernel<0>);
    counters[1].function_addresses[0] = reinterpret_cast<uint64_t>(&kernel<1>);
    counters[1].function_addresses[1] = reinterpret_cast<uint64_t>(&kernel<2>);
    counters[2].function_addresses[1] = reinterpret_cast<uint64_t>(&kernel<3>);
    for (size_t i = 0; i < tasks.size(); ++i)
        counters[i].arguments_address = reinterpret_cast<uint64_t>(&args);
    const auto header = image.load<CalendarRangeHeader>(0);
    std::vector<Sector> notifications(header.notify_slots_count);
    std::vector<uint64_t> addresses;
    for (auto &word : notifications)
        addresses.push_back(reinterpret_cast<uint64_t>(word.bytes.data()));
    ASSERT_TRUE(bind_range_calendar(image, reinterpret_cast<uint64_t>(base), layout, base, addresses));
    std::memcpy(region_at<uint8_t>(base, layout.total_size), image.bytes.data(), image.bytes.size());
    simpler_sim_install_invocation_context_hooks(
        [](void *value) {
            invocation_context = value;
            return 0;
        },
        [] {
            return invocation_context;
        }
    );
    alignas(64) uint32_t lifecycle = 2;
    std::thread vector([&] {
        run_percounter_lane(control, 1, CoreType::AIV, &lifecycle);
    });
    run_percounter_lane(control, 0, CoreType::AIC, &lifecycle);
    vector.join();
    simpler_sim_install_invocation_context_hooks(nullptr, nullptr);
    EXPECT_EQ(control->lane_error, 0U);
    EXPECT_EQ(data.output.load(), 60);
    for (const auto &calls : data.calls)
        EXPECT_EQ(calls.load(), 1);
    const auto &sink = counters[2];
    ASSERT_NE(sink.completion_notify_address, 0U);
    EXPECT_EQ(sink.completion_notify_target, 4U);
    EXPECT_EQ(
        percounter_notify_query(*reinterpret_cast<volatile uint32_t *>(sink.completion_notify_address)),
        sink.completion_notify_target
    );
}
}  // namespace

volatile uint8_t *sim_get_reg_base() {
    static thread_local std::array<uint8_t, SIM_REG_TOTAL_SIZE> registers{};
    return registers.data();
}
uint32_t sim_get_physical_core_id() { return 0; }
uint64_t platform_ssbuf_hardware_base_address() { return reinterpret_cast<uint64_t>(ssbuf.data()); }
uint32_t get_aicore_profiling_flag() { return 0; }
ChipSwimlaneActiveHead *get_chip_swimlane_aicore_head() { return nullptr; }

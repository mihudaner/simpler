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
#include "runtime_types.h"

uint64_t get_aicore_report_epoch();
#include "lane_loop.h"
#include "calendar_image.h"

#include <array>
#include <thread>

#include <gtest/gtest.h>

namespace simpler::percounter {
namespace {
TEST(A6CalendarNotifications, BoundCommandsShareOneGmWordForCompletionAndDefer) {
    TaskInput input{};
    input.active_mask = 1;
    input.block_num = 2;
    std::vector<CalendarPhase> phases;
    ASSERT_TRUE(plan_calendar_phases({input}, {}, &phases));
    auto plan = std::make_shared<CalendarPlan>();
    ASSERT_TRUE(build_static_calendar(phases.front().tasks, 2, {}, plan.get()));
    RangeCalendarImage image;
    ASSERT_TRUE(build_range_calendar({{&phases.front(), plan, false}}, {}, 1, 2, &image));
    struct Tables {
        PercounterControl control{};
        PercounterCounter counter{};
    } tables;
    PercounterLayout layout{};
    layout.counters_offset = offsetof(Tables, counter);
    layout.task_count = 1;
    alignas(64) std::array<uint32_t, 16> slot{};
    slot.fill(0xdeadc0de);
    slot.front() = 0;
    const auto address = reinterpret_cast<uint64_t>(slot.data());
    ASSERT_TRUE(bind_range_calendar(image, 0, layout, &tables, {address}));
    ASSERT_EQ(tables.counter.completion_notify_address, address);
    ASSERT_FALSE(image.dispatches.empty());
    const auto cmd = image.load<CalendarDispatch>(image.dispatches.front().offset).done_add_cmd;
    // The GM counter has no hardware ADD or OR aliases at +8 and +16.
    ASSERT_EQ(cmd, address);
    std::thread producer([&] {
        for (int i = 0; i < 1000; ++i)
            percounter_calendar_add(cmd);
    });
    for (int i = 0; i < 1000; ++i)
        percounter_calendar_set_defer_bit(address, 1U << 24);
    producer.join();
    EXPECT_EQ(percounter_notify_query(slot.front()), (1U << 24) + 1000U);
    for (size_t i = 1; i < slot.size(); ++i)
        EXPECT_EQ(slot[i], 0xdeadc0deU);
}

TEST(A6CalendarNotifications, OnlyRejectedWorkerConsumesItsOwnExitRequestAcrossReplay) {
    PercounterControl control{};
    alignas(64) uint32_t signal = 1;
    control.rejected_exit[1] = signal;
    EXPECT_EQ(percounter_wait_for_admission(&control, 1, signal, signal), PercounterAdmission::Rejected);
    EXPECT_EQ(control.rejected_exit[1], 0U);
    EXPECT_EQ(percounter_wait_for_admission(&control, 0, signal, UINT32_MAX), PercounterAdmission::Retire);
    signal = 2;
    EXPECT_EQ(percounter_wait_for_admission(&control, 0, signal, 1), PercounterAdmission::Start);
}
}  // namespace
}  // namespace simpler::percounter

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

#include <gtest/gtest.h>

#include <algorithm>
#include <memory>
#include <vector>

#include "host/calendar_event_score.h"
#include "host/calendar_image.h"
#include "host/graph_template.h"

namespace simpler::percounter {
namespace {

TEST(A6CalendarTopology, PlacesTheEntireMixedCohortOnPairedCubeAndVectorWorkers) {
    constexpr uint32_t clusters = 54;
    TaskInput mix{};
    mix.active_mask = 3;
    mix.is_mix = true;
    mix.sync_start = true;
    mix.block_num = clusters;
    mix.subtask_count = 2;
    std::vector<CalendarPhase> phases;
    ASSERT_TRUE(plan_calendar_phases({mix}, {}, &phases));
    auto plan = std::make_shared<CalendarPlan>();
    const auto &tasks = phases.front().tasks;
    const std::vector<CalendarRowCost> costs(clusters * 2, {100, 0});
    ASSERT_TRUE(build_static_calendar(tasks, clusters, costs, plan.get()));
    uint64_t predicted = 0;
    ASSERT_TRUE(evaluate_calendar_events(tasks, clusters, *plan, costs, {}, &predicted));
    EXPECT_EQ(predicted, 100U);

    RangeCalendarImage image;
    ASSERT_TRUE(build_range_calendar({{&phases.front(), plan, false}}, {}, 1, clusters, &image));
    const auto header = image.load<CalendarRangeHeader>(0);
    ASSERT_EQ(header.worker_count, 2 * clusters);
    for (uint32_t worker = 0; worker < header.worker_count; ++worker) {
        const auto index = image.load<uint32_t>(header.worker_index_offset + worker * sizeof(uint32_t));
        const auto range = image.load<CalendarRange>(header.range_offset + index * sizeof(CalendarRange));
        ASSERT_EQ(range.row_count, 1U);
        const auto row = image.load<CalendarExecutionRow>(range.rows_offset);
        EXPECT_EQ(row.flags & CALENDAR_EXEC_ROLE_MASK, worker >= clusters ? 1 : 0);
        EXPECT_EQ(row.block_index, worker % clusters);
        const auto join = image.load<CalendarLocalJoin>(range.rows_offset + row.mix_delta);
        EXPECT_EQ(join.arrive[0], 1U);
        EXPECT_EQ(join.arrive[1], 1U);
        EXPECT_EQ(join.arrive[2], 0U);
    }
}

TEST(A6CalendarTopology, RejectsAbsentRolesAndOversizedVectorCohorts) {
    constexpr uint32_t clusters = 3;
    TaskInput vec{};
    vec.active_mask = 2;
    vec.core_type_index = 1;
    vec.sync_start = true;
    vec.block_num = clusters;
    CalendarPlan plan;
    ASSERT_TRUE(build_static_calendar({vec}, clusters, {}, &plan));
    EXPECT_TRUE(std::all_of(plan.waits.row_input_owners.begin(), plan.waits.row_input_owners.end(), [](uint32_t owner) {
        return owner == CALENDAR_NO_INPUT_OWNER;
    }));
    vec.block_num++;
    EXPECT_FALSE(build_static_calendar({vec}, clusters, {}, &plan));

    for (uint8_t mask : {4, 5, 6, 7}) {
        uint8_t type = 0;
        EXPECT_EQ(task_placement_from_active_mask(mask, &type), TaskPlacement::UNSUPPORTED);
        const BodyTaskShape body{mask, false, false, 1, __builtin_popcount(mask)};
        const int32_t fanins[] = {0, 0};
        HostGraphTemplate graph;
        EXPECT_EQ(
            build_graph_template(&body, 1, fanins, nullptr, 0, 2 * clusters, &graph).status, TemplateStatus::UNSUPPORTED
        );
    }
}

}  // namespace
}  // namespace simpler::percounter

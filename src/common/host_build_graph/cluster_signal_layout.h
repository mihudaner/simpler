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

#pragma once

#include <cstddef>
#include <cstdint>

// The coordinator owns publication; each active lane owns its acknowledgement.
// Preparation and formal resource arbitration use independent generations.
template <unsigned Lanes>
struct SchedulerClusterSignalLayout {
    volatile uint64_t run_epoch;
    volatile int64_t prepare_task_ref;
    volatile uint32_t prepare_block;
    volatile uint32_t prepare_mask;
    volatile uint32_t prepare_generation;
    volatile uint32_t prepared[Lanes];
    volatile uint32_t sync_frontier[Lanes];
    volatile uint32_t sync_hold[Lanes];
    volatile uint32_t staged_mask;
    volatile uint32_t armed_generation;
    volatile int64_t task_ref;
    volatile uint64_t anchor_state;
    volatile uint32_t sync_tail;
    volatile uint32_t block_idx;
    volatile uint32_t active_mask;
    volatile uint32_t arrived[Lanes];
    volatile uint32_t finished[Lanes];
    volatile uint64_t gm_arrival_seq;
};

template <unsigned Lanes>
struct SchedulerClusterSsbufRegion;

template <>
struct SchedulerClusterSsbufRegion<3> {
    static constexpr unsigned offset = 2048;
    static constexpr unsigned capacity = 3072;
};

template <>
struct SchedulerClusterSsbufRegion<2> {
    // dav_9201 KFC clears a 32-bit field at 1744, beyond its descriptor.
    static constexpr unsigned offset = 1792;
    static constexpr unsigned capacity = 2048;
    static_assert(offset >= 1748 && offset % 64 == 0);
};

static_assert(
    sizeof(SchedulerClusterSignalLayout<3>) == 136 && offsetof(SchedulerClusterSignalLayout<3>, anchor_state) == 80
);
static_assert(
    sizeof(SchedulerClusterSignalLayout<2>) == 120 && offsetof(SchedulerClusterSignalLayout<2>, anchor_state) == 72
);

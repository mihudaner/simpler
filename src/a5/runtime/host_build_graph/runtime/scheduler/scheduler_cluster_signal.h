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

#include <cstdint>
#include <cstddef>
#include <type_traits>

#include "host_build_graph/cluster_signal_layout.h"
#include "scheduler_scalar_record.h"

#if defined(__CCE_AICORE__)
#define SCHEDULER_CLUSTER_SSBUF __ssbuf__
#else
#define SCHEDULER_CLUSTER_SSBUF
#endif

using SchedulerClusterRegion = SchedulerClusterSsbufRegion<PLATFORM_CORES_PER_BLOCKDIM>;
using SchedulerClusterSignal = SchedulerClusterSignalLayout<PLATFORM_CORES_PER_BLOCKDIM>;
static_assert(SchedulerClusterRegion::capacity == PLATFORM_SSBUF_SIZE);
static_assert(SchedulerClusterRegion::offset + sizeof(SchedulerClusterSignal) <= PLATFORM_SSBUF_SIZE);
static_assert(alignof(SchedulerClusterSignal) <= 8);
static_assert(std::is_standard_layout_v<SchedulerClusterSignal>);

inline __aicore__ SCHEDULER_CLUSTER_SSBUF SchedulerClusterSignal *scheduler_cluster_signal_at(uint64_t hardware_base) {
    return reinterpret_cast<SCHEDULER_CLUSTER_SSBUF SchedulerClusterSignal *>(
        hardware_base + SchedulerClusterRegion::offset
    );
}

// The DSB remains in the SSBUF access path, without an outlined operation wrapper.
inline __aicore__ void scheduler_cluster_barrier() {
    auto *trace = scheduler_scalar_current();
    const bool record = trace != nullptr && trace->buffer != nullptr;
    const uint64_t begin = record ? scheduler_scalar_clock() : 0;
#if defined(__CCE_AICORE__)
    dsb((mem_dsb_t)0);
#else
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
#endif
    if (record) trace->append_memory(SchedPhaseKind::ScalarDsbAll, begin, scheduler_scalar_clock());
}

template <typename T>
inline __aicore__ T scheduler_cluster_load_field(const SCHEDULER_CLUSTER_SSBUF volatile T *field) {
#if defined(__CCE_AICORE__)
    return *field;
#else
    return __atomic_load_n(field, __ATOMIC_ACQUIRE);
#endif
}

template <typename T>
inline __aicore__ void scheduler_cluster_store_field(SCHEDULER_CLUSTER_SSBUF volatile T *field, T value) {
#if defined(__CCE_AICORE__)
    *field = value;
#else
    __atomic_store_n(field, value, __ATOMIC_RELEASE);
#endif
}

inline __aicore__ uint32_t scheduler_cluster_load_acquire(const SCHEDULER_CLUSTER_SSBUF volatile uint32_t *field) {
    const uint32_t value = scheduler_cluster_load_field(field);
    scheduler_cluster_barrier();
    return value;
}

inline __aicore__ void
scheduler_cluster_store_release(SCHEDULER_CLUSTER_SSBUF volatile uint32_t *field, uint32_t value) {
    scheduler_cluster_barrier();
    scheduler_cluster_store_field(field, value);
}

// Called only by the AIC before publishing this cluster's GM INIT bit.
inline __aicore__ void
scheduler_cluster_signal_clear(SCHEDULER_CLUSTER_SSBUF SchedulerClusterSignal *signal, uint64_t run_epoch) {
    scheduler_cluster_store_field(&signal->run_epoch, run_epoch);
    scheduler_cluster_store_field(&signal->gm_arrival_seq, UINT64_C(0));
    scheduler_cluster_store_field(&signal->prepare_task_ref, INT64_C(-1));
    scheduler_cluster_store_field(&signal->prepare_block, UINT32_C(0));
    scheduler_cluster_store_field(&signal->prepare_mask, UINT32_C(0));
    scheduler_cluster_store_field(&signal->staged_mask, UINT32_C(0));
    scheduler_cluster_store_field(&signal->armed_generation, UINT32_C(0));
    scheduler_cluster_store_field(&signal->task_ref, INT64_C(-1));
    scheduler_cluster_store_field(&signal->anchor_state, UINT64_C(0));
    scheduler_cluster_store_field(&signal->sync_tail, UINT32_C(0));
    scheduler_cluster_store_field(&signal->block_idx, UINT32_C(0));
    scheduler_cluster_store_field(&signal->active_mask, UINT32_C(0));
    for (uint32_t lane = 0; lane < PLATFORM_CORES_PER_BLOCKDIM; ++lane) {
        scheduler_cluster_store_field(&signal->prepared[lane], UINT32_C(0));
        scheduler_cluster_store_field(&signal->sync_frontier[lane], UINT32_C(0));
        scheduler_cluster_store_field(&signal->sync_hold[lane], UINT32_C(0));
        scheduler_cluster_store_field(&signal->arrived[lane], UINT32_C(0));
        scheduler_cluster_store_field(&signal->finished[lane], UINT32_C(0));
    }
    scheduler_cluster_store_release(&signal->prepare_generation, UINT32_C(0));
}

// The store-to-load fence pairs with the coordinator's staged-mask fence.
// A release store alone would leave both sides able to miss the conflict.
inline __aicore__ void
scheduler_cluster_hold_sync(SCHEDULER_CLUSTER_SSBUF SchedulerClusterSignal *signal, uint32_t lane, uint64_t sequence) {
    if (signal == nullptr) return;
    scheduler_cluster_store_field(&signal->sync_hold[lane], static_cast<uint32_t>(sequence + 1));
    scheduler_cluster_barrier();
}

inline __aicore__ void scheduler_cluster_advance_sync(
    SCHEDULER_CLUSTER_SSBUF SchedulerClusterSignal *signal, uint32_t lane, uint64_t frontier
) {
    if (signal == nullptr) return;
    scheduler_cluster_store_field(&signal->sync_frontier[lane], static_cast<uint32_t>(frontier));
    scheduler_cluster_barrier();
    scheduler_cluster_store_field(&signal->sync_hold[lane], UINT32_C(0));
}

inline __aicore__ bool
scheduler_cluster_names_lane(const SCHEDULER_CLUSTER_SSBUF SchedulerClusterSignal *signal, uint32_t lane) {
    return signal != nullptr && (scheduler_cluster_load_acquire(&signal->staged_mask) & (UINT32_C(1) << lane)) != 0;
}

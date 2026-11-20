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
#include <algorithm>
#include <array>
#include <fstream>
#include <map>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

#include "record.h"  // NOLINT(build/include_subdir): shared capture format, supplied by the compiler include path.

namespace {
struct Partition {
    std::array<int32_t, 3> captured_kernels;
    int captured_blocks;
    std::vector<uint64_t> scalars;
    int blocks;
};

int parse_blocks(const std::string &value, int original, int candidate) {
    if (value == std::to_string(original)) return original;
    if (value == std::to_string(candidate)) return candidate;
    throw std::runtime_error("Unsupported SWA block count: " + value);
}
}  // namespace

int main(int argc, char **argv) {
    try {
        if (argc != 8)
            throw std::runtime_error(
                "Usage: adapt-plan input output quant-blocks oa-blocks ob-blocks post-blocks padding-blocks"
            );
        const int quant = parse_blocks(argv[3], 64, 54);
        const int oa = parse_blocks(argv[4], 32, 54);
        const int ob = parse_blocks(argv[5], 32, 54);
        const int post = parse_blocks(argv[6], 64, 54);
        const int padding = parse_blocks(argv[7], 80, 8);
        // Each specialized binary expects this scalar signature and partitions exactly this shape.
        std::map<uint64_t, Partition> partitions{
            {9, {{-1, 9, -1}, 80, {80, 72}, padding}},    {22, {{18, 19, 19}, 24, {72, 64, 128, 0, 0}, 48}},
            {25, {{-1, 20, -1}, 64, {72, 8, 80}, quant}}, {28, {{21, 22, 22}, 32, {8192, 72, 80, 80}, oa}},
            {29, {{23, -1, -1}, 32, {80, 8192, 80}, ob}}, {35, {{-1, 27, -1}, 64, {80}, post}},
        };
        std::ifstream input(argv[1], std::ios::binary);
        auto records = dsv41::read_records(input);
        const auto slice = dsv41::select_slice(records, 8, 35);
        for (size_t i = slice.begin; i < slice.end; ++i) {
            auto &h = records[i].header;
            if (h.operation != dsv41::Operation::SUBMIT) continue;
            auto it = partitions.find(h.task_id);
            if (it == partitions.end()) continue;
            const auto &part = it->second;
            if (h.block_num != part.captured_blocks || records[i].scalars != part.scalars ||
                !std::equal(part.captured_kernels.begin(), part.captured_kernels.end(), h.kernels))
                throw std::runtime_error(
                    "Unexpected captured shape or kernels for SWA task " + std::to_string(h.task_id)
                );
            h.block_num = part.blocks;
            h.kernels[2] = -1;  // A6 MIX groups have one vector lane.
            partitions.erase(it);
        }
        if (!partitions.empty()) throw std::runtime_error("Missing SWA partition records");
        std::ofstream output(argv[2], std::ios::binary);
        dsv41::write(output, dsv41::record_magic);
        dsv41::write(output, uint64_t{sizeof(dsv41::Operand)});
        for (const auto &record : records) {
            dsv41::write(output, record.header);
            for (const auto &operand : record.tensors)
                dsv41::write(output, operand);
            for (const auto scalar : record.scalars)
                dsv41::write(output, scalar);
            for (const auto dependency : record.dependencies)
                dsv41::write(output, dependency);
        }
        output.close();
        if (!output) throw std::runtime_error("Failed to finish converted plan");
        std::cout << "A6 SWA: t22=48 x 1C1V, t25=" << quant << " x V, t28=" << oa << " x 1C1V"
                  << ", t29=" << ob << " x C, t35=" << post << " x V, t9=" << padding << " x V\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}

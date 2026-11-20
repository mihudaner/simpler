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
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>

#include "record.h"  // NOLINT(build/include_subdir): shared capture format, supplied by the compiler include path.

int main(int argc, char **argv) {
    try {
        if (argc != 5) throw std::runtime_error("Usage: adapt-plan input-plan output-plan quant-blocks oa-blocks");
        const std::string quant_arg = argv[3], oa_arg = argv[4];
        if ((quant_arg != "54" && quant_arg != "64") || (oa_arg != "32" && oa_arg != "54") ||
            (quant_arg == "64" && oa_arg == "54")) {
            throw std::runtime_error("Expected SWA quant/O-A blocks 64/32, 54/32 or 54/54");
        }
        const int quant_blocks = std::stoi(quant_arg), oa_blocks = std::stoi(oa_arg);
        std::ifstream input(argv[1], std::ios::binary);
        auto records = dsv41::read_records(input);
        const auto slice = dsv41::select_slice(records, 8, 35);
        int matched = 0;
        for (size_t i = slice.begin; i < slice.end; ++i) {
            auto &h = records[i].header;
            if (h.operation != dsv41::Operation::SUBMIT) continue;
            if (h.task_id == 25) {
                if (h.kernels[0] != -1 || h.kernels[1] != 20 || h.kernels[2] != -1 || h.block_num != 64)
                    throw std::runtime_error("Expected original SWA output quantization with 64 vector blocks");
                h.block_num = quant_blocks;
                ++matched;
                continue;
            }
            if (h.task_id != 22 && h.task_id != 28) continue;
            const bool attention = h.task_id == 22;
            const int aic = attention ? 18 : 21;
            const int aiv = attention ? 19 : 22;
            const int blocks = attention ? 24 : 32;
            if (h.kernels[0] != aic || h.kernels[1] != aiv || h.kernels[2] != aiv || h.block_num != blocks) {
                throw std::runtime_error("Expected original SWA 1C2V task; refuse a modified or already adapted plan");
            }
            h.kernels[2] = -1;
            h.block_num = attention ? 48 : oa_blocks;
            ++matched;
        }
        if (matched != 3) throw std::runtime_error("Expected SWA tasks 22, 25 and 28");
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
        std::cout << "A6 SWA: t22=48 x 1C1V, t25=" << quant_blocks << " x V, t28=" << oa_blocks << " x 1C1V\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}

// Copyright (c) PyPTO Contributors.
// This program is free software, you can redistribute it and/or modify it under the terms and conditions of
// CANN Open Software License Agreement Version 2.0 (the "License").
// Please refer to the License for details. You may not use this file except in compliance with the License.
// THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
// INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
// See LICENSE in the root of the software repository for the full text of the License.
// -----------------------------------------------------------------------------------------------------------
#include "../../dsv41_scheduler/kernels/pypto_lib_latest/vendor/aiv/_c2a_compress__2.cpp"
#include "rmsnorm.hpp"

#if defined(__DAV_VEC__)
// Each exported tile adapter passes the address of one tile in the generated UB layout.
// The offsets below are in elements of the pointer type, relative to that tile.
extern "C" __aicore__ inline void __pypto_vf__c2a_compress__2_0(__ubuf__ bfloat16_t *weight) {
    auto base = reinterpret_cast<__ubuf__ float *>(weight);
    auto prev_score = base + 1792;
    auto curr_score = base + 768;
    auto prev_value = base + 1280;
    auto curr_value = base + 256;
    auto pooled = base + 3328;
    auto latent = weight + 7680;
    auto rotated = weight + 8192;
    __VEC_SCOPE__ {
        MaskReg full = pset_b32(PAT_ALL);
        for (uint16_t block = 0; block < 8; ++block) {
            int offset = block * 64;
            RegTensor<float> a, b, max_score, total, x, y;
            vlds(a, prev_score, offset, NORM);
            vlds(b, curr_score, offset, NORM);
            vlds(x, prev_value, offset, NORM);
            vlds(y, curr_value, offset, NORM);
            vmax(max_score, a, b, full, MODE_ZEROING);
            vsub(a, a, max_score, full);
            vsub(b, b, max_score, full);
            vexp(a, a, full, MODE_ZEROING);
            vexp(b, b, full, MODE_ZEROING);
            vadd(total, a, b, full, MODE_ZEROING);
            vdiv(a, a, total, full, MODE_ZEROING);
            vdiv(b, b, total, full, MODE_ZEROING);
            vmul(x, x, a, full, MODE_ZEROING);
            vmul(y, y, b, full, MODE_ZEROING);
            vadd(x, x, y, full, MODE_ZEROING);
            RegTensor<bfloat16_t> bf;
            vcvt(bf, x, full, ROUND_R, RS_DISABLE, PART_EVEN);
            vcvt(x, bf, full, PART_EVEN);
            vsts(x, pooled, offset, NORM_B32, full);
        }
        mem_bar(VST_VLD);
        RegTensor<float> inverse;
        recipe_rms::row_inverse<512>(inverse, pooled, 0, full);
        for (uint16_t block = 0; block < 8; ++block) {
            int offset = block * 64;
            RegTensor<float> value, gain;
            RegTensor<bfloat16_t> bf;
            vlds(value, pooled, offset, NORM);
            vlds(bf, weight, offset, UNPK_B16);
            vcvt(gain, bf, full, PART_EVEN);
            vmul(value, value, inverse, full, MODE_ZEROING);
            vmul(value, value, gain, full, MODE_ZEROING);
            vcvt(bf, value, full, ROUND_R, RS_DISABLE, PART_EVEN);
            vsts(bf, latent, offset, PK_B32, full);
            vsts(bf, rotated, offset, PK_B32, full);
        }
    }
}

namespace {
__aicore__ inline void
set_level(RegTensor<int32_t> &codes, RegTensor<float> &magnitude, float threshold, int32_t level, MaskReg &full) {
    MaskReg selected;
    RegTensor<int32_t> next;
    vcmps_gt(selected, magnitude, threshold, full);
    vdup(next, level, full, MODE_ZEROING);
    vsel(codes, next, codes, selected);
}
}  // namespace

extern "C" __aicore__ inline void __pypto_vf__c2a_compress__2_1(__ubuf__ float *scale_storage) {
    auto bf_base = reinterpret_cast<__ubuf__ bfloat16_t *>(scale_storage);
    auto rotated = bf_base + 7680;
    auto cosine = scale_storage + 1024;
    auto sine = scale_storage + 1536;
    auto payload = reinterpret_cast<__ubuf__ uint8_t *>(scale_storage) + 2048;
    auto factors = bf_base + 4096;
    __VEC_SCOPE__ {
        MaskReg full = pset_b32(PAT_ALL);
        MaskReg lower = pset_b32(PAT_VL32);
        RegTensor<uint32_t> lanes;
        vci((RegTensor<int32_t> &)lanes, 0, INC_ORDER);

        // Apply RoPE to the final 32 pairs of the normalized latent.
        RegTensor<bfloat16_t> bf;
        RegTensor<float> values, cosv, sinv, even, odd, real, imag, a, b, unused;
        vlds(bf, rotated, 448, UNPK_B16);
        vcvt(values, bf, full, PART_EVEN);
        vgather2(cosv, cosine, lanes, lower);
        vgather2(sinv, sine, lanes, lower);
        vdintlv(even, odd, values, values);
        vmul(a, even, cosv, lower, MODE_ZEROING);
        vmul(b, odd, sinv, lower, MODE_ZEROING);
        vsub(real, a, b, lower);
        vmul(a, even, sinv, lower, MODE_ZEROING);
        vmul(b, odd, cosv, lower, MODE_ZEROING);
        vadd(imag, a, b, lower, MODE_ZEROING);
        vintlv(values, unused, real, imag);
        vcvt(bf, values, full, ROUND_R, RS_DISABLE, PART_EVEN);
        mem_bar(VLD_VST);
        vsts(bf, rotated, 448, PK_B32, full);
        mem_bar(VST_VLD);

        // Each 64-value chunk uses four group-16 BF16 scales. The select index
        // is in BF16 lanes; conversion reads the even lanes of each register.
        MaskReg all16 = pset_b16(PAT_ALL);
        MaskReg first64 = pset_b16(PAT_VL64);
        RegTensor<uint16_t> group, abs_mask;
        vci((RegTensor<int16_t> &)group, (int16_t)0, INC_ORDER);
        vshrs(group, group, 5, all16, MODE_ZEROING);
        vdup(abs_mask, (uint16_t)0x7fff, all16, MODE_ZEROING);
        for (uint16_t block = 0; block < 8; ++block) {
            int offset = block * 64;
            RegTensor<uint16_t> bits, magnitude_bits, maxima, selected;
            RegTensor<uint32_t> expanded;
            vlds(bits, reinterpret_cast<__ubuf__ uint16_t *>(rotated), offset, NORM);
            vand(magnitude_bits, bits, abs_mask, first64, MODE_ZEROING);
            vcgmax(maxima, magnitude_bits, first64, MODE_ZEROING);
            vselr(selected, maxima, group);
            vunpack(expanded, bits, LOWER);
            vcvt(values, (RegTensor<bfloat16_t> &)expanded, full, PART_EVEN);
            RegTensor<float> scale, normalized, magnitude;
            vcvt(scale, (RegTensor<bfloat16_t> &)selected, full, PART_EVEN);
            vmuls(scale, scale, 1.0f / 6.0f, full, MODE_ZEROING);
            vmaxs(scale, scale, 1.0f / 512.0f, full, MODE_ZEROING);
            vcvt(bf, scale, full, ROUND_R, RS_DISABLE, PART_EVEN);
            vcvt(scale, bf, full, PART_EVEN);
            vsts(scale, scale_storage, offset, NORM_B32, full);
            vdiv(normalized, values, scale, full, MODE_ZEROING);
            vabs(magnitude, normalized, full);

            // The exported E2M1 encoder rounds exact midpoints toward zero.
            RegTensor<int32_t> codes, sign, sign_mask, even_code, odd_code, packed;
            vdup(codes, 0, full, MODE_ZEROING);
            set_level(codes, magnitude, 0.25f, 1, full);
            set_level(codes, magnitude, 0.75f, 2, full);
            set_level(codes, magnitude, 1.25f, 3, full);
            set_level(codes, magnitude, 1.75f, 4, full);
            set_level(codes, magnitude, 2.5f, 5, full);
            set_level(codes, magnitude, 3.5f, 6, full);
            set_level(codes, magnitude, 5.0f, 7, full);
            vshrs(sign, (RegTensor<int32_t> &)normalized, 28, full, MODE_ZEROING);
            vdup(sign_mask, 8, full, MODE_ZEROING);
            vand(sign, sign, sign_mask, full, MODE_ZEROING);
            vor(codes, codes, sign, full, MODE_ZEROING);
            vdintlv(even_code, odd_code, codes, codes);
            vshls(odd_code, odd_code, 4, lower, MODE_ZEROING);
            vor(packed, even_code, odd_code, lower, MODE_ZEROING);
            vsts((RegTensor<uint8_t> &)packed, payload, block * 32, PK4_B32, lower);
        }
        mem_bar(VST_VLD);
        RegTensor<uint32_t> scale_index;
        RegTensor<float> scales;
        vshls(scale_index, lanes, 4, lower, MODE_ZEROING);
        vgather2(scales, scale_storage, scale_index, lower);
        vcvt(bf, scales, lower, ROUND_R, RS_DISABLE, PART_EVEN);
        mem_bar(VLD_VST);
        vsts(bf, factors, 0, PK_B32, lower);
    }
}
#endif

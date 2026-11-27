// Copyright (c) PyPTO Contributors.
// This program is free software, you can redistribute it and/or modify it under the terms and conditions of
// CANN Open Software License Agreement Version 2.0 (the "License").
// Please refer to the License for details. You may not use this file except in compliance with the License.
// THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
// INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
// See LICENSE in the root of the software repository for the full text of the License.
// -----------------------------------------------------------------------------------------------------------
// The exported outer kernel owns the page addressing, tensor strides, and partial-row DMA.
#include "../../dsv41_scheduler/kernels/pypto_lib_latest/vendor/aiv/idx_k_norm_rope_publish.cpp"

namespace {
__aicore__ inline void load_bf16(RegTensor<float> &value, __ubuf__ bfloat16_t *src, int offset, MaskReg &bfmask) {
    RegTensor<bfloat16_t> raw;
    vlds(raw, src, offset, UNPK_B16);
    vcvt(value, raw, bfmask, PART_EVEN);
}

__aicore__ inline void round_to_bf16(RegTensor<float> &value, MaskReg &full, MaskReg &bfmask) {
    RegTensor<bfloat16_t> rounded;
    vcvt(rounded, value, full, ROUND_R, RS_DISABLE, PART_EVEN);
    vcvt(value, rounded, bfmask, PART_EVEN);
}

__aicore__ inline void sum_squares(RegTensor<float> &sum, RegTensor<float> &value, MaskReg &full) {
    vmul(sum, value, value, full, MODE_ZEROING);
    vcadd(sum, sum, full, MODE_ZEROING);
    vdup(sum, sum, full, POS_LOWEST, MODE_ZEROING);
}

template <int Level>
__aicore__ inline void encode_level(RegTensor<int32_t> &codes, RegTensor<float> &mag, float midpoint, MaskReg &full) {
    MaskReg selected;
    if constexpr (Level % 2 == 0) {
        vcmps_ge(selected, mag, midpoint, full);
    } else {
        vcmps_gt(selected, mag, midpoint, full);
    }
    RegTensor<int32_t> level;
    vdup(level, Level, full, MODE_ZEROING);
    vsel(codes, level, codes, selected);
}

// Each half-row is two independent groups of 32. Each group publishes an E8M0 scale
// and 16 bytes of adjacent E2M1 nibbles, with ties rounded to even.
__aicore__ inline void quantize_half(
    RegTensor<int32_t> &two_scales, RegTensor<float> &values, __ubuf__ uint8_t *out, MaskReg &full, MaskReg &lower,
    MaskReg &upper
) {
    RegTensor<float> mag, lo, hi, scale, normalized;
    vabs(mag, values, full);
    vcmax(lo, mag, lower);
    vcmax(hi, mag, upper);
    vdup(lo, lo, full, POS_LOWEST, MODE_ZEROING);
    vdup(hi, hi, full, POS_LOWEST, MODE_ZEROING);
    vsel(scale, lo, hi, lower);
    vmaxs(scale, scale, 0x1.8p-124f, full, MODE_ZEROING);
    vmuls(scale, scale, 1.0f / 6.0f, full, MODE_ZEROING);
    RegTensor<int32_t> exponent, bits, first, second;
    vadds(bits, (RegTensor<int32_t> &)scale, 0x7fffff, full, MODE_ZEROING);
    vshrs(exponent, bits, 23, full, MODE_ZEROING);
    vshls((RegTensor<int32_t> &)scale, exponent, 23, full, MODE_ZEROING);
    vdiv(normalized, values, scale, full, MODE_ZEROING);
    vdup(first, exponent, full, POS_LOWEST, MODE_ZEROING);
    vdup(second, exponent, full, POS_HIGHEST, MODE_ZEROING);
    vshls(second, second, 8, full, MODE_ZEROING);
    vor(two_scales, first, second, full, MODE_ZEROING);

    RegTensor<int32_t> codes, sign, sign_mask, even, odd;
    vabs(mag, normalized, full);
    vdup(codes, 0, full, MODE_ZEROING);
    encode_level<1>(codes, mag, 0.25f, full);
    encode_level<2>(codes, mag, 0.75f, full);
    encode_level<3>(codes, mag, 1.25f, full);
    encode_level<4>(codes, mag, 1.75f, full);
    encode_level<5>(codes, mag, 2.5f, full);
    encode_level<6>(codes, mag, 3.5f, full);
    encode_level<7>(codes, mag, 5.0f, full);
    vshrs(sign, (RegTensor<int32_t> &)normalized, 28, full, MODE_ZEROING);
    vdup(sign_mask, 8, full, MODE_ZEROING);
    vand(sign, sign, sign_mask, full, MODE_ZEROING);
    vor(codes, codes, sign, full, MODE_ZEROING);
    vdintlv(even, odd, codes, codes);
    vshls(odd, odd, 4, lower, MODE_ZEROING);
    vor(codes, even, odd, lower, MODE_ZEROING);
    vsts(codes, (__ubuf__ int32_t *)out, 0, PK4_B32, lower);
}
}  // namespace

extern "C" __aicore__ inline void __pypto_vf_idx_k_norm_rope_publish_0(__ubuf__ float *sine, int64_t active_rows) {
    // The vendor tile adapter passes the sine tile at the beginning of its UB allocation.
    auto base = reinterpret_cast<__ubuf__ uint8_t *>(sine);
    auto payload = base + 1024;
    auto scales = reinterpret_cast<__ubuf__ int32_t *>(base + 3072);
    auto weight = reinterpret_cast<__ubuf__ bfloat16_t *>(base + 5376);
    auto input = reinterpret_cast<__ubuf__ bfloat16_t *>(base + 5632);
    auto cosine = reinterpret_cast<__ubuf__ float *>(base + 7680);
    uint16_t rows = static_cast<uint16_t>(active_rows);
    __VEC_SCOPE__ {
        MaskReg full = pset_b32(PAT_ALL);
        MaskReg bfmask = pset_b16(PAT_ALL);
        uint32_t group = 32;
        MaskReg lower = plt_b32(group, POST_UPDATE);
        MaskReg upper;
        pnot(upper, lower, full);
        RegTensor<float> weight0, weight1, one;
        load_bf16(weight0, weight, 0, bfmask);
        load_bf16(weight1, weight, 64, bfmask);
        vdup(one, 1.0f, full, MODE_ZEROING);
        RegTensor<uint32_t> trig_index, lane_mask;
        vci((RegTensor<int32_t> &)trig_index, 0, INC_ORDER);
        vdup(lane_mask, 31u, full, MODE_ZEROING);
        vand(trig_index, trig_index, lane_mask, full, MODE_ZEROING);
        for (uint16_t row = 0; row < rows; ++row) {
            RegTensor<float> first, second, sum0, sum1, inverse;
            load_bf16(first, input, row * 128, bfmask);
            load_bf16(second, input, row * 128 + 64, bfmask);
            sum_squares(sum0, first, full);
            sum_squares(sum1, second, full);
            vadd(inverse, sum0, sum1, full, MODE_ZEROING);
            vmuls(inverse, inverse, 1.0f / 128.0f, full, MODE_ZEROING);
            vadds(inverse, inverse, 1.0e-6f, full, MODE_ZEROING);
            vsqrt(inverse, inverse, full, MODE_ZEROING);
            vdiv(inverse, one, inverse, full, MODE_ZEROING);
            vmul(first, first, inverse, full, MODE_ZEROING);
            vmul(first, first, weight0, full, MODE_ZEROING);
            round_to_bf16(first, full, bfmask);
            vmul(second, second, inverse, full, MODE_ZEROING);
            vmul(second, second, weight1, full, MODE_ZEROING);
            round_to_bf16(second, full, bfmask);

            RegTensor<float> cosv, sinv, even, odd, a, b, real, imag, unused;
            vgather2(cosv, cosine + row * 32, trig_index, full);
            vgather2(sinv, sine + row * 32, trig_index, full);
            vdintlv(even, odd, second, second);
            vmul(a, even, cosv, full, MODE_ZEROING);
            vmul(b, odd, sinv, full, MODE_ZEROING);
            vsub(real, a, b, full);
            vmul(a, even, sinv, full, MODE_ZEROING);
            vmul(b, odd, cosv, full, MODE_ZEROING);
            vadd(imag, a, b, full, MODE_ZEROING);
            vintlv(second, unused, real, imag);
            round_to_bf16(second, full, bfmask);

            RegTensor<int32_t> scales0, scales1;
            quantize_half(scales0, first, payload + row * 256, full, lower, upper);
            quantize_half(scales1, second, payload + row * 256 + 32, full, lower, upper);
            vshls(scales1, scales1, 16, full, MODE_ZEROING);
            vor(scales0, scales0, scales1, full, MODE_ZEROING);
            vsts(scales0, scales, row * 64, ONEPT_B32, full);
        }
    }
}

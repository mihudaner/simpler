# Copyright (c) PyPTO Contributors.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.
# -----------------------------------------------------------------------------------------------------------
"""Repeated real DS4.1 SWA sublayers, with shared projection weights.

The first dimension of states, mixes, norm weights and window caches holds
independent layer bands. The Graph specializes the business orchestration for
72 tokens and a 32-AIC/64-AIV target; all compute kernels come from PyPTO-Lib.
"""

# Tensor shapes are PyPTO DSL expressions, not Python generic type arguments.
# pyright: reportInvalidTypeForm=false, reportGeneralTypeIssues=false

from types import SimpleNamespace

import pypto.language as pl
import torch
from config import FLASH as M
from config import LOCAL_T_DYN, ORI_BLOCKS_DYN, T_DYN
from decode_swa import build_swa_specs, decode_swa
from hc_dsl import coefficients_grid, collapse_norm_grid, expand_grid, inverse_rms_grid, project_hf32_grid
from mxfp8_dsl import quantize_bf16_grid
from o_proj_dsl import project_o_a, project_o_b, rope_quant_grid
from q_branch_dsl import normalize_quant_grid, project_q_b, query_rope_grid
from qkv_proj_dsl import project_kv, project_q_a
from swa_dsl import swa_queries
from window_kv_dsl import window_kv_grid
from workloads.swa_validation import Validator  # noqa: F401 -- workload validation entry point

CAPACITY = 100
TOKENS = 72
CACHE_PAGES = 37
D = M.hidden_size
HC_MULT = M.hc_mult
HEAD_DIM = M.head_dim
Q_LORA = M.q_lora_rank
LOCAL_H = M.num_attention_heads
LOCAL_O_WIDTH = M.o_groups * M.o_lora_rank
MX_GROUP = M.weight_block_size[0]
ROPE_DIM = M.qk_rope_head_dim
O_LORA = M.o_lora_rank
LOCAL_O_GROUPS = M.o_groups
O_GROUP_IN = LOCAL_H * HEAD_DIM // LOCAL_O_GROUPS
MIX_HC = M.mix_hc
HC_DIM = M.hc_dim
WINDOW_CACHE_GROUP = 32


@pl.jit.inline(auto_scope=False)
def swa_step(  # noqa: PLR0913 -- mirrors the SWA tensor ABI
    x_hc: pl.Tensor[[TOKENS, HC_MULT, D], pl.FP32],
    incoming_pre_mix: pl.Tensor[[TOKENS, HC_MULT], pl.FP32],
    hc_attn_fn: pl.Tensor[[MIX_HC, HC_DIM], pl.FP32],
    hc_attn_scale: pl.Tensor[[3], pl.FP32],
    hc_attn_base: pl.Tensor[[MIX_HC], pl.FP32],
    attn_norm_weight: pl.Tensor[[D], pl.BF16],
    wq_a: pl.Tensor[[D, Q_LORA], pl.FP8E4M3FN],
    wq_a_scale: pl.Tensor[[D // MX_GROUP, Q_LORA], pl.FP8E8M0, pl.MX_B_NN],
    q_norm_weight: pl.Tensor[[Q_LORA], pl.BF16],
    wq_b: pl.Tensor[[Q_LORA, LOCAL_H * HEAD_DIM], pl.FP8E4M3FN],
    wq_b_scale: pl.Tensor[[Q_LORA // MX_GROUP, LOCAL_H * HEAD_DIM], pl.FP8E8M0, pl.MX_B_NN],
    wkv: pl.Tensor[[D, HEAD_DIM], pl.FP8E4M3FN],
    wkv_scale: pl.Tensor[[D // MX_GROUP, HEAD_DIM], pl.FP8E8M0, pl.MX_B_NN],
    kv_norm_weight: pl.Tensor[[HEAD_DIM], pl.BF16],
    attn_sink: pl.Tensor[[LOCAL_H], pl.FP32],
    wo_a: pl.Tensor[[LOCAL_O_GROUPS, O_GROUP_IN, O_LORA], pl.FP8E4M3FN],
    wo_a_scale: pl.Tensor[[LOCAL_O_GROUPS, O_GROUP_IN // 32, O_LORA], pl.FP8E8M0],
    wo_b: pl.Tensor[[LOCAL_O_WIDTH, D], pl.FP8E4M3FN],
    wo_b_scale: pl.Tensor[[LOCAL_O_WIDTH // MX_GROUP, D], pl.FP8E8M0, pl.MX_B_NN],
    rope_cos: pl.Tensor[[TOKENS, ROPE_DIM // 2], pl.FP32],
    rope_sin: pl.Tensor[[TOKENS, ROPE_DIM // 2], pl.FP32],
    window_slots: pl.Tensor[[TOKENS], pl.INT64],
    window_indices: pl.Tensor[[TOKENS, 128], pl.INT32],
    window_cache: pl.InOut[pl.Tensor[[CACHE_PAGES, 128, 1, HEAD_DIM], pl.FP8E4M3FN]],
    window_cache_scale: pl.InOut[pl.Tensor[[CACHE_PAGES, 128, 1, HEAD_DIM // WINDOW_CACHE_GROUP], pl.BF16]],
    attention_hidden: pl.InOut[pl.Tensor[[TOKENS, HC_MULT, D], pl.FP32]],
    attention_pre_mix: pl.InOut[pl.Tensor[[TOKENS, HC_MULT], pl.FP32]],
    num_tokens: pl.Scalar[pl.INT32],
):
    x_hc.bind_dynamic(0, LOCAL_T_DYN)
    rope_cos.bind_dynamic(0, T_DYN)
    window_cache.bind_dynamic(0, ORI_BLOCKS_DYN)
    attention_output = pl.create_tensor([TOKENS, D], dtype=pl.BF16)
    return decode_swa(
        x_hc,
        incoming_pre_mix,
        hc_attn_fn,
        hc_attn_scale,
        hc_attn_base,
        attn_norm_weight,
        wq_a,
        wq_a_scale,
        q_norm_weight,
        wq_b,
        wq_b_scale,
        wkv,
        wkv_scale,
        kv_norm_weight,
        attn_sink,
        wo_a,
        wo_a_scale,
        wo_b,
        wo_b_scale,
        rope_cos,
        rope_sin,
        window_slots,
        window_indices,
        window_cache,
        window_cache_scale,
        attention_output,
        attention_hidden,
        attention_pre_mix,
        num_tokens,
    )


@pl.jit.inline(auto_scope=False)
def swa_static_step(  # noqa: PLR0913 -- mirrors the SWA tensor ABI
    x_hc: pl.Tensor[[TOKENS, HC_MULT, D], pl.FP32],
    incoming_pre_mix: pl.Tensor[[TOKENS, HC_MULT], pl.FP32],
    hc_attn_fn: pl.Tensor[[MIX_HC, HC_DIM], pl.FP32],
    hc_attn_scale: pl.Tensor[[3], pl.FP32],
    hc_attn_base: pl.Tensor[[MIX_HC], pl.FP32],
    attn_norm_weight: pl.Tensor[[D], pl.BF16],
    wq_a: pl.Tensor[[D, Q_LORA], pl.FP8E4M3FN],
    wq_a_scale: pl.Tensor[[D // MX_GROUP, Q_LORA], pl.FP8E8M0, pl.MX_B_NN],
    q_norm_weight: pl.Tensor[[Q_LORA], pl.BF16],
    wq_b: pl.Tensor[[Q_LORA, LOCAL_H * HEAD_DIM], pl.FP8E4M3FN],
    wq_b_scale: pl.Tensor[[Q_LORA // MX_GROUP, LOCAL_H * HEAD_DIM], pl.FP8E8M0, pl.MX_B_NN],
    wkv: pl.Tensor[[D, HEAD_DIM], pl.FP8E4M3FN],
    wkv_scale: pl.Tensor[[D // MX_GROUP, HEAD_DIM], pl.FP8E8M0, pl.MX_B_NN],
    kv_norm_weight: pl.Tensor[[HEAD_DIM], pl.BF16],
    attn_sink: pl.Tensor[[LOCAL_H], pl.FP32],
    wo_a: pl.Tensor[[LOCAL_O_GROUPS, O_GROUP_IN, O_LORA], pl.FP8E4M3FN],
    wo_a_scale: pl.Tensor[[LOCAL_O_GROUPS, O_GROUP_IN // 32, O_LORA], pl.FP8E8M0],
    wo_b: pl.Tensor[[LOCAL_O_WIDTH, D], pl.FP8E4M3FN],
    wo_b_scale: pl.Tensor[[LOCAL_O_WIDTH // MX_GROUP, D], pl.FP8E8M0, pl.MX_B_NN],
    rope_cos: pl.Tensor[[TOKENS, ROPE_DIM // 2], pl.FP32],
    rope_sin: pl.Tensor[[TOKENS, ROPE_DIM // 2], pl.FP32],
    window_slots: pl.Tensor[[TOKENS], pl.INT64],
    window_indices: pl.Tensor[[TOKENS, 128], pl.INT32],
    window_cache: pl.InOut[pl.Tensor[[CACHE_PAGES, 128, 1, HEAD_DIM], pl.FP8E4M3FN]],
    window_cache_scale: pl.InOut[pl.Tensor[[CACHE_PAGES, 128, 1, HEAD_DIM // WINDOW_CACHE_GROUP], pl.BF16]],
    attention_hidden: pl.InOut[pl.Tensor[[TOKENS, HC_MULT, D], pl.FP32]],
    attention_pre_mix: pl.InOut[pl.Tensor[[TOKENS, HC_MULT], pl.FP32]],
    num_tokens: pl.Scalar[pl.INT32],
):
    # Static specialization of decode_swa: one M80 projection group, 72 live rows.
    # Weight-scale views preserve the lib's MX_B_NN physical byte layout.
    residual = pl.reshape(x_hc, [TOKENS, HC_DIM])
    x_norm = pl.create_tensor([TOKENS, D], dtype=pl.BF16)
    with pl.spmd(12, name_hint="dsl_hc_collapse_norm") as x_ready:
        collapse_norm_grid(residual, incoming_pre_mix, attn_norm_weight, x_norm)
    proj_payload = pl.create_tensor([80, D], dtype=pl.FP8E4M3FN)
    proj_scales = pl.create_tensor([1, 80 * (D // 32)], dtype=pl.FP8E8M0)
    with pl.spmd(12, name_hint="dsl_mxfp8_quant"):
        quantize_bf16_grid(x_norm, proj_payload, proj_scales, num_tokens)

    qa_weight = pl.reshape(wq_a, [1, D * Q_LORA])
    qa_scale = pl.tensor.view(wq_a_scale, [1, D // 32 * Q_LORA], layout=pl.ND)
    qa = pl.create_tensor([80, Q_LORA], dtype=pl.BF16)
    with pl.spmd(Q_LORA // 128, name_hint="dsl_q_proj_a"):
        project_q_a(proj_payload, qa_weight, proj_scales, qa_scale, qa, num_tokens)
    qr = pl.create_tensor([TOKENS, Q_LORA], dtype=pl.BF16)
    qb_payload = pl.create_tensor([80, Q_LORA], dtype=pl.FP8E4M3FN)
    qb_scales = pl.create_tensor([1, 80 * (Q_LORA // 32)], dtype=pl.FP8E8M0)
    with pl.spmd(5, name_hint="dsl_q_norm_quant"):
        normalize_quant_grid(qa, q_norm_weight, qr, qb_payload, qb_scales, num_tokens)
    qb_weight = pl.reshape(wq_b, [1, Q_LORA * LOCAL_H * HEAD_DIM])
    qb_scale = pl.tensor.view(wq_b_scale, [1, Q_LORA // 32 * LOCAL_H * HEAD_DIM], layout=pl.ND)
    raw_query = pl.create_tensor([80, LOCAL_H * HEAD_DIM], dtype=pl.BF16)
    with pl.spmd(32, name_hint="dsl_q_proj_b"):
        project_q_b(qb_payload, qb_weight, qb_scales, qb_scale, raw_query, num_tokens)
    query = pl.create_tensor([TOKENS, LOCAL_H * HEAD_DIM], dtype=pl.BF16)
    with pl.spmd(12, name_hint="dsl_q_rope"):
        query_rope_grid(raw_query, rope_cos, rope_sin, query, num_tokens)

    kv_weight = pl.reshape(wkv, [1, D * HEAD_DIM])
    kv_scale = pl.tensor.view(wkv_scale, [1, D // 32 * HEAD_DIM], layout=pl.ND)
    kv = pl.create_tensor([TOKENS, HEAD_DIM], dtype=pl.BF16)
    with pl.spmd(HEAD_DIM // 128, name_hint="dsl_kv_proj", sync_start=True):
        project_kv(proj_payload, kv_weight, proj_scales, kv_scale, kv, num_tokens)
    cache = pl.reshape(window_cache, [CACHE_PAGES * 128, HEAD_DIM])
    cache_scales = pl.reshape(window_cache_scale, [CACHE_PAGES * 128, HEAD_DIM // 32])
    with pl.spmd(12, name_hint="dsl_window_kv", deps=[x_ready], sync_start=True):
        window_kv_grid(kv, kv_norm_weight, rope_cos, rope_sin, window_slots, cache, cache_scales, num_tokens)
    attended = pl.create_tensor([TOKENS, LOCAL_H * HEAD_DIM], dtype=pl.BF16)
    query_heads = pl.reshape(query, [TOKENS * LOCAL_H, HEAD_DIM])
    attended_heads = pl.reshape(attended, [TOKENS * LOCAL_H, HEAD_DIM])
    sinks = pl.reshape(attn_sink, [1, LOCAL_H])
    attention_ready = pl.system.task_dummy(deps=[])
    with pl.spmd(12, name_hint="dsl_swa", deps=[attention_ready], sync_start=True):
        swa_queries(query_heads, cache, cache_scales, window_indices, sinks, attended_heads, num_tokens)

    inverse = pl.create_tensor([80, 1], dtype=pl.FP32)
    partials = pl.create_tensor([4 * 80, 32], dtype=pl.FP32)
    live_inverse = inverse[0:TOKENS, 0:1]
    with pl.spmd(64, name_hint="dsl_mhc_rms"):
        inverse_rms_grid(residual, live_inverse)
    target = partials[:, 0:MIX_HC]
    with pl.spmd(20, name_hint="dsl_mhc_hf32"):
        project_hf32_grid(residual, hc_attn_fn, target, num_tokens)
    post_mix = pl.create_tensor([TOKENS, HC_MULT], dtype=pl.FP32)
    residual_mix = pl.create_tensor([TOKENS, HC_MULT * HC_MULT], dtype=pl.FP32)
    with pl.spmd(12, name_hint="dsl_mhc_sinkhorn"):
        coefficients_grid(inverse, partials, hc_attn_scale, hc_attn_base, attention_pre_mix, post_mix, residual_mix)

    o_payload = pl.create_tensor([LOCAL_O_GROUPS * 80, O_GROUP_IN], dtype=pl.FP8E4M3FN)
    o_scales = pl.create_tensor([LOCAL_O_GROUPS, 80 * (O_GROUP_IN // 32)], dtype=pl.FP8E8M0)
    with pl.spmd(12, name_hint="dsl_o_rope_quant"):
        rope_quant_grid(attended, rope_cos, rope_sin, o_payload, o_scales, num_tokens)
    oa_weight = pl.reshape(wo_a, [LOCAL_O_GROUPS, O_GROUP_IN * O_LORA])
    oa_scale = pl.reshape(wo_a_scale, [LOCAL_O_GROUPS, O_GROUP_IN // 32 * O_LORA])
    oa = pl.create_tensor([80, LOCAL_O_WIDTH], dtype=pl.BF16)
    with pl.spmd(32, name_hint="dsl_o_proj_a"):
        project_o_a(o_payload, oa_weight, o_scales, oa_scale, oa)
    ob_payload = pl.create_tensor([80, LOCAL_O_WIDTH], dtype=pl.FP8E4M3FN)
    ob_scales = pl.create_tensor([1, 80 * (LOCAL_O_WIDTH // 32)], dtype=pl.FP8E8M0)
    with pl.spmd(12, name_hint="dsl_mxfp8_quant"):
        quantize_bf16_grid(oa, ob_payload, ob_scales, num_tokens)
    ob_weight = pl.reshape(wo_b, [1, LOCAL_O_WIDTH * D])
    ob_scale = pl.tensor.view(wo_b_scale, [1, LOCAL_O_WIDTH // 32 * D], layout=pl.ND)
    attention_output = pl.create_tensor([TOKENS, D], dtype=pl.BF16)
    with pl.spmd(32, name_hint="dsl_o_proj_b"):
        project_o_b(ob_payload, ob_weight, ob_scales, ob_scale, attention_output, num_tokens)
    output = pl.reshape(attention_hidden, [TOKENS, HC_DIM])
    post_ready = pl.system.task_dummy(deps=[])
    with pl.spmd(12, name_hint="dsl_hc_post", deps=[post_ready]):
        expand_grid(attention_output, residual, post_mix, residual_mix, output)
    return attention_hidden, attention_pre_mix


@pl.jit.graph
def swa_graph(  # noqa: PLR0913 -- mirrors the SWA tensor ABI
    x_hc: pl.Tensor[[TOKENS, HC_MULT, D], pl.FP32],
    incoming_pre_mix: pl.Tensor[[TOKENS, HC_MULT], pl.FP32],
    hc_attn_fn: pl.Tensor[[MIX_HC, HC_DIM], pl.FP32],
    hc_attn_scale: pl.Tensor[[3], pl.FP32],
    hc_attn_base: pl.Tensor[[MIX_HC], pl.FP32],
    attn_norm_weight: pl.Tensor[[D], pl.BF16],
    wq_a: pl.Tensor[[D, Q_LORA], pl.FP8E4M3FN],
    wq_a_scale: pl.Tensor[[D // MX_GROUP, Q_LORA], pl.FP8E8M0, pl.MX_B_NN],
    q_norm_weight: pl.Tensor[[Q_LORA], pl.BF16],
    wq_b: pl.Tensor[[Q_LORA, LOCAL_H * HEAD_DIM], pl.FP8E4M3FN],
    wq_b_scale: pl.Tensor[[Q_LORA // MX_GROUP, LOCAL_H * HEAD_DIM], pl.FP8E8M0, pl.MX_B_NN],
    wkv: pl.Tensor[[D, HEAD_DIM], pl.FP8E4M3FN],
    wkv_scale: pl.Tensor[[D // MX_GROUP, HEAD_DIM], pl.FP8E8M0, pl.MX_B_NN],
    kv_norm_weight: pl.Tensor[[HEAD_DIM], pl.BF16],
    attn_sink: pl.Tensor[[LOCAL_H], pl.FP32],
    wo_a: pl.Tensor[[LOCAL_O_GROUPS, O_GROUP_IN, O_LORA], pl.FP8E4M3FN],
    wo_a_scale: pl.Tensor[[LOCAL_O_GROUPS, O_GROUP_IN // 32, O_LORA], pl.FP8E8M0],
    wo_b: pl.Tensor[[LOCAL_O_WIDTH, D], pl.FP8E4M3FN],
    wo_b_scale: pl.Tensor[[LOCAL_O_WIDTH // MX_GROUP, D], pl.FP8E8M0, pl.MX_B_NN],
    rope_cos: pl.Tensor[[TOKENS, ROPE_DIM // 2], pl.FP32],
    rope_sin: pl.Tensor[[TOKENS, ROPE_DIM // 2], pl.FP32],
    window_slots: pl.Tensor[[TOKENS], pl.INT64],
    window_indices: pl.Tensor[[TOKENS, 128], pl.INT32],
    window_cache: pl.InOut[pl.Tensor[[CACHE_PAGES, 128, 1, HEAD_DIM], pl.FP8E4M3FN]],
    window_cache_scale: pl.InOut[pl.Tensor[[CACHE_PAGES, 128, 1, HEAD_DIM // WINDOW_CACHE_GROUP], pl.BF16]],
    attention_hidden: pl.InOut[pl.Tensor[[TOKENS, HC_MULT, D], pl.FP32]],
    attention_pre_mix: pl.InOut[pl.Tensor[[TOKENS, HC_MULT], pl.FP32]],
    num_tokens: pl.Scalar[pl.INT32],
):
    return swa_static_step(
        x_hc,
        incoming_pre_mix,
        hc_attn_fn,
        hc_attn_scale,
        hc_attn_base,
        attn_norm_weight,
        wq_a,
        wq_a_scale,
        q_norm_weight,
        wq_b,
        wq_b_scale,
        wkv,
        wkv_scale,
        kv_norm_weight,
        attn_sink,
        wo_a,
        wo_a_scale,
        wo_b,
        wo_b_scale,
        rope_cos,
        rope_sin,
        window_slots,
        window_indices,
        window_cache,
        window_cache_scale,
        attention_hidden,
        attention_pre_mix,
        num_tokens,
    )


def make_forward(step):
    @pl.jit
    def forward(  # noqa: PLR0913 -- mirrors the SWA tensor ABI
        states: pl.InOut[pl.Tensor],
        mixes: pl.InOut[pl.Tensor],
        hc_attn_fn: pl.Tensor,
        hc_attn_scale: pl.Tensor,
        hc_attn_base: pl.Tensor,
        attn_norm_weight: pl.Tensor,
        wq_a: pl.Tensor,
        wq_a_scale: pl.Tensor[[D // MX_GROUP, Q_LORA], pl.FP8E8M0, pl.MX_B_NN],
        q_norm_weight: pl.Tensor,
        wq_b: pl.Tensor,
        wq_b_scale: pl.Tensor[[Q_LORA // MX_GROUP, LOCAL_H * HEAD_DIM], pl.FP8E8M0, pl.MX_B_NN],
        wkv: pl.Tensor,
        wkv_scale: pl.Tensor[[D // MX_GROUP, HEAD_DIM], pl.FP8E8M0, pl.MX_B_NN],
        kv_norm_weight: pl.Tensor,
        attn_sink: pl.Tensor,
        wo_a: pl.Tensor,
        wo_a_scale: pl.Tensor,
        wo_b: pl.Tensor,
        wo_b_scale: pl.Tensor[[LOCAL_O_WIDTH // MX_GROUP, D], pl.FP8E8M0, pl.MX_B_NN],
        rope_cos: pl.Tensor,
        rope_sin: pl.Tensor,
        window_slots: pl.Tensor,
        window_indices: pl.Tensor,
        window_cache: pl.InOut[pl.Tensor],
        window_cache_scale: pl.InOut[pl.Tensor],
        num_tokens: pl.Scalar[pl.INT32],
        layers: pl.Scalar[pl.INDEX],
    ):
        tokens = TOKENS
        pages = CACHE_PAGES
        for layer in pl.range(layers):
            x_hc = pl.slice(states, [tokens, HC_MULT, D], [layer * tokens, 0, 0])
            incoming_pre_mix = pl.slice(mixes, [tokens, HC_MULT], [layer * tokens, 0])
            attention_hidden = pl.slice(states, [tokens, HC_MULT, D], [(layer + 1) * tokens, 0, 0])
            attention_pre_mix = pl.slice(mixes, [tokens, HC_MULT], [(layer + 1) * tokens, 0])
            layer_norm = pl.slice(attn_norm_weight, [D], [layer * D])
            layer_cache = pl.slice(window_cache, [pages, 128, 1, HEAD_DIM], [layer * pages, 0, 0, 0])
            layer_cache_scale = pl.slice(window_cache_scale, [pages, 128, 1, HEAD_DIM // 32], [layer * pages, 0, 0, 0])
            step(
                x_hc,
                incoming_pre_mix,
                hc_attn_fn,
                hc_attn_scale,
                hc_attn_base,
                layer_norm,
                wq_a,
                wq_a_scale,
                q_norm_weight,
                wq_b,
                wq_b_scale,
                wkv,
                wkv_scale,
                kv_norm_weight,
                attn_sink,
                wo_a,
                wo_a_scale,
                wo_b,
                wo_b_scale,
                rope_cos,
                rope_sin,
                window_slots,
                window_indices,
                layer_cache,
                layer_cache_scale,
                attention_hidden,
                attention_pre_mix,
                num_tokens,
            )
        return states, mixes

    return forward


ordinary = make_forward(swa_step)
graph = make_forward(swa_graph)


INPUT_NAMES = [
    "states",
    "mixes",
    "hc_attn_fn",
    "hc_attn_scale",
    "hc_attn_base",
    "attn_norm_weight",
    "wq_a",
    "wq_a_scale",
    "q_norm_weight",
    "wq_b",
    "wq_b_scale",
    "wkv",
    "wkv_scale",
    "kv_norm_weight",
    "attn_sink",
    "wo_a",
    "wo_a_scale",
    "wo_b",
    "wo_b_scale",
    "rope_cos",
    "rope_sin",
    "window_slots",
    "window_indices",
    "window_cache",
    "window_cache_scale",
]


def inputs(tokens=72):
    options = SimpleNamespace(
        dp=1,
        tokens=tokens,
        local_tokens=tokens,
        requests=12,
        seed=20261116,
        case="mixed",
        active_tokens=tokens,
        start_pos=[1024] * 12,
    )
    values = {spec.name: spec.create_tensor() for spec in build_swa_specs(options) if hasattr(spec, "create_tensor")}
    states = torch.zeros((CAPACITY + 1) * tokens, HC_MULT, D)
    states[:tokens].copy_(values["x_hc"])
    mixes = torch.zeros((CAPACITY + 1) * tokens, HC_MULT)
    mixes[:tokens].copy_(values["incoming_pre_mix"])
    values["states"] = states
    values["mixes"] = mixes
    # Vary a real boundary weight on every invocation, while sharing the large
    # projection matrices. This is a repeated sublayer fixture, not model weights.
    values["attn_norm_weight"] = (
        (
            values["attn_norm_weight"].float().repeat(CAPACITY, 1)
            * (1.0 + torch.arange(CAPACITY).float().view(-1, 1) / 256.0)
        )
        .bfloat16()
        .reshape(-1)
    )
    for name in ("window_cache", "window_cache_scale"):
        source = values[name]
        assert source.shape[0] == CACHE_PAGES
        values[name] = source.view(torch.uint8).repeat(CAPACITY, 1, 1, 1).view(source.dtype)
    return [values[name].contiguous() for name in INPUT_NAMES]

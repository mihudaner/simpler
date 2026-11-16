# Copyright (c) PyPTO Contributors.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.
# -----------------------------------------------------------------------------------------------------------
"""Serial additions with a changing weight band on every Graph invocation."""

import pypto.language as pl
import torch

ROWS = 128
COLS = 128
CAPACITY = 100


@pl.jit.inline(auto_scope=False)
def add_band(w: pl.Tensor, acc: pl.InOut[pl.Tensor], layer: pl.Scalar[pl.INDEX]):
    base = layer * ROWS
    with pl.at(level=pl.Level.CORE_GROUP):
        weight = pl.load(w, [base, 0], [ROWS, COLS])
        current = pl.load(acc, [0, 0], [ROWS, COLS])
        pl.store(pl.add(current, weight), [0, 0], acc)
    return acc


@pl.jit.graph
def graph_band(w: pl.Tensor, acc: pl.InOut[pl.Tensor], layer: pl.Scalar[pl.INDEX]):
    return add_band(w, acc, layer)


@pl.jit
def ordinary(w: pl.Tensor, acc: pl.InOut[pl.Tensor], layers: pl.Scalar[pl.INDEX]):
    for layer in pl.range(layers):
        acc = add_band(w, acc, layer)
    return acc


@pl.jit
def graph(w: pl.Tensor, acc: pl.InOut[pl.Tensor], layers: pl.Scalar[pl.INDEX]):
    for layer in pl.range(layers):
        acc = graph_band(w, acc, layer)
    return acc


def inputs():
    weights = torch.arange(1, CAPACITY + 1, dtype=torch.float32)
    weights = weights.repeat_interleave(ROWS).view(-1, 1).expand(-1, COLS).contiguous()
    return [weights, torch.zeros(ROWS, COLS)]


def validate(actual, layers):
    expected = torch.full((ROWS, COLS), layers * (layers + 1) / 2)
    torch.testing.assert_close(actual, expected, rtol=0, atol=0)
    return {"passed": True, "expected_value": expected[0, 0].item(), "max_abs_error": 0.0}

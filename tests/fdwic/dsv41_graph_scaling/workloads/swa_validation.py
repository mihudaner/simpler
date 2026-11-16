# Copyright (c) PyPTO Contributors.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.
# -----------------------------------------------------------------------------------------------------------
"""Validate every SWA layer against the Lib's independent CPU reference."""

import json

import torch
from decode_swa import golden_swa
from golden import mapped_pool_ratio_allclose, ratio_allclose


class Validator:
    def __init__(self, layers, values, output):
        from workloads.swa import CACHE_PAGES, INPUT_NAMES, TOKENS, D  # noqa: PLC0415

        self.layers = layers
        self.initial = values
        self.named = dict(zip(INPUT_NAMES, values))
        self.output = output
        self.tokens, self.pages, self.hidden = TOKENS, CACHE_PAGES, D
        self.validated = None

    def check(self, actual, index):
        if self.validated is not None:
            for position, tensor in actual.items():
                if not torch.equal(tensor.view(torch.uint8), self.validated[position].view(torch.uint8)):
                    raise AssertionError(f"SWA output {position} differs from the CPU-validated run at round {index}")
            return {"passed": True, "comparison": "exact_replay_of_cpu_validated_outputs"}

        tokens, pages = self.tokens, self.pages
        for position in (0, 1):
            if not torch.isfinite(actual[position]).all():
                raise AssertionError(f"Non-finite SWA output {position}")
            torch.testing.assert_close(actual[position][:tokens], self.initial[position][:tokens], rtol=0, atol=0)
            torch.testing.assert_close(
                actual[position][(self.layers + 1) * tokens :],
                self.initial[position][(self.layers + 1) * tokens :],
                rtol=0,
                atol=0,
            )
        for position in (23, 24):
            if not torch.equal(
                actual[position][self.layers * pages :].view(torch.uint8),
                self.initial[position][self.layers * pages :].view(torch.uint8),
            ):
                raise AssertionError(f"Unused SWA cache layers modified: {position}")

        comparators = {
            "attention_hidden": ratio_allclose(atol=1e-2, rtol=1 / 128),
            "attention_pre_mix": ratio_allclose(atol=1e-4, rtol=1e-4),
            "window_cache": mapped_pool_ratio_allclose(
                "window_slots",
                mapping_shape=(tokens,),
                block_size=128,
                atol=2**-9,
                rtol=2**-3,
                max_error_ratio=0.01,
            ),
            "window_cache_scale": mapped_pool_ratio_allclose(
                "window_slots",
                mapping_shape=(tokens,),
                block_size=128,
                atol=0,
                rtol=0,
                max_error_ratio=0,
            ),
        }
        records = []
        for layer in range(self.layers):
            row = layer * tokens
            page = layer * pages
            # A local reference uses the actual preceding output as its input:
            # each of N transformations is checked without accumulating CPU/NPU
            # floating-point differences across 100 successive transformations.
            expected = dict(self.named)
            expected.update(
                x_hc=actual[0][row : row + tokens],
                incoming_pre_mix=actual[1][row : row + tokens],
                attn_norm_weight=self.initial[5][layer * self.hidden : (layer + 1) * self.hidden],
                window_cache=self.initial[23][page : page + pages].clone(),
                window_cache_scale=self.initial[24][page : page + pages].clone(),
                attention_output=torch.zeros(tokens, self.hidden, dtype=torch.bfloat16),
                attention_hidden=torch.zeros_like(actual[0][row : row + tokens]),
                attention_pre_mix=torch.zeros_like(actual[1][row : row + tokens]),
                num_tokens=tokens,
            )
            golden_swa(expected)
            observed = {
                "attention_hidden": actual[0][row + tokens : row + 2 * tokens],
                "attention_pre_mix": actual[1][row + tokens : row + 2 * tokens],
                "window_cache": actual[23][page : page + pages],
                "window_cache_scale": actual[24][page : page + pages],
            }
            checks = {}
            for name, comparator in comparators.items():
                passed, detail = comparator(
                    observed[name],
                    expected[name],
                    actual_outputs=observed,
                    expected_outputs=expected,
                    inputs=expected,
                    rtol=1e-5,
                    atol=1e-5,
                )
                checks[name] = {"passed": passed, "detail": detail}
                if not passed:
                    (self.output / "golden-failure.json").write_text(
                        json.dumps({"layer": layer + 1, "checks": checks}, indent=2) + "\n"
                    )
                    raise AssertionError(f"SWA layer {layer + 1} {name}: {detail}")
            records.append({"layer": layer + 1, "checks": checks})
            print(f"[SWA GOLDEN] layer={layer + 1}/{self.layers}: hidden, mix, KV and scale passed", flush=True)
        (self.output / "golden.json").write_text(
            json.dumps(
                {
                    "passed": True,
                    "reference": "lib golden_swa, per-layer actual input",
                    "guards_passed": True,
                    "layers": records,
                },
                indent=2,
            )
            + "\n"
        )
        self.validated = actual
        return {"passed": True, "comparison": "independent_cpu_reference_per_layer", "layers_checked": self.layers}

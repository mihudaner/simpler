#!/usr/bin/env python3
# Copyright (c) PyPTO Contributors.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.
# -----------------------------------------------------------------------------------------------------------
"""Check the captured Host ABI and the A6 SWA tile assignments."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from compile_kernels import HERE, REPO, SUITE, swa_tasks

A6_BLOCKS = {12: 54, 22: 48, 30: 54, 33: 54, 34: 54}


def read_records(tool, path):
    return json.loads(subprocess.check_output([str(tool), "--records-json", str(path)], text=True))


def validate_source(records):
    selected = [(r["id"], (r["blocks"], r["kernels"])) for r in records if r["op"] == 2 and 8 <= r["id"] <= 34]
    if selected != list(swa_tasks().items()):
        raise ValueError("Source plan differs from the pinned SWA task table")


def check_conversion(before, after):
    validate_source(before)
    expected = []
    for record in before:
        if record["op"] == 2 and record["id"] in A6_BLOCKS:
            slots = [*record["kernels"][:2], -1]
            record = {**record, "blocks": A6_BLOCKS[record["id"]], "kernels": slots}
        expected.append(record)
    if after != expected:
        raise ValueError("A6 conversion changed fields outside the five SWA partitions")
    return sum(r["blocks"] * sum(k >= 0 for k in r["kernels"]) for r in after if r["op"] == 2 and 8 <= r["id"] <= 34)


def build_converter(cxx, output):
    subprocess.run(
        [
            cxx,
            "-std=c++17",
            "-O2",
            f"-I{SUITE / 'production'}",
            f"-I{REPO / 'src/common'}",
            f"-I{REPO / 'src/common/task_interface'}",
            str(HERE / "adapt_plan.cpp"),
            "-o",
            output,
        ],
        check=True,
    )


def convert_plan(record_tool, converter, original, converted):
    before = read_records(record_tool, original)
    validate_source(before)
    subprocess.run([converter, original, converted], check=True)
    return check_conversion(before, read_records(record_tool, converted))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True, help="Original latest A5 plan-rank0.bin")
    parser.add_argument("--record-tool", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New output directory")
    parser.add_argument("--cxx", default="c++")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    converter = args.output / "adapt-plan"
    build_converter(args.cxx, converter)
    executions = convert_plan(args.record_tool, converter, args.plan, args.output / "plan-a6-rank0.bin")
    print(f"Verified A6 SWA partition and unchanged payloads, flags and dependencies: {executions} kernel instances.")


if __name__ == "__main__":
    main()

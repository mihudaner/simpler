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
import copy
import hashlib
import json
import subprocess
from pathlib import Path

from prepare import A6_PLAN_BLOCKS, DEFAULT_A6_PLAN, FIXTURE, HERE, REPO, SUITE, unpack_fixture


def semantic_hash(records):
    return hashlib.sha256(json.dumps(records, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def read_records(tool, path):
    return json.loads(subprocess.check_output([str(tool), "--records-json", str(path)], text=True))


def check_conversion(before, after, plan):
    quant_blocks, oa_blocks = A6_PLAN_BLOCKS[plan]
    expected = copy.deepcopy(before)
    block_counts = {22: 48, 25: quant_blocks, 28: oa_blocks}
    selected = []
    for record in expected:
        task = record["id"]
        if record["op"] == 2 and task in block_counts:
            record["blocks"] = block_counts[task]
            if task in (22, 28):
                record["kernels"][2] = -1
            selected.append(task)
    if selected != [22, 25, 28] or after != expected:
        raise ValueError(f"Converted capture does not match the {plan} SWA plan")
    tasks = [r for r in after if r["op"] == 2 and 8 <= r["id"] <= 35]
    executions = sum(r["blocks"] * sum(k >= 0 for k in r["kernels"]) for r in tasks)
    if len(tasks) != 16:
        raise ValueError(f"Expected 16 SWA compute tasks for {plan}")
    return executions


def convert_plan(record_tool, converter, original, converted, plan):
    before = read_records(record_tool, original)
    golden = json.loads((FIXTURE / "plan-semantics.json").read_text())
    if len(before) != golden["records"] or semantic_hash(before) != golden["semantic_sha256"]:
        raise ValueError("Host ABI decoded the fixture differently; do not run or convert this capture")
    subprocess.run([converter, original, converted, *map(str, A6_PLAN_BLOCKS[plan])], check=True)
    after = read_records(record_tool, converted)
    executions = check_conversion(before, after, plan)
    return semantic_hash(before), executions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--a6-plan", choices=A6_PLAN_BLOCKS, default=DEFAULT_A6_PLAN)
    parser.add_argument("--cxx", default="g++", help="Host C++ compiler executable, not the AICPU cross compiler")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    tools = output / "host"
    tools.mkdir()
    # No runtime or SDK is needed to read the Host submission format.
    flags = [
        args.cxx,
        "-std=c++17",
        "-O2",
        f"-I{SUITE / 'production'}",
        f"-I{REPO / 'src/common'}",
        f"-I{REPO / 'src/common/task_interface'}",
    ]
    for source, target in (
        (SUITE / "production/record_tool.cpp", "record-tool"),
        (HERE / "adapt_plan.cpp", "adapt-plan"),
    ):
        subprocess.run([*flags, str(source), "-o", str(tools / target)], check=True)
    bundle = output / "bundle"
    unpack_fixture(bundle)
    original, converted = bundle / "plan-rank0.bin", output / "plan-a6-rank0.bin"
    original_semantics, executions = convert_plan(
        tools / "record-tool", tools / "adapt-plan", original, converted, args.a6_plan
    )
    quant_blocks, oa_blocks = A6_PLAN_BLOCKS[args.a6_plan]
    # Keep the original capture intact; the A6 plan stays separately named.
    summary = {
        "runtime_executed": False,
        "host_compiler": subprocess.check_output([args.cxx, "--version"], text=True).splitlines()[0],
        "original_plan_sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
        "original_semantic_sha256": original_semantics,
        "a6_plan_sha256": hashlib.sha256(converted.read_bytes()).hexdigest(),
        "tasks": 16,
        "a5_executions": 578,
        "a6_executions": executions,
        "a6_plan": args.a6_plan,
        "changes": [
            {"task": 22, "before": {"blocks": 24, "lanes": "C,V0,V1"}, "after": {"blocks": 48, "lanes": "C,V"}},
            {"task": 25, "before": {"blocks": 64, "lanes": "V"}, "after": {"blocks": quant_blocks, "lanes": "V"}},
            {"task": 28, "before": {"blocks": 32, "lanes": "C,V0,V1"}, "after": {"blocks": oa_blocks, "lanes": "C,V"}},
        ],
    }
    summary["changes"] = [change for change in summary["changes"] if change["before"] != change["after"]]
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"Verified A5 source capture and A6 {args.a6_plan}: {executions} kernel instances (offline).")


if __name__ == "__main__":
    main()

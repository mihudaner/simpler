# Copyright (c) PyPTO Contributors.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.
# -----------------------------------------------------------------------------------------------------------
"""Run PyPTO-generated orchestration on either current A5 scheduling backend."""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import _task_interface
import torch
from _task_interface import _set_host_log_directory
from pypto.ir import CompiledProgram
from pypto.pypto_core import passes
from pypto.runtime import RunConfig
from simpler._log import TIMING, get_logger
from simpler.task_interface import CallConfig, TaskArgs, TensorArgType
from simpler.worker import Worker
from workloads import simple_chain

from simpler_setup.environment import PROJECT_ROOT
from simpler_setup.torch_interop import torch_dtype_to_datatype


def verify_runtime():
    """Check the installed SDK against this worktree, not PyPTO's other checkout."""
    root = Path(__file__).resolve().parents[3]
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    if Path(PROJECT_ROOT).resolve() != root or _task_interface.__build_commit__ != revision:
        raise RuntimeError("Runtime SDK, Python extension and benchmark worktree must have the same revision")
    # PyPTO's source-checkout guard compares its own runtime/ submodule. This
    # benchmark intentionally selects an independently built runtime worktree;
    # the check above binds both SDK code and the extension to that worktree.
    os.environ["PYPTO_SKIP_RUNTIME_PIN_CHECK"] = "1"
    return revision


def compile_case(args):
    workload = load_workload(args)
    values = workload.inputs()
    entry = getattr(workload, args.variant)
    config = RunConfig(platform="a5", save_kernels_dir=str(args.build))
    start = time.perf_counter_ns()
    with passes.PassContext([], runtime=passes.RuntimeKind.HOST_BUILD_GRAPH):
        if args.workload == "simple_chain":
            compiled = entry.compile(*values, args.layers, config=config)
        else:
            compiled = entry.compile(*values, 72, args.layers, config=config)
    # Assemble the generated host orchestration and kernels before device allocation.
    _ = compiled.chip_callable
    elapsed = time.perf_counter_ns() - start
    (args.build / "compile-summary.json").write_text(
        json.dumps({"variant": args.variant, "compile_ns": elapsed, "runtime": compiled.runtime_name}, indent=2) + "\n"
    )


def execute_case(args):
    logs = args.output / "host-logs"
    logs.mkdir()
    _set_host_log_directory(str(logs.resolve()))
    get_logger().setLevel(TIMING)
    compiled = CompiledProgram.from_dir(args.build)
    if compiled.runtime_name != "host_build_graph":
        raise ValueError("Both comparison arms must use host_build_graph")
    workload = load_workload(args)
    values = workload.inputs()
    records = []
    validator = workload.Validator(args.layers, values, args.output) if args.workload == "swa" else None
    worker = Worker(level=2, platform="a5", device_id=args.device, runtime=args.runtime)
    tensors = []
    try:
        worker.init()
        handle = worker.register(compiled.chip_callable)
        try:
            for value in values:
                buffer = worker.malloc(value.nbytes)
                tensors.append(buffer)
                worker.copy_to(buffer, value)
            task_args = TaskArgs()
            for index, (buffer, value) in enumerate(zip(tensors, values)):
                task_args.add_tensor(
                    buffer.tensor(shapes=tuple(value.shape), dtype=torch_dtype_to_datatype(value.dtype)),
                    TensorArgType.INOUT if index in mutable_indices(args) else TensorArgType.INPUT,
                )
            if args.workload == "swa":
                task_args.add_scalar(72)
            task_args.add_scalar(args.layers)
            for index in range(args.warmup + args.rounds):
                for mutable in mutable_indices(args):
                    worker.copy_to(tensors[mutable], values[mutable])
                run_config = CallConfig()
                run_config.enable_chip_swimlane = 4 if args.diagnostic else 0
                run_config.enable_dep_gen = args.diagnostic
                run_config.output_prefix = str(args.output / f"round-{index}")
                start = time.perf_counter_ns()
                worker.run(handle, task_args, run_config)
                elapsed = time.perf_counter_ns() - start
                expected_mode = 5 if args.runtime == "percounter" else 1
                if worker.scheduler_runtime_mode != expected_mode:
                    raise RuntimeError(f"Unexpected scheduler mode: {worker.scheduler_runtime_mode}")
                checked = validate_output(args, worker, tensors, values, index, validator)
                records.append(
                    {"round": index, "warmup": index < args.warmup, "api_wall_ns": elapsed, "validation": checked}
                )
        finally:
            for tensor in reversed(tensors):
                worker.free(tensor)
    finally:
        worker.close()
    summary = {
        "workload": args.workload,
        "variant": args.variant,
        "runtime": args.runtime,
        "scheduler_mode": expected_mode,
        "layers": args.layers,
        "device": args.device,
        "diagnostic": args.diagnostic,
        "host_phase_breakdown": os.environ.get("SIMPLER_HBG_BIND_BREAKDOWN_ENABLE") == "1",
        "rounds": records,
    }
    (args.output / "result.json").write_text(json.dumps(summary, indent=2) + "\n")


def load_workload(args):
    if args.workload == "simple_chain":
        return simple_chain
    model = Path(args.lib_root) / "models" / "deepseek_v4_1_flash"
    if not model.is_dir():
        raise ValueError("--lib-root must identify a PyPTO-Lib checkout with DS4.1")
    sys.path.insert(0, str(model.resolve()))
    from workloads import swa  # noqa: PLC0415 -- requires the selected PyPTO-Lib module path

    return swa


def mutable_indices(args):
    return (1,) if args.workload == "simple_chain" else (0, 1, 23, 24)


def validate_output(args, worker, tensors, values, index, validator):
    if args.workload == "simple_chain":
        actual = torch.empty_like(values[1])
        worker.copy_from(actual, tensors[1])
        return simple_chain.validate(actual, args.layers)
    actual = {}
    for position in mutable_indices(args):
        value = torch.empty_like(values[position])
        worker.copy_from(value, tensors[position])
        actual[position] = value
    return validator.check(actual, index)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", choices=("ordinary", "graph"), required=True)
    parser.add_argument("--workload", choices=("simple_chain", "swa"), default="simple_chain")
    parser.add_argument("--lib-root", type=Path, default=os.environ.get("PYPTO_LIB_ROOT"))
    parser.add_argument("--runtime", choices=("host_build_graph", "percounter"), default="host_build_graph")
    parser.add_argument("--layers", type=int, choices=(1, 10, 100), default=1)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--compile-only", action="store_true")
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--diagnostic", action="store_true")
    args = parser.parse_args()
    verify_runtime()
    if args.compile_only:
        args.build.mkdir(parents=True, exist_ok=True)
        compile_case(args)
    else:
        if args.output is None:
            parser.error("--output is required for execution")
        args.output.mkdir(parents=True, exist_ok=False)
        execute_case(args)


if __name__ == "__main__":
    main()

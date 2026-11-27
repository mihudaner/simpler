#!/usr/bin/env python3
# Copyright (c) PyPTO Contributors.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.
# -----------------------------------------------------------------------------------------------------------
"""Validate a single-device scheduler snapshot with its native runner."""

import argparse
import hashlib
import json
import os
import shlex
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PRODUCTION = HERE.parent / "dsv41_scheduler/production"


def summarize(output):
    sys.path.insert(0, str(PRODUCTION))
    from timing import paired_spans, summarize_replay  # noqa: PLC0415

    core = summarize_replay(output)
    result = json.loads((output / "rank0/result.json").read_text())
    text = "\n".join(p.read_text() for p in sorted((output / "rank0/host").glob("host.*.log")))
    _, walls = paired_spans(text)
    if len(walls) != 1:
        raise ValueError("SWA requires exactly one device")
    spans = walls[result["device"]]
    if len(spans) != result["warmup"] + result["rounds"]:
        raise ValueError("Unexpected extra invocations in the L0 run")
    wall_ms = [s["duration_ns"] / 1e6 for s in spans[result["warmup"] :]]
    return {
        "runtime": result["runtime"],
        "device": result["device"],
        "profiling_level": 0,
        "warmup": result["warmup"],
        "rounds": result["rounds"],
        "numerical_validation": result["validated_against_fused_prefix"],
        "aicore_mean_ms": core["mean_ms"],
        "aicore_min_ms": min(core["samples_ms"]),
        "aicore_max_ms": max(core["samples_ms"]),
        "aicore_samples_ms": core["samples_ms"],
        "device_mean_ms": statistics.mean(wall_ms),
        "device_samples_ms": wall_ms,
    }


def allocated_device(parser, requested):
    device = os.environ["TASK_DEVICE"]
    if not device.isdigit():
        parser.error("SWA needs one allocated device; TASK_DEVICE must contain a single ID")
    if requested is not None and requested != int(device):
        parser.error("--device differs from the allocated TASK_DEVICE")
    return int(device)


def set_run_defaults(parser, args, platform, built_runtime, has_pair):
    if platform == "a5" and args.device is not None and not os.environ.get("TASK_DEVICE"):
        parser.error("--device must come from task-submit on A5")
    if args.runtime is None:
        args.runtime = "both" if has_pair else built_runtime
    if args.warmup is None:
        args.warmup = 0 if platform == "a6" else 1
    if args.rounds is None:
        args.rounds = 1 if platform == "a6" else 10
    if args.warmup < (0 if platform == "a6" else 1) or args.rounds < 1:
        parser.error("Invalid warmup or round count")


def runtime_packages(parser, build_dir, build, runtimes, has_pair):
    packages = {}
    for runtime in runtimes:
        directory = build_dir / "percounter" if has_pair and runtime == "percounter" else build_dir
        metadata = json.loads((directory / "build.json").read_text())
        if (
            metadata["runtime"] != runtime
            or metadata["platform"] != build["platform"]
            or metadata["case"] != build["case"]
        ):
            parser.error(f"Build a {build['platform']} {build['case']} callable for {runtime} before running it")
        bundle, runner = directory / "bundle", directory / "host/native-runner"
        for path, key in ((runner, "runner_sha256"), (bundle / "callable.bin", "callable_sha256")):
            if hashlib.sha256(path.read_bytes()).hexdigest() != metadata[key]:
                parser.error(f"Build artifact changed: {path.name}")
        packages[runtime] = (metadata, bundle, runner)
    return packages


def run_a6(parser, args, build, bundle, runner, libraries, output):
    if build["plan_sha256"] != hashlib.sha256((bundle / "plan-rank0.bin").read_bytes()).hexdigest():
        parser.error("A6 plan differs from the plan paired with this callable")
    device = allocated_device(parser, args.device) if os.environ.get("TASK_DEVICE") else args.device
    if device is None or device < 0:
        parser.error("Supply the allocated A6 device via --device or TASK_DEVICE")
    rank = output / "rank0"
    rank.mkdir(parents=True)
    command = [
        str(runner),
        str(bundle),
        str(libraries),
        str(device),
        "0",
        str(output / "rootinfo"),
        str(rank),
        str(args.level),
        str(args.warmup),
        str(args.rounds),
        f"--runtime={build['runtime']}",
    ]
    with (rank / "console.log").open("w") as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=False)
    case = json.loads((bundle / "case.json").read_text())["case"]
    if result.returncode:
        raise SystemExit(f"{case} failed (exit {result.returncode}); see {rank / 'console.log'}")
    validation = json.loads((rank / "result.json").read_text())
    if not all(validation[key] for key in ("passed", "snapshot_inputs", "validated_against_fused_prefix")):
        raise RuntimeError(f"Native runner did not validate the {case} snapshot")
    print(f"{case} output check passed. Results: {rank / 'result.json'}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, default=HERE / "build/a5")
    parser.add_argument("--runtime-lib", type=Path)
    parser.add_argument("--runtime", choices=["host_build_graph", "percounter", "both"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--level", type=int, choices=(0, 2), default=0, help="A6 profiling level (default 0)")
    parser.add_argument("--warmup", type=int)
    parser.add_argument("--rounds", type=int)
    parser.add_argument("--device", type=int, help="Allocated logical device ID")
    args = parser.parse_args()
    build_dir, output = args.build_dir.resolve(), args.output.resolve()
    if output.exists():
        parser.error("Output already exists; select a new directory")
    build = json.loads((build_dir / "build.json").read_text())
    platform = build["platform"]
    if platform not in ("a5", "a6"):
        parser.error(f"Unknown bundle platform: {platform}")
    if platform == "a5" and args.level != 0:
        parser.error("This A5 runner collects L0")
    libraries = (args.runtime_lib or REPO / "build/lib" / platform / "onboard").resolve()
    pair = build_dir / "percounter"
    has_pair = build["runtime"] == "host_build_graph" and (pair / "build.json").is_file()
    set_run_defaults(parser, args, platform, build["runtime"], has_pair)
    runtimes = ["host_build_graph", "percounter"] if args.runtime == "both" else [args.runtime]
    packages = runtime_packages(parser, build_dir, build, runtimes, has_pair)
    runtime_files = [libraries / "../dispatcher/libsimpler_aicpu_dispatcher.so"]
    for runtime in runtimes:
        runtime_files += [
            libraries / runtime / name for name in ("libhost_runtime.so", "libaicpu_kernel.so", "aicore_kernel.o")
        ]
    if any(not path.is_file() for path in runtime_files):
        parser.error(f"Missing {platform} runtime artifact: {next(p for p in runtime_files if not p.is_file())}")
    if not os.environ.get("ASCEND_HOME_PATH"):
        parser.error("Source the CANN environment first")
    if platform == "a6":
        for runtime, package in packages.items():
            run_a6(parser, args, *package, libraries, output / runtime if len(packages) > 1 else output)
        return
    if not os.environ.get("TASK_DEVICE"):
        command = [
            sys.executable,
            "-I",
            str(Path(__file__).resolve()),
            "--build-dir",
            str(build_dir),
            "--runtime-lib",
            str(libraries),
            "--runtime",
            args.runtime,
            "--output",
            str(output),
            "--warmup",
            str(args.warmup),
            "--rounds",
            str(args.rounds),
        ]
        subprocess.run(
            ["task-submit", "--device", "auto", "--device-num", "1", "--max-time", "300", "--run", shlex.join(command)],
            check=True,
        )
        return
    device = allocated_device(parser, args.device)
    subprocess.run(["bash", str(REPO / ".claude/skills/onboard-arch-precheck/check.sh"), "a5"], check=True)
    output.mkdir(parents=True)
    record = {
        "case": build["case"],
        "platform": "a5",
        "device": device,
        "start_time": datetime.now(timezone.utc).isoformat(),
        "build": build,
        "callables": {name: package[0]["callable_sha256"] for name, package in packages.items()},
        "runtime_sha256": {
            p.resolve().relative_to(libraries.parent).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in runtime_files
        },
        "status": "running",
        "results": [],
    }
    try:
        for runtime, (_, bundle, runner) in packages.items():
            environment = {**os.environ, "DSV41_RUNNER": str(runner), "DSV41_PYTHON": sys.executable}
            destination = output / runtime
            command = [
                "bash",
                str(PRODUCTION / "run.sh"),
                str(bundle),
                str(libraries),
                str(destination),
                "0",
                str(args.warmup),
                str(args.rounds),
                f"--runtime={runtime}",
            ]
            subprocess.run(command, env=environment, check=True)
            record["results"].append(summarize(destination))
        record["status"] = "passed"
    except Exception:
        record["status"] = "failed"
        raise
    finally:
        record["end_time"] = datetime.now(timezone.utc).isoformat()
        (output / "summary.json").write_text(json.dumps(record, indent=2) + "\n")
    print("\nruntime             AICore mean (ms)  Device mean (ms)  output check")
    for result in record["results"]:
        print(f"{result['runtime']:20} {result['aicore_mean_ms']:16.6f}  {result['device_mean_ms']:16.6f}  PASS")


if __name__ == "__main__":
    main()

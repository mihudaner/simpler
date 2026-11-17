#!/usr/bin/env python3
# Copyright (c) PyPTO Contributors.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.
# -----------------------------------------------------------------------------------------------------------
"""Run the original SWA case with and without AICPU lifecycle detail."""

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def sha256(path):
    return hashlib.file_digest(path.open("rb"), "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--comparison", choices=("detail", "levels"), default="detail")
    args = parser.parse_args()
    os.chdir(ROOT)
    devices = os.environ.get("TASK_DEVICE", "").split(",")
    if len(devices) != 1 or not devices[0].isdigit():
        raise RuntimeError("Run inside one task-submit device allocation")
    subprocess.run(["bash", ".claude/skills/onboard-arch-precheck/check.sh", "a5"], check=True)
    args.output.mkdir(parents=True, exist_ok=False)
    runtime = Path("build/lib/a5/onboard")
    files = [
        args.bundle / "callable.bin",
        args.bundle / "case.json",
        Path("tests/fdwic/dsv41_scheduler/build/portable/host/native-runner"),
        *(
            runtime / "host_build_graph" / name
            for name in ["libhost_runtime.so", "libaicpu_kernel.so", "aicore_kernel.o"]
        ),
        Path("build/lib/a5/dispatcher/libsimpler_aicpu_dispatcher.so"),
    ]
    record = {
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "case": "pypto_lib_latest/swa",
        "runtime": "host_build_graph",
        "device": int(devices[0]),
        "files": [{"path": str(path), "sha256": sha256(path)} for path in files],
        "runs": [],
    }
    plan = [
        ("l0", 0, 0, 10),
        ("current-a", 3, 0, 5),
        ("detail-a", 3, 1, 5),
        ("detail-b", 3, 1, 5),
        ("current-b", 3, 0, 5),
    ]
    if args.comparison == "levels":
        plan = [("l0", 0, 0, 10), ("l2-a", 2, 1, 5), ("l3-a", 3, 1, 5), ("l3-b", 3, 1, 5), ("l2-b", 2, 1, 5)]
    for name, level, detail, rounds in plan:
        output = args.output / name
        command = [
            "bash",
            "tests/fdwic/dsv41_scheduler/production/run.sh",
            str(args.bundle),
            str(runtime),
            str(output),
            str(level),
            "1",
            str(rounds),
            "--runtime=host_build_graph",
        ]
        entry = {
            "name": name,
            "level": level,
            "aicpu_detail": detail,
            "warmup": 1,
            "rounds": rounds,
            "command": command,
            "started": datetime.now(timezone.utc).isoformat(),
        }
        if args.comparison == "levels":
            entry["variant"] = f"l{level}"
        print(f"START {name}: L{level}, AICPU detail={detail}", flush=True)
        with (args.output / f"{name}.log").open("w") as log:
            result = subprocess.run(
                command,
                check=False,
                env={
                    **os.environ,
                    "SIMPLER_HBG_AICPU_DETAIL_ENABLE": str(detail),
                    "SIMPLER_HBG_BIND_BREAKDOWN_ENABLE": "0",
                },
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        entry.update(exit_code=result.returncode, ended=datetime.now(timezone.utc).isoformat())
        record["runs"].append(entry)
        (args.output / "run.json").write_text(json.dumps(record, indent=2) + "\n")
        print(f"END {name}: exit={result.returncode}", flush=True)
        if result.returncode:
            raise RuntimeError(f"{name} failed; see {args.output / (name + '.log')}")


if __name__ == "__main__":
    main()

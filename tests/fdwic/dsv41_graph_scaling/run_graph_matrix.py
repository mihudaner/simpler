# Copyright (c) PyPTO Contributors.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.
# -----------------------------------------------------------------------------------------------------------
"""Run only Graph: HBG and Percounter at 1, 10 and 100 layers, serially."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--workload", choices=("simple_chain", "swa"), default="simple_chain")
    parser.add_argument(
        "--runtimes", choices=("host_build_graph", "percounter"), nargs="+", default=("host_build_graph", "percounter")
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", type=int, required=True)
    parser.add_argument("--rounds", type=int, default=30)
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--host-phases", action="store_true")
    args = parser.parse_args()
    allocated = os.environ.get("TASK_DEVICE", "").split(",")
    if str(args.device) not in allocated:
        parser.error("Run this matrix inside a task-submit allocation and pass its TASK_DEVICE")
    if args.rounds < 1 or args.warmup < 0:
        parser.error("--rounds must be positive and --warmup nonnegative")
    args.output.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ)
    env["SIMPLER_HBG_BIND_BREAKDOWN_ENABLE"] = "1" if args.host_phases else "0"
    commands = []
    for layers in (1, 10, 100):
        for runtime in args.runtimes:
            name = f"{runtime}-graph-{layers}"
            command = [
                sys.executable,
                str(Path(__file__).with_name("run.py")),
                "--workload",
                args.workload,
                "--variant",
                "graph",
                "--runtime",
                runtime,
                "--layers",
                str(layers),
                "--build",
                str(args.build),
                "--output",
                str(args.output / name),
                "--device",
                str(args.device),
                "--rounds",
                str(args.rounds),
                "--warmup",
                str(args.warmup),
            ]
            print(f"RUN {name}", flush=True)
            with (args.output / f"{name}.log").open("w") as log:
                result = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT, check=False)
            commands.append({"case": name, "exit_code": result.returncode})
            (args.output / "matrix.json").write_text(json.dumps(commands, indent=2) + "\n")
            if result.returncode:
                raise SystemExit(f"{name} failed; see its log")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# Copyright (c) PyPTO Contributors.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.
# -----------------------------------------------------------------------------------------------------------
"""Render both captures and add Device-wall boundaries from the same run."""

import argparse
import gzip
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", type=Path, default=ARCHIVE / "analysis/r002")
    parser.add_argument("--output", type=Path, default=ARCHIVE / "traces")
    args = parser.parse_args()
    labels = json.loads((ARCHIVE / "labels.zh-CN.json").read_text())
    summary = json.loads((args.analysis / "summary.json").read_text())
    traces = args.output
    traces.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((ROOT / "tests/fdwic/dsv41_scheduler/kernels/pypto_lib_latest/manifest.json").read_text())
    (traces / "name_map.json").write_text(
        json.dumps(
            {
                "level": 2,
                "orchestrator_name": "SWA",
                "callable_id_to_name": {str(k["func_id"]): k["name"] for k in manifest["kernels"]},
            },
            indent=2,
        )
        + "\n"
    )
    validation = {}
    for variant, sample in summary["representatives"].items():
        source = ROOT / sample["capture"]
        stem = traces / f"swa-{variant}-L{sample['level']}"
        copied = stem.with_suffix(".source.json")
        content = gzip.decompress(source.read_bytes()) if source.suffix == ".gz" else source.read_bytes()
        raw = json.loads(content)
        copied.write_bytes(content)
        shutil.copyfile(source.parent / "deps.json", stem.with_suffix(".deps.json"))
        output = stem.with_suffix(".json.gz")
        subprocess.run(
            [
                sys.executable,
                "-m",
                "simpler_setup.tools.swimlane_converter",
                str(copied),
                "--deps-json",
                str(stem.with_suffix(".deps.json")),
                "--func-names",
                str(traces / "name_map.json"),
                "-o",
                str(output),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        trace = json.loads(gzip.decompress(output.read_bytes()))
        lookup = {(row[6], row[0], row[2]): row[3] for row in raw["aicore_tasks"]}
        scale = 1e6 / sample["frequency_hz"]
        anchor = None
        checked = 0
        for event in trace["traceEvents"]:
            fields = event.get("args", {})
            if event.get("pid") != 4 or event.get("ph") != "X" or "kernel-start-time-us" not in fields:
                continue
            match = re.search(r"CoreId:(\d+)", fields["event-hint"])
            assert match is not None
            core = int(match[1])
            cycle = lookup[(fields["run_epoch"], core, fields["reg_task_id"])]
            display = fields["kernel-start-time-us"]
            if anchor is None:
                anchor = (cycle, display)
            assert abs(display - (anchor[1] + (cycle - anchor[0]) * scale)) < 0.001
            checked += 1
        assert checked == len(raw["aicore_tasks"]) == 578

        assert anchor is not None
        anchor_cycle, anchor_display = anchor

        def mapped(cycle):
            return anchor_display + (cycle - anchor_cycle) * scale

        points = [sample[f"t{i}"] for i in range(4)]
        trace["traceEvents"].extend(
            [
                {"ph": "M", "pid": 7, "name": "process_name", "args": {"name": "Device wall"}},
                {"ph": "M", "pid": 7, "name": "process_sort_index", "args": {"sort_index": 0}},
                {"ph": "M", "pid": 7, "tid": 70000, "name": "thread_name", "args": {"name": labels["thread"]}},
            ]
        )
        for name, start, end in [
            ("Device wall", points[0], points[3]),
            (labels["before"], points[0], points[1]),
            (labels["aicore"], points[1], points[2]),
            (labels["after"], points[2], points[3]),
        ]:
            trace["traceEvents"].append(
                {
                    "ph": "X",
                    "pid": 7,
                    "tid": 70000,
                    "cat": "device_wall_breakdown",
                    "name": name,
                    "ts": mapped(start),
                    "dur": (end - start) * scale,
                    "args": {"start_cycle": start, "end_cycle": end, "frequency_hz": sample["frequency_hz"]},
                }
            )
        trace["metadata"]["device_wall_breakdown"] = {
            "source": "same-invocation STRACE integer endpoints",
            "kernel_anchors_checked": checked,
            "host_clock_alignment_used": False,
        }
        with gzip.open(output, "wt", encoding="utf-8") as stream:
            json.dump(trace, stream, ensure_ascii=False, separators=(",", ":"))
        with gzip.GzipFile(filename=stem.with_suffix(".raw.json.gz"), mode="wb") as dst:
            dst.write(content)
        copied.unlink()
        flows = {phase: [e["id"] for e in trace["traceEvents"] if e.get("ph") == phase] for phase in ("s", "f")}
        assert sorted(flows["s"]) == sorted(flows["f"])
        validation[variant] = {
            "file": str(output.resolve().relative_to(ROOT)),
            "kernel_anchors_checked": checked,
            "flow_pairs": len(flows["s"]),
            "gzip_json_readable": True,
            "lifecycle_intervals": sum(e.get("cat") == "aicpu_lifecycle" for e in trace["traceEvents"]),
        }
    (args.analysis / "trace-validation.json").write_text(json.dumps(validation, indent=2) + "\n")


if __name__ == "__main__":
    main()

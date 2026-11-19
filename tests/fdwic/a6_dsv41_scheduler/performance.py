#!/usr/bin/env python3
# Copyright (c) PyPTO Contributors.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.
# -----------------------------------------------------------------------------------------------------------
"""Report native SWA Host/device timing and save one representative L3 device trace."""

import argparse
import io
import json
import lzma
import re
import statistics
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SUITE = Path(__file__).resolve().parents[1] / "dsv41_scheduler"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SUITE / "production"))

from timing import paired_spans  # noqa: E402

from simpler_setup.tools.strace_timing import parse_span_records  # noqa: E402

HOST = ("bind", "publish_image", "prepare_execution")
PHASES = {
    "handshake": ("handshake_start_cycles", "handshake_complete_cycles"),
    "bootstrap_wait": ("bootstrap_wait_start_cycles", "bootstrap_complete_cycles"),
    "exit_wait": ("exit_wait_start_cycles", "exit_wait_end_cycles"),
}


def lifecycle(raw, expected):
    streams = raw["scheduler_records"]["streams"]
    if any(s["capture"]["dropped"] or s["capture"]["truncated"] for s in streams):
        raise ValueError("Incomplete scheduler capture")
    tasks = raw["aicore_tasks"]
    if len(tasks) != expected or len(raw["aicore_execution_identities"]["records"]) != expected:
        raise ValueError(f"Expected {expected} executions and identities")
    intervals = defaultdict(list)
    for row in raw["aicpu_lifecycle_records"]:
        for name, (start, end) in PHASES.items():
            if row[start] and row[end]:
                intervals[name].append((row[start], row[end]))
        for item in row["detail_intervals"]:
            intervals[item["name"]].append((item["start_cycles"], item["end_cycles"]))
    result = {}
    for name in (*PHASES, "swimlane_init", "swimlane_collect"):
        spans = sorted(intervals[name])
        if not spans:
            raise ValueError(f"No AICPU detail for {name}")
        cursor = total = 0
        for start, end in spans:
            if end < start:
                raise ValueError(f"Invalid {name} interval")
            total += max(0, end - max(start, cursor))
            cursor = max(cursor, end)
        result[name] = total * 1e6 / raw["metadata"]["clock_freq_hz"]
    return result


def save_trace(capture, target, points, expected):
    if target.exists():
        raise FileExistsError(target)
    manifest = json.loads((SUITE / "kernels/pypto_lib_latest/manifest.json").read_text())
    fixture = json.loads((Path(__file__).parent / "fixtures/fixture.json").read_text())
    selected = set(fixture["kernel_ids"])
    names = {str(k["func_id"]): k["name"] for k in manifest["kernels"] if k["func_id"] in selected}
    with tempfile.TemporaryDirectory() as temp:
        mapping, trace = Path(temp) / "name_map.json", Path(temp) / "trace.json"
        mapping.write_text(json.dumps({"level": 2, "orchestrator_name": "SWA", "callable_id_to_name": names}))
        subprocess.run(
            [
                sys.executable,
                "-m",
                "simpler_setup.tools.swimlane_converter",
                str(capture),
                "--device-only",
                "--func-names",
                str(mapping),
                "--deps-json",
                str(capture.with_name("deps.json")),
                "-o",
                str(trace),
            ],
            cwd=ROOT,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        document = json.loads(trace.read_bytes())
    events = document["traceEvents"]
    workers = [e for e in events if e.get("pid") == 4 and "kernel-start-time-us" in e.get("args", {})]
    if len(workers) != expected or any(
        e["name"].split("(")[0].removesuffix("_spmd") not in names.values() for e in workers
    ):
        raise ValueError("Missing or unnamed worker executions")
    if not any(e.get("cat") == "aicpu_lifecycle" and e.get("name") == "swimlane_collect" for e in events):
        raise ValueError("Missing AICPU collection intervals")
    if points is not None:
        first = min(e["args"]["kernel-start-time-us"] for e in workers)
        t0, t1, t2, t3 = points
        events.append({"ph": "M", "pid": 7, "name": "process_name", "args": {"name": "Device wall"}})
        for name, start, end in (
            ("Device wall", t0, t3),
            ("Before kernels", t0, t1),
            ("AICore window", t1, t2),
            ("After kernels", t2, t3),
        ):
            events.append(
                {
                    "ph": "X",
                    "pid": 7,
                    "tid": 1,
                    "cat": "device_wall_breakdown",
                    "name": name,
                    "ts": first + (start - t1) / 1000,
                    "dur": (end - start) / 1000,
                }
            )
    target.parent.mkdir(parents=True, exist_ok=True)
    with lzma.LZMAFile(target, "x") as output, io.TextIOWrapper(output, encoding="utf-8") as stream:
        json.dump(document, stream, separators=(",", ":"), ensure_ascii=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path, help="Parent of rank0/")
    parser.add_argument("--platform", required=True, choices=("a5", "a6"))
    parser.add_argument("--level", required=True, type=int, choices=(0, 3))
    parser.add_argument("--trace", type=Path, help="Write one L3 .json.xz selected by median Device wall")
    parser.add_argument(
        "--shared-device-clock",
        action="store_true",
        help="Split RunWall when both endpoints use the same device counter epoch",
    )
    args = parser.parse_args()
    rank = args.run / "rank0"
    result = json.loads((rank / "result.json").read_text())
    if not all(
        result[k] for k in ("passed", "snapshot_inputs", "numerical_validation", "validated_against_fused_prefix")
    ):
        raise ValueError("SWA snapshot validation failed")
    if (result["rank"], result["ranks"], result["runtime"], result["warmup"], result["rounds"]) != (
        0,
        1,
        "host_build_graph",
        1,
        10,
    ):
        raise ValueError("Expected HBG, one warmup and ten measurements")
    lines = re.findall(
        r"run=(\d+) scheduler_mode=(\d+) profiling=(\d+) warmup=(\d+)", (rank / "console.log").read_text()
    )
    if [tuple(map(int, line)) for line in lines] != [(i, 1, args.level, int(i == 0)) for i in range(11)]:
        raise ValueError("Wrong scheduler mode, level or measured iterations")
    logs = "\n".join(p.read_text() for p in sorted((rank / "host").glob("host.*.log")))
    cores, walls = paired_spans(logs)
    dev = result["device"]
    if set(cores) != {dev} or len(cores[dev]) != 11:
        raise ValueError("Missing or extra invocations")
    host = defaultdict(dict)
    for span, _ in parse_span_records(logs.splitlines()):
        if span.name in {"chip.run", *("chip.run." + phase for phase in HOST)}:
            call = host[span.pid, span.inv]
            if span.name in call:
                raise ValueError(f"Duplicate Host span {span.name}")
            call[span.name] = span.dur / 1000
    expected = 578 if args.platform == "a5" else 570
    samples, endpoints = [], []
    for iteration, (core, wall) in enumerate(zip(cores[dev][1:], walls[dev][1:], strict=True), 1):
        t0, t1, t2, t3 = wall["start_cycle"], core["start_cycle"], core["end_cycle"], wall["end_cycle"]
        call = host[core["pid"], core["invocation"]]
        sample = {phase: call["chip.run." + phase] for phase in HOST}
        sample.update(api=call["chip.run"], core=core["duration_ns"] / 1000, device=wall["duration_ns"] / 1000)
        if args.shared_device_clock:
            if core["clock_hz"] != 1_000_000_000 or not t0 <= t1 < t2 <= t3:
                raise ValueError("Cannot split endpoints on a shared 1 GHz device clock")
            sample.update(before=(t1 - t0) / 1000, after=(t3 - t2) / 1000)
        if args.level == 3:
            raw = json.loads((rank / f"run{iteration}/chip_swimlane_records.json").read_bytes())
            rows = raw["aicore_tasks"]
            if not rows or (min(r[3] for r in rows), max(r[4] for r in rows)) != (t1, t2):
                raise ValueError("Trace kernel endpoints differ from AICore wall")
            sample.update(lifecycle(raw, expected))
        samples.append(sample)
        endpoints.append((t0, t1, t2, t3))
    for field in samples[0]:
        print(f"{field:18} {statistics.mean(s[field] for s in samples):10.3f} us")
    if args.trace:
        if args.level != 3:
            parser.error("--trace requires --level 3")
        median = statistics.median(s["device"] for s in samples)
        index = min(range(len(samples)), key=lambda i: abs(samples[i]["device"] - median))
        capture = rank / f"run{index + 1}/chip_swimlane_records.json"
        save_trace(capture, args.trace, endpoints[index] if args.shared_device_clock else None, expected)
        print(f"L3 representative: run{index + 1}, Device wall {samples[index]['device']:.3f} us")


if __name__ == "__main__":
    main()

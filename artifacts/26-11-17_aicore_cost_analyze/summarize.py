#!/usr/bin/env python3
# Copyright (c) PyPTO Contributors.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.
# -----------------------------------------------------------------------------------------------------------
"""Summarize same-device SWA profiling runs and select representative captures."""

import argparse
import csv
import gzip
import hashlib
import json
import math
import re
import shlex
import statistics
from pathlib import Path

from simpler_setup.tools.strace_timing import parse_span_records

METRICS = ("before_us", "aicore_us", "after_us", "device_us")

COARSE_PHASES = {
    "handshake": ("handshake_start_cycles", "handshake_complete_cycles"),
    "topology_config": ("config_start_cycles", "topology_complete_cycles"),
    "context_publish": ("context_publish_start_cycles", "context_publish_complete_cycles"),
    "bootstrap_wait": ("bootstrap_wait_start_cycles", "bootstrap_complete_cycles"),
    "register_release": ("register_release_start_cycles", "register_release_end_cycles"),
    "exit_signal": ("exit_signal_start_cycles", "exit_signal_end_cycles"),
    "exit_wait": ("exit_wait_start_cycles", "exit_wait_end_cycles"),
}


def union_cycles(intervals, low, high):
    cursor, total = low, 0
    for start, end in sorted(intervals):
        start, end = max(start, low, cursor), min(end, high)
        if end > start:
            total += end - start
            cursor = end
    return total


def lifecycle_summary(samples, output):
    evidence, aggregate = [], {}
    for row in samples:
        if row["warmup"] or row["variant"] == "l0":
            continue
        path = Path(row["capture"])
        content = gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()
        raw = json.loads(content)
        streams = raw.get("scheduler_records", {}).get("streams", [])
        dropped = sum(stream["capture"]["dropped"] for stream in streams)
        truncated = any(stream["capture"]["truncated"] for stream in streams)
        assert not dropped and not truncated, (path, dropped, truncated)
        assert len(raw["aicore_tasks"]) == 578
        intervals = {}
        for trace in raw["aicpu_lifecycle_records"]:
            for name, (start, end) in COARSE_PHASES.items():
                if trace.get(start, 0) and trace.get(end, 0):
                    intervals.setdefault(name, []).append((trace[start], trace[end]))
            for entry in trace.get("detail_intervals", []):
                start, end = entry["start_cycles"], entry["end_cycles"]
                assert row["t0"] <= start <= end <= row["t3"]
                intervals.setdefault(entry["name"], []).append((start, end))
        phases = {}
        for name, ranges in intervals.items():
            scale = 1e6 / row["frequency_hz"]
            values = {
                "window_us": union_cycles(ranges, row["t0"], row["t3"]) * scale,
                "before_us": union_cycles(ranges, row["t0"], row["t1"]) * scale,
                "after_us": union_cycles(ranges, row["t2"], row["t3"]) * scale,
            }
            phases[name] = values
            aggregate.setdefault((row["variant"], name), []).append(values)
        evidence.append(
            {
                "group": row["group"],
                "iteration": row["iteration"],
                "capture": str(path),
                "sha256_uncompressed": hashlib.sha256(content).hexdigest(),
                "kernels": len(raw["aicore_tasks"]),
                "scheduler_streams": len(streams),
                "dropped": dropped,
                "truncated": truncated,
                "lifecycle_records": raw["aicpu_lifecycle_records"],
                "phases": phases,
            }
        )
    (output / "lifecycle-samples.json").write_text(json.dumps(evidence, indent=2) + "\n")
    result = {
        f"{variant}/{name}": {metric: stats([r[metric] for r in rows]) for metric in rows[0]}
        for (variant, name), rows in aggregate.items()
    }
    (output / "lifecycle-summary.json").write_text(json.dumps(result, indent=2) + "\n")


def stats(values):
    return {
        "n": len(values),
        "mean": statistics.mean(values),
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run = json.loads((args.run / "run.json").read_text())
    samples, logs = [], {}
    for config in run["runs"]:
        assert config["exit_code"] == 0
        group = config["name"]
        rank = args.run / group / "rank0"
        result = json.loads((rank / "result.json").read_text())
        assert result["passed"] and result["numerical_validation"] and result["snapshot_inputs"]
        observed = [
            tuple(map(int, row))
            for row in re.findall(
                r"run=(\d+) scheduler_mode=(\d+) profiling=(\d+) warmup=(\d+)", (rank / "console.log").read_text()
            )
        ]
        expected = [
            (i, 1, config["level"], int(i < config["warmup"])) for i in range(config["warmup"] + config["rounds"])
        ]
        assert observed == expected, (group, observed)
        invocations = {}
        for path in sorted((rank / "host").glob("host.*.log")):
            for span, line in parse_span_records(path.read_text().splitlines()):
                key = (span.pid, span.inv)
                invocations.setdefault(key, {})[span.name] = span
                logs.setdefault((group, key), []).append(line)
        calls = [(key, spans) for key, spans in invocations.items() if "chip.run.runner_run.device_wall" in spans]
        calls.sort(key=lambda item: item[1]["chip.run"].ts)
        assert len(calls) == len(expected), (group, len(calls))
        for iteration, (key, spans) in enumerate(calls):
            device = spans["chip.run.runner_run.device_wall"]
            core = spans["chip.run.runner_run.aicore_wall"]
            da = dict(token.split("=", 1) for token in shlex.split(device.attrs))
            ca = dict(token.split("=", 1) for token in shlex.split(core.attrs))
            hz = int(da["dev_cnt_hz"])
            assert hz == int(ca["aicore_cnt_hz"])
            endpoints = [
                int(da["dev_start_cycle"]),
                int(ca["aicore_start_cycle"]),
                int(ca["aicore_end_cycle"]),
                int(da["dev_end_cycle"]),
            ]
            assert endpoints == sorted(endpoints)
            durations = [(endpoints[i + 1] - endpoints[i]) * 1e6 / hz for i in range(3)]
            wall = (endpoints[3] - endpoints[0]) * 1e6 / hz
            assert math.isclose(wall, device.dur / 1000, abs_tol=0.002)
            capture = rank / f"run{iteration}" / "chip_swimlane_records.json"
            if not capture.exists() and capture.with_suffix(".json.gz").exists():
                capture = capture.with_suffix(".json.gz")
            samples.append(
                {
                    "group": group,
                    "level": config["level"],
                    "variant": config.get(
                        "variant", "l0" if config["level"] == 0 else ("detail" if config["aicpu_detail"] else "current")
                    ),
                    "iteration": iteration,
                    "warmup": iteration < config["warmup"],
                    "pid": key[0],
                    "inv": key[1],
                    "frequency_hz": hz,
                    "t0": endpoints[0],
                    "t1": endpoints[1],
                    "t2": endpoints[2],
                    "t3": endpoints[3],
                    **dict(zip(METRICS, [*durations, wall])),
                    "capture": str(capture),
                }
            )
    summary, chosen = {}, {}
    variants = list(dict.fromkeys(row["variant"] for row in samples))
    for variant in variants:
        rows = [s for s in samples if s["variant"] == variant and not s["warmup"]]
        summary[variant] = {metric: stats([s[metric] for s in rows]) for metric in METRICS}
        if variant == "l0":
            continue
        representative = min(rows, key=lambda s: abs(s["device_us"] - summary[variant]["device_us"]["median"]))
        chosen[variant] = representative
    comparisons = {}
    for base, candidate in ((variants[0], variants[1]), (variants[0], variants[2]), (variants[1], variants[2])):
        comparisons[f"{candidate}_vs_{base}"] = {
            metric: {
                "ratio": summary[candidate][metric]["mean"] / summary[base][metric]["mean"],
                "change_percent": (summary[candidate][metric]["mean"] / summary[base][metric]["mean"] - 1) * 100,
            }
            for metric in METRICS
        }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "summary.json").write_text(
        json.dumps(
            {
                "unit": "us",
                "summary": summary,
                "comparisons": comparisons,
                "representatives": chosen,
                "all_outputs_validated": True,
            },
            indent=2,
        )
        + "\n"
    )
    with (args.output / "samples.csv").open("w") as f:
        writer = csv.DictWriter(f, fieldnames=list(samples[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(samples)
    for variant, row in chosen.items():
        key = (row["group"], (row["pid"], row["inv"]))
        (args.output / f"{variant}.host.log").write_text("\n".join(logs[key]) + "\n")
    lifecycle_summary(samples, args.output)
    print(
        json.dumps({v: {m: round(x["mean"], 3) for m, x in values.items()} for v, values in summary.items()}, indent=2)
    )


if __name__ == "__main__":
    main()

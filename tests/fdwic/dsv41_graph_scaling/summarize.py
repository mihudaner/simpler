# Copyright (c) PyPTO Contributors.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.
# -----------------------------------------------------------------------------------------------------------
"""Summarize validated, non-diagnostic runs with the repository STRACE parser."""

import argparse
import csv
import json
import statistics
from pathlib import Path

from simpler_setup.tools.strace_timing import (
    count_record_heads,
    group_invocations,
    parse_drop_summaries,
    parse_spans,
)

MARKERS = {
    "host_total_us": "chip.run",
    "host_bind_us": "chip.run.bind",
    "device_wall_us": "chip.run.runner_run.device_wall",
    "aicore_us": "chip.run.runner_run.aicore_wall",
}
HOST_PHASES = {
    "host_orch_us": "chip.run.bind.host_orch",
    "graph_definitions_us": "chip.run.bind.graph_definitions",
    "native_nodes_us": "chip.run.bind.graph_definitions.native_nodes",
    "scheduler_state_us": "chip.run.bind.commit.scheduler_state",
    "scheduler_calls_us": "chip.run.bind.commit.scheduler_state.calls",
}


def read_case(path, host_phases=False):
    result = json.loads(path.read_text())
    if result["diagnostic"] or result.get("host_phase_breakdown", False) != host_phases:
        raise ValueError(f"Diagnostic capture cannot enter performance statistics: {path}")
    log_paths = sorted(path.parent.rglob("host.*.log"))
    lines = [line for log in log_paths for line in log.read_text().splitlines()]
    spans = list(parse_spans(lines))
    if len(spans) != count_record_heads(lines) or any(x["total"] for x in parse_drop_summaries(lines).values()):
        raise ValueError(f"Lost STRACE records: {path}")
    invocations = [inv for inv in group_invocations(spans) if inv.root() is not None]
    if len(invocations) != len(result["rounds"]):
        raise ValueError(f"Invocation / round count mismatch: {path}")
    samples = []
    for record, inv in zip(result["rounds"], invocations):
        if not record["validation"]["passed"]:
            raise ValueError(f"Unvalidated result: {path}")
        names = inv.by_name()
        missing = set(MARKERS.values()) - names.keys()
        if missing:
            raise ValueError(f"Missing timing markers {missing}: {path}")
        sample = {key: names[name].dur / 1000 for key, name in MARKERS.items()}
        if host_phases:
            required = {"host_orch_us", "graph_definitions_us", "scheduler_state_us"}
            if result["runtime"] == "host_build_graph":
                required.add("scheduler_calls_us")
                if result["variant"] == "graph":
                    required.add("native_nodes_us")
            for key, name in HOST_PHASES.items():
                if key in required and name not in names:
                    raise ValueError(f"Missing diagnostic marker {name}: {path}")
                sample[key] = names[name].dur / 1000 if name in names else None
        sample.update(round=record["round"], warmup=record["warmup"], api_total_us=record["api_wall_ns"] / 1000)
        samples.append(sample)
    measured = [sample for sample in samples if not sample["warmup"]]
    if not measured:
        raise ValueError(f"No measured rounds: {path}")
    summary = {key: result[key] for key in ("workload", "runtime", "scheduler_mode", "variant", "layers", "device")}
    summary.update(source=str(path), measured_rounds=len(measured), warmup_rounds=len(samples) - len(measured))
    for key in (*MARKERS, "api_total_us", *(HOST_PHASES if host_phases else ())):
        values = [sample[key] for sample in measured if sample[key] is not None]
        summary.update(
            {
                f"{key}_{stat}": value
                for stat, value in (
                    ("mean", statistics.mean(values) if values else None),
                    ("median", statistics.median(values) if values else None),
                    ("min", min(values) if values else None),
                )
            }
        )
    return summary, {"source": str(path), "samples": samples}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--host-phases", action="store_true", help="Read the separate instrumented diagnostic")
    args = parser.parse_args()
    summaries, samples = [], []
    for path in sorted(args.input.glob("*/result.json")):
        summary, raw = read_case(path, args.host_phases)
        summaries.append(summary)
        samples.append(raw)
    if not summaries:
        parser.error("No completed cases")
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "timing-samples.json").write_text(json.dumps(samples, indent=2) + "\n")
    with (args.output / "timing-summary.csv").open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(summaries[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(summaries)
    print("| Runtime | Variant | Layers | AICore µs | Device wall µs | Host bind µs | API total µs |")
    print("| --- | --- | ---: | ---: | ---: | ---: | ---: |")
    for row in summaries:
        numbers = " | ".join(
            f"{row[key + '_mean']:.3f}"
            for key in (
                "aicore_us",
                "device_wall_us",
                "host_bind_us",
                "api_total_us",
            )
        )
        print(f"| {row['runtime']} | {row['variant']} | {row['layers']} | {numbers} |")


if __name__ == "__main__":
    main()

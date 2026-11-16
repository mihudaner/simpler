# PyPTO Graph scaling: 1, 10 and 100 repeated sublayers

This benchmark compiles Python PyPTO programs and executes their generated Host
orchestration through `CompiledProgram.chip_callable` and `simpler.Worker`.
It compares `host_build_graph` (mode 1) and `percounter` (mode 5) from the same
runtime checkout. It does not replay a captured task list.

See the [Chinese progress and measurement report](../../../docs/zh-cn/investigations/2026-11-16-pypto-graph-scaling.md)
and [recorded smoke evidence](evidence/smoke-summary.json). The first simple-chain performance matrix is available in the report and
[evidence/simple-matrix-r1](evidence/simple-matrix-r1). SWA Graph on HBG at 1/10/100 layers is recorded in [evidence/swa-host-phases-r1](evidence/swa-host-phases-r1).

Current scope: preserve the ordinary results already collected; run **Graph only**
for subsequent HBG/Percounter comparisons. The separate Host phase diagnostic is
in [evidence/host-phases-graph-r2](evidence/host-phases-graph-r2).

## Files

| File | Purpose |
| ---- | ------- |
| `workloads/simple_chain.py` | Add successive weight bands to one accumulator; exact reference is N(N+1)/2. |
| `workloads/swa.py` | Specialize the DS4.1 SWA orchestration for 72 tokens using Lib compute kernels; pass hidden and mix between layers. |
| `workloads/swa_validation.py` | Check every layer against Lib CPU golden, untouched regions, and exact repeatability. |
| `run.py` | Compile, select the runtime, reset inputs, run, check outputs and record API wall time. |
| `run_graph_matrix.py` | Run Graph at 1/10/100 layers on selected backends, serially inside one allocation. |
| `summarize.py` | Validate timing records and generate per-round JSON and summary CSV. |

Each Graph arm calls one decorated sublayer N times inside one PyPTO orchestration.
The original ordinary arm calls the same computation inline. SWA shares projection weights
but uses separate layer cache bands and different normalization weights. This is
a scaling fixture, not a full DS4.1 model. The SWA Graph specializes temporary
sizes and task counts for 72 live tokens, 37 cache pages per layer and 32 AIC / 64 AIV.
It uses the Lib compute kernels without modifying their arithmetic. Arbitrary
dynamic sizes are outside this fixture's scope.

SWA HBG passed 105 runs. The first run per size checks each layer's actual input
against the independent Lib CPU reference (111 layers total); the remaining runs
compare every mutable output byte with that validated result. Hidden, mix, cache,
scale and untouched regions are checked outside timing. The original single-layer
Lib entry also passes its golden check on HBG. SWA Percounter has not been run.

## Usage

Use a project-local Python environment with this checkout's installed Simpler,
a compatible PyPTO compiler and its dependencies. Build both A5 runtime variants
against `pto_isa.pin`. For SWA, set `PYPTO_LIB_ROOT` to the PyPTO-Lib checkout.
All commands below run from the runtime repository root.

Compile before reserving a device:

```bash
python tests/fdwic/dsv41_graph_scaling/run.py --compile-only \
  --workload simple_chain --variant graph --layers 10 \
  --build outputs/graph-scaling/build/simple-graph
```

Run one diagnostic inside an allocated device job; activate that environment
inside the job as required by the local setup:

```bash
task-submit --device auto --device-num 1 --timeout 600 --max-time 600 \
  --run '.claude/skills/onboard-arch-precheck/check.sh a5 && \
    python tests/fdwic/dsv41_graph_scaling/run.py \
      --workload simple_chain --variant graph --runtime host_build_graph \
      --layers 10 --build outputs/graph-scaling/build/simple-graph \
      --device "$TASK_DEVICE" --rounds 1 --warmup 0 --diagnostic \
      --output outputs/graph-scaling/check-hbg-graph-10'
```

Use `--runtime percounter` for the other backend. Use a new output path for every
run. Diagnostic captures and performance runs are separate: diagnostic wall time
includes capture overhead and must not be used as a performance result. A final
comparison must hold one allocation for the whole sequential matrix.

For the current Graph-only matrix, after compiling the Graph artifact:

```bash
task-submit --device auto --device-num 1 --timeout 900 --max-time 900 \
  --run '.claude/skills/onboard-arch-precheck/check.sh a5 && \
    python tests/fdwic/dsv41_graph_scaling/run_graph_matrix.py \
      --build outputs/graph-scaling/build/simple-graph \
      --output outputs/graph-scaling/graph-matrix-new \
      --device "$TASK_DEVICE"'
```

Add `--host-phases` to run the **instrumented diagnostic**, after rebuilding the
Host runtimes with the current timing patch. Summarize that run with the same flag:

```bash
python tests/fdwic/dsv41_graph_scaling/summarize.py \
  outputs/graph-scaling/graph-phases-new --host-phases \
  --output outputs/graph-scaling/graph-phases-new/summary
```

`graph_definitions` includes `native_nodes`, and `scheduler_state` includes
`scheduler_calls`; do not add parent and child durations. Missing HBG-specific
spans on Percounter are not zero-time measurements. The phase capture includes
instrumentation overhead and must remain separate from the baseline performance
matrix. The matrix driver was executed for the SWA HBG capture; the earlier simple-chain
capture used the equivalent six individual CLI invocations described in the report.

The runner verifies the installed SDK/extension revision against this worktree
and checks the actual scheduler mode after each invocation. PyPTO's original
runtime-submodule check is then bypassed explicitly for this separate-worktree
composition. This compiler/runtime combination requires functional validation;
passing the revision guard alone is not sufficient.

For SWA, compile with `--workload swa` and run the matrix with
`--workload swa --runtimes host_build_graph --host-phases`. The same compiled
artifact accepts 1/10/100 layers at runtime. Detailed commands, specialization
boundaries, golden tolerances and results are in the Chinese report. The full
Host bind includes the selected Host subphases; API total also includes device
execution, completion waiting and call overhead. Neither is a sum of the displayed
columns.

# Run Pipeline and the KernelLaunch Stream

`Worker.run` and `ChipWorker.run` do not simply call `rtKernelLaunch` and
return. A run is prepared on the host, launched on the device, and finalized on
the host again; the run pipeline exists to overlap the first part of
one run with the device work of another.

That split is often mistaken for a duplicate of the CANN stream. This page
states what the stream provides, what it cannot provide for a run, and which
parts of the pipeline are current behavior versus target direction.

## What the stream provides

`rtKernelLaunch` submits a device operation to a stream. A stream is an ordered
queue, so operations submitted to one stream execute in submission order.
Submission itself is asynchronous: `launch_execution` enqueues the run's device
work and returns without waiting for the device to finish it. Completion is
observed later through the run's stream pair and the completion/finalize path.

## What the stream does not provide

### It orders operations, not the state they read

`rtKernelLaunch` copies its argument struct; it does not snapshot the memory
that struct points at. A run's device segment reads a `Runtime` image, graph
definitions, task arguments, staging and DFX regions that live in device
memory. The host writes some of those regions while preparing a run. If the
next run prepared into the same bytes, the device could still be reading the
previous run's content.

The resource contract classifies storage by its data flow and ownership:

- `DELIVERED` regions carry this run's own content and need independent copies
  for in-flight runs, selected by the run's lease slot.
- `SCRATCH` regions are initialized once and reused by serialized device work.
- `POOLED_SCRATCH` is a GM heap leased from the platform's `ScratchPool`.
  Ordered runs can share a generation; growth creates a new generation while
  existing runs retain the old one until their leases end. Under allocation
  pressure, an idle current generation can be withdrawn and reclaimed before
  the single retry; a generation with a live lease remains protected.
- `REPORTED` storage holds device-written results for host observation. The
  result pool keys ownership by run epoch; no runtime contract declares this
  resource class yet.
- `EXEC_HANDLE` names an execution stream, independent of the pipeline slot.

HBG Program mode pools its GM heap and delivers an independent runtime image
per run. The host relocates pointers using the heap's address without writing
its contents. HBG Kernel mode instead retains a delivered heap per run, so
captured graphs keep their backing. TMR declares its heap, shared memory and
runtime image as scratch and delivers per-run task arguments. Resource sets
are granted on demand; the declared depth is not a preallocation count.
Prepared runs retain only their selected, committed regions. Heap, shared
memory and runtime image have independent owners even when their bank number
is the same; retaining one does not force replacement of the others.

### It has no resource pool or admission counter

A stream's queue can accept many submissions, but the per-run device resources
are finite. When no slot's resource set is available, something must block the
caller before it prepares into a slot that is still in use. That blocking is
the run pipeline's admission; the selector is the run-resource lease
(`{slot_id, generation}`). The stream cannot supply either because it does not
know those buffers exist.

### A run has a host head and a host tail

A run is not only a device segment. It has:

1. a host head: resolve arguments, acquire resources, build or stage the
   runtime image, and publish the launch state;
2. a device segment: the AICPU/AICore work submitted on the stream pair;
3. a host tail: observe completion, validate results, copy back outputs, drain
   DFX, release the runtime image and return the resource lease.

A stream has no host completion callback. The host state machine that spans
these three parts is real work, and the number of simultaneously live states is
the pipeline depth. A complete run also needs a place to keep its host-owned
state while the previous run's device segment is still executing.

### One run uses two streams that cannot be merged

A run submits on an AICPU stream and an AICore stream. The AICPU Run kernel
spins in the handshake waiting for the AICore workers to report. If both were
serialized onto one stream, the AICore submission would sit behind a spin that
can never end. The two streams therefore stay distinct and have no mutual
ordering. Queued cross-run event waits order a successor behind its predecessor
on both execution roles; sharing scratch requires that device order.

## What overlaps today

The current onboard program pipeline overlaps **host preparation** with device
execution. At a granted depth of two, run N can be executing while run N+1 is
prepared; run N+2 blocks before its host callback until an admission slot is
free. Whole-run FIFO admission and queued device waits keep the device segments
ordered even when several submitted runs await host finalization.

The op-execute watchdog is not a reason to avoid queueing. It counts execution
time, not time spent waiting behind another operation: on a2a3, three two-second
operations queued on one stream under a three-second budget all completed, while
a single six-second operation was reaped with `507018`.

## Why the common depth is two

A run occupies the whole device — a run is never narrower than the device — so
adding submission depth does not add device parallelism. The resource that can
be idle is the host: while run N executes, the host could be preparing run N+1.
One executing run plus one prepared run covers that overlap. A third slot buys
no additional host preparation parallelism and costs another copy of every
`DELIVERED` resource, though it can decouple submission from host finalization.

Depth is a **grant**, not a global constant. A2/A3 and A5 Program contracts
publish `UINT32_MAX` as their resource-set ceiling; the context selects its
actual grant. Kernel contracts retain their runtime-specific ceilings. The
contract does not itself promise concurrent device execution.

## Target direction, not current behavior

The following is the direction from the [run pipeline design
discussion](https://github.com/hw-native-sys/simpler/issues/1853) and the
interface review recorded on
[#2223](https://github.com/hw-native-sys/simpler/issues/2223); it is not a
description of the current implementation.

- Unify device submission across Program and Kernel modes on a
  `kernel_launch`-style layer, while preserving Program mode's concurrent host
  orchestration.
- Order simpler-owned uploads, clears and rebuilds—not just kernels—and keep
  the caller-stream predecessor/successor relationships explicit. Accepting a
  request into a host queue is not the same as submitting it to the caller's
  stream.

Device execution parallelism, host preparation concurrency and submission depth
are separate quantities. A run occupying the whole device does not imply a
two-slot lifetime limit; removing that limit also does not make the RTS queue or
device memory unbounded.

## Related

- [task-flow.md](task-flow.md) — pipeline resource leases and whole-run FIFO
  admission in the current execution leaf.
- [chip-level-arch.md](chip-level-arch.md) — the host/AICPU/AICore split and
  the Layer 1/2 `prepare -> launch -> wait -> finalize` lifecycle.
- [#1853](https://github.com/hw-native-sys/simpler/issues/1853) — what the
  pipeline does not overlap and the open design questions.
- [#1717](https://github.com/hw-native-sys/simpler/issues/1717) — intra-run
  launch/orchestration overlap.

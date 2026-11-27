#!/usr/bin/env bash
# Copyright (c) PyPTO Contributors.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.
# -----------------------------------------------------------------------------------------------------------
set -euo pipefail
[[ $# == 1 ]] || { echo "Usage (from source checkout): pack-a6.sh NEW_OUTPUT_DIR" >&2; exit 2; }
out=$(realpath -m -- "$1")
here=$(dirname "$(realpath -- "$0")")
repo=$(git rev-parse --show-toplevel)
cd "$repo"
: "${ASCEND_HOME_PATH:?load the CANN 9.3.0 environment}"
[[ -x .venv/bin/python && ! -e $out ]] || { echo 'Need .venv and a new output directory' >&2; exit 2; }
pin=$(cat pto_isa.pin)
[[ $(git -C build/pto-isa rev-parse HEAD) == "$pin" ]]
sha=$(git rev-parse HEAD)
suite=tests/fdwic/a6_dsv41_scheduler
mkdir -p "$out"
pkg=$out/007-a6-calendar
mkdir -p "$pkg/$suite" "$pkg/lib/a6/dispatcher"
# Keep source locations useful in DFX without embedding the build host's checkout path.
export CFLAGS="${CFLAGS:-} -ffile-prefix-map=$repo=."
export CXXFLAGS="${CXXFLAGS:-} -ffile-prefix-map=$repo=."
export CCC_OVERRIDE_OPTIONS="+-ffile-prefix-map=$repo=."
.venv/bin/python simpler_setup/build_runtimes.py --platforms a6 \
    --lib-dir "$out/lib" --cache-dir "$out/cache" \
    --runtime host_build_graph --runtime percounter --profiling-dfx 1 \
    --profiling-orch 0 --profiling-sched 0 --profiling-tensormap 0
install -m755 "$out/lib/a6/dispatcher/libsimpler_aicpu_dispatcher.so" "$pkg/lib/a6/dispatcher/"
for mode in host_build_graph percounter; do
    mkdir -p "$pkg/lib/a6/onboard/$mode"
    for file in libhost_runtime.so libaicpu_kernel.so aicore_kernel.o; do
        cp "$out/lib/a6/onboard/$mode/$file" "$pkg/lib/a6/onboard/$mode/"
    done
done
cases=(engram swa c1a_reuse c1a_reindex c2a_full)
for name in "${cases[@]}"; do
    flags=(--stage 007 --kernel-set cpp)
    if [[ $name != engram ]]; then flags+=(--five-block-t0); fi
    prepared=$out/prepared/$name
    .venv/bin/python -I "$suite/prepare.py" build --platform a6 --case "$name" "${flags[@]}" \
        --runtime both --pto-isa build/pto-isa --build-dir "$prepared"
    for mode in host_build_graph percounter; do
        src=$prepared
        if [[ $mode == percounter ]]; then src=$src/percounter; fi
        dst=$pkg/cases/$name/$mode
        mkdir -p "$dst/host"
        cp -a "$src/bundle" "$src/build.json" "$dst"
        install -m755 "$src/host/native-runner" "$dst/host/"
    done
    # The two modes use exactly the same converted plan, input buffers, and references.
    diff -qr --exclude=callable.bin "$pkg/cases/$name/host_build_graph/bundle" "$pkg/cases/$name/percounter/bundle"
done
cp "$suite/run.py" "$pkg/$suite/"
install -m755 "$here/run-a6.sh" "$pkg/"
cp "$here/README.zh-CN.md" "$pkg/"
printf 'simpler=%s\npto_isa=%s\nplatform=a6\nDFX=1\ncases=%s\n' "$sha" "$pin" "${cases[*]}" > "$pkg/BUILD"
(cd "$pkg" && find . -type f ! -name SHA256SUMS -print0 | LC_ALL=C sort -z | xargs -0 sha256sum > SHA256SUMS)
bash "$pkg/run-a6.sh" --verify
archive=007-a6-calendar-${#cases[@]}models-${sha:0:12}.tar.xz
tar -C "$out" --sort=name --mtime="@$(git show -s --format=%ct HEAD)" --owner=0 --group=0 --numeric-owner \
    -cf - 007-a6-calendar | xz -T4 -3 > "$out/$archive"
(cd "$out" && sha256sum "$archive" > "$archive.sha256")
printf 'Archive: %s/%s\n' "$out" "$archive"

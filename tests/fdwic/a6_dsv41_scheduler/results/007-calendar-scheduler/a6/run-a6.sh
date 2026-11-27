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
pkg=$(dirname "$(realpath -- "$0")")
if [[ $# == 1 && $1 == --verify ]]; then
    (cd "$pkg" && sha256sum -c --status SHA256SUMS)
    cat "$pkg/BUILD"
    exit 0
fi
if [[ $# -lt 2 || $# -gt 6 ]]; then
    echo "Usage: run-a6.sh DEVICE NEW_OUTPUT [engram|swa|c1a_reuse|c1a_reindex|c2a_full|all] [host_build_graph|percounter|both] [warmup] [rounds]" >&2
    exit 2
fi
device=$1
out=$(realpath -m -- "$2")
: "${ASCEND_HOME_PATH:?load the CANN 9.3.0 environment}"
[[ $device =~ ^[0-9]+$ && ${TASK_DEVICE:-$device} == "$device" && ! -e $out ]] || {
    echo 'Need one allocated logical device and a new output directory' >&2; exit 2;
}
case ${3:-all} in
    all) cases=(engram swa c1a_reuse c1a_reindex c2a_full) ;;
    engram|swa|c1a_reuse|c1a_reindex|c2a_full) cases=("$3") ;;
    *) echo 'Unknown case' >&2; exit 2 ;;
esac
case ${4:-both} in
    both) modes=(host_build_graph percounter) ;; host_build_graph|percounter) modes=("$4") ;; *) exit 2 ;;
esac
warmup=${5:-0}
rounds=${6:-1}
[[ $warmup =~ ^[0-9]+$ && $rounds =~ ^[1-9][0-9]*$ ]] || { echo 'Invalid round counts' >&2; exit 2; }
"$pkg/run-a6.sh" --verify
mkdir -p "$out"
cp "$pkg/BUILD" "$out/"
# Query the device assigned to this run through the same ACL used by the replay.
python3 -I - "$device" <<'PY' | tee "$out/device.txt"
import ctypes
import sys
acl = ctypes.CDLL("libascendcl.so")
device = int(sys.argv[1])
if acl.aclInit(None):
    sys.exit("ACL initialization failed")
if acl.aclrtSetDevice(device):
    acl.aclFinalize()
    sys.exit("ACL could not open the allocated device")
acl.aclrtGetSocName.restype = ctypes.c_char_p
soc = acl.aclrtGetSocName() or b""
print("device={} soc={}".format(device, soc.decode()), flush=True)
close_rc = acl.aclrtResetDevice(device)
finalize_rc = acl.aclFinalize()
if not soc.startswith(b"Ascend960"):
    sys.exit("This package requires an Ascend960 (A6)")
if close_rc or finalize_rc:
    sys.exit("ACL could not close the precheck")
PY
failures=0
printf 'case\truntime\tdevice\twarmup\trounds\texit\n' > "$out/status.tsv"
for name in "${cases[@]}"; do
    for mode in "${modes[@]}"; do
        dest=$out/$name/$mode
        logs=$out/ascend/$name/$mode
        mkdir -p "$logs"
        rc=0
        ASCEND_PROCESS_LOG_PATH="$logs" python3 -I "$pkg/tests/fdwic/a6_dsv41_scheduler/run.py" \
            --build-dir "$pkg/cases/$name/$mode" --runtime-lib "$pkg/lib/a6/onboard" --runtime "$mode" \
            --output "$dest" --device "$device" --level 0 --warmup "$warmup" --rounds "$rounds" || rc=$?
        printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$name" "$mode" "$device" "$warmup" "$rounds" "$rc" >> "$out/status.tsv"
        if (( rc != 0 )); then failures=1; fi
    done
done
cat "$out/status.tsv"
exit "$failures"

#!/usr/bin/env python3
# Copyright (c) PyPTO Contributors.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.
# -----------------------------------------------------------------------------------------------------------
"""Verify the captured A5 reference package and the A6 plan without CANN or a device."""

import importlib.util
import json
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from compile_kernels import REPO, SOURCES, SUITE, swa_tasks
from prepare_plan import build_converter, check_conversion, convert_plan, read_records, validate_source

SPEC = importlib.util.spec_from_file_location(
    "standalone_swa_prepare", Path(__file__).resolve().with_name("prepare.py")
)
assert SPEC and SPEC.loader
PREPARE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREPARE)


class FixtureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temporary.cleanup)
        cls.directory = Path(temporary.name)
        cls.source = cls.directory / "source"
        cls.metadata = PREPARE.unpack_fixture(cls.source)
        cls.converter = cls.directory / "adapt-plan"
        cls.tool = cls.directory / "record-tool"
        build_converter("c++", cls.converter)
        subprocess.run(
            [
                "c++",
                "-std=c++17",
                "-O2",
                f"-I{REPO / 'src/common'}",
                f"-I{REPO / 'src/common/task_interface'}",
                SUITE / "production/record_tool.cpp",
                "-o",
                cls.tool,
            ],
            check=True,
        )

    def test_real_converter_preserves_payload_flags_and_dependencies(self):
        original = self.source / "plan-rank0.bin"
        converted = self.directory / "a6.bin"
        self.assertEqual(convert_plan(self.tool, self.converter, original, converted), 660)
        before, after = (read_records(self.tool, path) for path in (original, converted))
        tasks = swa_tasks()
        self.assertEqual(len(tasks), 15)
        self.assertEqual(sum(blocks * sum(i >= 0 for i in slots) for blocks, slots in tasks.values()), 632)
        self.assertEqual([r["id"] for r, s in zip(before, after, strict=True) if r != s], [12, 22, 30, 33, 34])
        fused = next(r for r in after if r["op"] == 2 and r["id"] == 34)
        self.assertEqual((fused["blocks"], fused["kernels"]), (54, [24, 25, -1]))
        fused["sync"] ^= 1
        with self.assertRaisesRegex(ValueError, "changed fields"):
            check_conversion(before, after)
        next(r for r in before if r["op"] == 2 and r["id"] == 34)["id"] = 35
        with self.assertRaisesRegex(ValueError, "pinned SWA task table"):
            validate_source(before)

    def test_snapshot_covers_all_writable_device_tensors(self):
        case = json.loads((self.source / "case.json").read_text())
        self.assertEqual(case["source"], self.metadata["source"])
        self.assertFalse((self.source / "rank1.txt").exists())
        self.assertEqual((self.source / "slice.txt").read_text().split(), ["8", "34"])
        self.assertEqual((self.source / "snapshot.txt").read_text().split(), ["rank0"])
        lines = (self.source / "rank0.txt").read_text().splitlines()
        self.assertEqual(lines[:2], ["DSV41_NATIVE_V1", "1 0"])
        base = json.loads((SOURCES / "manifest.json").read_text())["entry_signature"]
        signature = base + [3] * len(case["ranks"][0]["boundary_buffers"])
        self.assertEqual(len(signature), int(lines[2]))
        expected = set()
        for index, (kind, row) in enumerate(zip(signature, lines[3 : 3 + len(signature)], strict=True)):
            fields = shlex.split(row)
            size = int(fields[2])
            actual = (self.source / fields[-1]).stat().st_size
            self.assertTrue(actual > 0 and (actual == size or fields[-2] == "REPEAT" and size % actual == 0))
            if kind in (2, 3) and fields[0] == "DEVICE":
                reference = self.source / "reference" / f"{index}.bin"
                self.assertIn(reference.stat().st_size, (1, size))
                expected.add(reference)
        self.assertEqual(expected, set((self.source / "reference").glob("*.bin")))
        self.assertEqual(len(expected), self.metadata["reference_count"])

    def test_corrupt_snapshot_is_rejected(self):
        damaged = self.directory / "damaged"
        damaged.mkdir()
        (damaged / "fixture.json").write_bytes((PREPARE.FIXTURE / "fixture.json").read_bytes())
        (damaged / PREPARE.ARCHIVE).write_bytes((PREPARE.FIXTURE / PREPARE.ARCHIVE).read_bytes()[:-1])
        with self.assertRaisesRegex(ValueError, "checksum differs"):
            PREPARE.unpack_fixture(self.directory / "rejected", damaged)


if __name__ == "__main__":
    unittest.main()

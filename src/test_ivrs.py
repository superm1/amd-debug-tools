#!/usr/bin/python3
# SPDX-License-Identifier: MIT

"""Unit tests for the IVRS parser implementation."""

import struct
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

import amd_debug.ivrs as ivrs_mod
from amd_debug.ivrs import IvhdDeviceEntry, IvhdEntry, IvmdMapping, IvrsParser
from amd_debug.ivrs_fixtures import (
    _pack_ivmd_all_devices,
    _pack_ivmd_exclusion_range,
    _pack_ivmd_single_device,
    make_ivrs_table,
)


class TestIvrsParser(unittest.TestCase):

    def test_rejects_too_small_table(self):
        with self.assertRaises(ValueError):
            IvrsParser(b"\x00" * 47)

    def test_parses_dma_remap_from_ivinfo(self):
        parser = IvrsParser(make_ivrs_table(dma_remap=True))
        self.assertTrue(parser.has_dma_remap)
        self.assertEqual(parser.virt_info & 0x2, 0x2)

    def test_parses_ivhd_type_10_header(self):
        parser = IvrsParser(make_ivrs_table(ivhd_type=0x10))
        self.assertEqual(len(parser.ivhd_entries), 1)
        self.assertEqual(parser.ivhd_entries[0].subtable_type, 0x10)
        self.assertEqual(parser.ivhd_entries[0].header_size, 24)

    def test_parses_ivhd_type_11_header(self):
        parser = IvrsParser(make_ivrs_table(ivhd_type=0x11))
        self.assertEqual(len(parser.ivhd_entries), 1)
        self.assertEqual(parser.ivhd_entries[0].subtable_type, 0x11)
        self.assertEqual(parser.ivhd_entries[0].header_size, 40)

    def test_parses_ivhd_type_40_instead_of_skipping(self):
        parser = IvrsParser(make_ivrs_table(ivhd_type=0x40))
        self.assertEqual(len(parser.ivhd_entries), 1)
        self.assertEqual(parser.ivhd_entries[0].subtable_type, 0x40)
        self.assertEqual(parser.ivhd_entries[0].header_size, 40)

    def test_finds_msft0201_device_in_f0_entry(self):
        parser = IvrsParser(make_ivrs_table(msft0201_devid=0x60, ivhd_type=0x40))
        self.assertTrue(parser.has_msft0201_in_acpi())
        self.assertEqual(parser.find_msft0201_device_id(), 0x60)

    def test_handles_broken_f0_uid_length_without_exception(self):
        table = bytearray(make_ivrs_table(msft0201_devid=0x60, ivhd_type=0x40))
        # F0 entry starts after IVRS header (48), IVHD 40-byte header and two 4-byte range entries.
        f0_offset = 48 + 40 + 8
        uid_len_offset = f0_offset + 21
        table[uid_len_offset] = 0xFF

        parser = IvrsParser(bytes(table))
        self.assertIsNone(parser.find_msft0201_device_id())

    def test_ivmd_type_20_requires_unity_flag(self):
        ivmd = bytearray(_pack_ivmd_all_devices(memory_length=0x100000))
        ivmd[1] = 0x00  # clear all flags

        parser = IvrsParser(
            make_ivrs_table(msft0201_devid=0x60, ivmd_entries=[bytes(ivmd)])
        )
        self.assertFalse(parser.has_valid_msft0201_mapping(0x60))

    def test_ivmd_type_21_requires_matching_device_id(self):
        parser = IvrsParser(
            make_ivrs_table(
                msft0201_devid=0x60,
                ivmd_entries=[_pack_ivmd_single_device(0x70, memory_length=0x100000)],
            )
        )
        self.assertFalse(parser.has_valid_msft0201_mapping(0x60))

    def test_ivmd_type_22_uses_inclusive_device_range(self):
        parser = IvrsParser(
            make_ivrs_table(
                msft0201_devid=0x60,
                ivmd_entries=[
                    _pack_ivmd_exclusion_range(
                        device_id=0x50,
                        end_device_id=0x70,
                        memory_length=0x100000,
                    )
                ],
            )
        )
        self.assertTrue(parser.has_valid_msft0201_mapping(0x60))
        self.assertFalse(parser.has_valid_msft0201_mapping(0x80))

    def test_none_msft_device_id_never_matches_mapping(self):
        parser = IvrsParser(
            make_ivrs_table(
                ivmd_entries=[_pack_ivmd_all_devices(memory_length=0x100000)]
            )
        )
        self.assertFalse(parser.has_valid_msft0201_mapping(None))

    def test_malformed_subtable_length_stops_parsing_cleanly(self):
        table = bytearray(make_ivrs_table(msft0201_devid=0x60, ivhd_type=0x11))
        # Corrupt first IVDB length so it extends past table end.
        struct.pack_into("<H", table, 48 + 2, 0xFFFF)

        parser = IvrsParser(bytes(table))
        self.assertEqual(parser.subtables, [])

    def test_get_entry_size_rules(self):
        self.assertEqual(IvhdDeviceEntry.get_entry_size(bytes([0x02]), 0), 4)
        self.assertEqual(IvhdDeviceEntry.get_entry_size(bytes([0x40]), 0), 8)

        f0 = bytearray(22)
        f0[0] = 0xF0
        f0[21] = 5
        self.assertEqual(IvhdDeviceEntry.get_entry_size(bytes(f0 + b"abcde"), 0), 27)

        self.assertIsNone(
            IvhdDeviceEntry.get_entry_size(bytes([0x90]) + b"\x00" * 40, 0)
        )

    def test_get_entry_size_handles_short_f0_header(self):
        self.assertIsNone(
            IvhdDeviceEntry.get_entry_size(bytes([0xF0]) + b"\x00" * 10, 0)
        )

    def test_ivhd_entry_rejects_unknown_type(self):
        data = bytearray(24)
        data[0] = 0x12
        struct.pack_into("<H", data, 2, 24)
        with self.assertRaises(ValueError):
            IvhdEntry(bytes(data), 0)

    def test_ivhd_entry_rejects_short_type_11_header(self):
        data = bytearray(24)
        data[0] = 0x11
        struct.pack_into("<H", data, 2, 24)
        with self.assertRaises(ValueError):
            IvhdEntry(bytes(data), 0)

    def test_ivhd_entry_breaks_when_fixed_entry_overruns_end(self):
        # 24-byte type 10 header plus a single 4-byte device-entry payload that starts
        # with a type in the 40h-7Fh range (implies 8-byte fixed length).
        data = bytearray(24 + 4)
        data[0] = 0x10
        struct.pack_into("<H", data, 2, len(data))
        data[24] = 0x40
        ivhd = IvhdEntry(bytes(data), 0)
        self.assertEqual(ivhd.device_entries, [])

    def test_ivhd_device_ids_property(self):
        parser = IvrsParser(
            make_ivrs_table(extra_devices=[0x0010, 0x0020], ivhd_type=0x10)
        )
        self.assertEqual(
            parser.ivhd_entries[0].device_ids, {0x0003, 0xFFFE, 0x0010, 0x0020}
        )

    def test_ivhd_device_length_property_for_fixed_entry(self):
        entry = IvhdDeviceEntry(bytes([0x02, 0x34, 0x12, 0x00]), 0, 4)
        self.assertEqual(entry.length, 4)

    def test_ivhd_device_hid_none_when_hid_field_truncated(self):
        # Explicitly pass entry_length to avoid automatic size inference.
        entry = IvhdDeviceEntry(bytes([0xF0, 0x34, 0x12, 0x00, 0x4D]), 0, 22)
        self.assertIsNone(entry.hid)

    def test_ivhd_device_hid_none_when_entry_length_cannot_be_inferred(self):
        entry = IvhdDeviceEntry(bytes([0xF0, 0x34, 0x12, 0x00, 0x4D]), 0)
        self.assertIsNone(entry.hid)
        self.assertEqual(entry.length, 4)

    def test_ivmd_rejects_too_short_subtable(self):
        ivmd = bytearray(_pack_ivmd_single_device(0x60, 0x1000))
        struct.pack_into("<H", ivmd, 2, 16)
        with self.assertRaises(ValueError):
            IvmdMapping(bytes(ivmd), 0)

    def test_ivmd_helpers_and_properties(self):
        parser = IvrsParser(
            make_ivrs_table(
                msft0201_devid=0x60,
                ivmd_entries=[_pack_ivmd_single_device(0x60, memory_length=0x1000)],
            )
        )
        ivmd = parser.ivmd_mappings[0]
        self.assertEqual(ivmd.subtable_type, 0x21)
        self.assertTrue(ivmd.is_unity_map)
        self.assertFalse(ivmd.is_exclusion_range)
        self.assertTrue(ivmd.has_valid_mapping)
        self.assertFalse(ivmd.covers_device_id(0x70))

    def test_ivmd_type_20_uses_has_valid_mapping_for_cover(self):
        ivmd = bytearray(_pack_ivmd_all_devices(memory_length=0))
        parser = IvrsParser(make_ivrs_table(ivmd_entries=[bytes(ivmd)]))
        self.assertFalse(parser.ivmd_mappings[0].covers_device(0x1234))

    def test_ivmd_covers_device_id_rejects_zero_length_mapping(self):
        ivmd = bytearray(_pack_ivmd_single_device(0x60, memory_length=0))
        parser = IvrsParser(make_ivrs_table(ivmd_entries=[bytes(ivmd)]))
        self.assertFalse(parser.ivmd_mappings[0].covers_device_id(0x60))

    def test_subtable_raw_slice_property(self):
        parser = IvrsParser(make_ivrs_table(msft0201_devid=0x60, ivhd_type=0x11))
        subtable = parser.subtables[0]
        self.assertEqual(
            subtable.raw,
            parser.data[subtable.offset : subtable.offset + subtable.length],
        )

    def test_parse_subtables_breaks_on_zero_and_too_small_length(self):
        # length == 0 at first subtable offset
        zero_len = bytearray(make_ivrs_table())
        struct.pack_into("<H", zero_len, 48 + 2, 0)
        self.assertEqual(IvrsParser(bytes(zero_len)).subtables, [])

        # length < 4 at first subtable offset
        tiny_len = bytearray(make_ivrs_table())
        struct.pack_into("<H", tiny_len, 48 + 2, 3)
        self.assertEqual(IvrsParser(bytes(tiny_len)).subtables, [])

    def test_parse_subtables_skips_unknown_type(self):
        table = bytearray(make_ivrs_table())
        table[48] = 0x33
        parser = IvrsParser(bytes(table))
        self.assertEqual(parser.subtables, [])

    def test_parse_subtables_handles_malformed_ivhd_and_continues(self):
        table = bytearray(make_ivrs_table())
        # Unknown IVHD-like type with valid length to trigger IvhdEntry ValueError path.
        table[48] = 0x10
        struct.pack_into("<H", table, 48 + 2, 8)
        parser = IvrsParser(bytes(table))
        self.assertEqual(parser.subtables, [])

    def test_subtable_validation_rejects_length_too_small(self):
        bad = bytearray(_pack_ivmd_single_device(0x60, 0x1000))
        struct.pack_into("<H", bad, 2, 3)
        with self.assertRaises(ValueError):
            IvmdMapping(bytes(bad), 0)

    def test_subtable_validation_rejects_out_of_bounds_length(self):
        bad = bytearray(_pack_ivmd_single_device(0x60, 0x1000))
        struct.pack_into("<H", bad, 2, 0x4000)
        with self.assertRaises(ValueError):
            IvmdMapping(bytes(bad), 0)

    def test_main_success_output(self):
        data = make_ivrs_table(
            msft0201_devid=0x60,
            ivmd_entries=[_pack_ivmd_single_device(0x60, memory_length=0x1000)],
        )
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(data)
            path = f.name

        argv = ["ivrs.py", path]
        buf = StringIO()
        try:
            with patch("sys.argv", argv), redirect_stdout(buf):
                rc = ivrs_mod.main()
        finally:
            import os

            os.unlink(path)

        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("IVRS Table Analysis", out)
        self.assertIn("MSFT0201 check", out)

    def test_main_parse_error_output(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"\x00" * 4)
            path = f.name

        argv = ["ivrs.py", path]
        buf = StringIO()
        try:
            with patch("sys.argv", argv), redirect_stdout(buf):
                rc = ivrs_mod.main()
        finally:
            import os

            os.unlink(path)

        out = buf.getvalue()
        self.assertEqual(rc, 1)
        self.assertIn("Error parsing IVRS table", out)

    def test_main_reports_msft_string_without_parsed_f0_entry(self):
        table = bytearray(make_ivrs_table(msft0201_devid=0x60, ivhd_type=0x40))
        f0_offset = 48 + 40 + 8
        table[f0_offset + 21] = 0xFF

        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(bytes(table))
            path = f.name

        argv = ["ivrs.py", path]
        buf = StringIO()
        try:
            with patch("sys.argv", argv), redirect_stdout(buf):
                rc = ivrs_mod.main()
        finally:
            import os

            os.unlink(path)

        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("Not found in IVHD device entries", out)
        self.assertIn("But MSFT0201 HID string found in table", out)

    def test_module_main_invocation_path(self):
        data = make_ivrs_table()
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(data)
            path = f.name

        argv = ["amd_debug.ivrs", path]
        buf = StringIO()
        try:
            with patch("sys.argv", argv), redirect_stdout(buf):
                import runpy

                runpy.run_module("amd_debug.ivrs", run_name="__main__")
        finally:
            import os

            os.unlink(path)


if __name__ == "__main__":
    unittest.main()

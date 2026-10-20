#!/usr/bin/python3
# SPDX-License-Identifier: MIT

"""
This module contains unit tests for the platform detection functions in the
amd-debug-tools package.
"""

import logging
import unittest
from unittest.mock import patch

from amd_debug.cpu import (
    CpuInfo,
    get_cpu_info,
    parse_cpuinfo,
    VENDOR_AMD,
    VENDOR_INTEL,
)

INTEL_CPUINFO = (
    "processor\t: 0\n"
    "vendor_id\t: GenuineIntel\n"
    "cpu family\t: 6\n"
    "model\t\t: 167\n"
    "model name\t: 11th Gen Intel(R) Core(TM) i7-11700 @ 2.50GHz\n"
    "stepping\t: 1\n"
)

AMD_CPUINFO = (
    "processor\t: 0\n"
    "vendor_id\t: AuthenticAMD\n"
    "cpu family\t: 25\n"
    "model\t\t: 33\n"
    "model name\t: AMD Ryzen 7 3700X 8-Core Processor\n"
    "stepping\t: 0\n"
)


class TestParseCpuInfo(unittest.TestCase):
    """Unit tests for the parse_cpuinfo helper"""

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(filename="/dev/null", level=logging.DEBUG)

    def test_parse_intel_cpuinfo(self):
        """Test parsing a full Intel /proc/cpuinfo"""
        info = parse_cpuinfo(INTEL_CPUINFO)
        self.assertEqual(info.vendor, VENDOR_INTEL)
        self.assertEqual(info.family, 6)
        self.assertEqual(info.model, 167)
        self.assertEqual(
            info.model_string, "11th Gen Intel(R) Core(TM) i7-11700 @ 2.50GHz"
        )

    def test_parse_amd_cpuinfo(self):
        """Test parsing a full AMD /proc/cpuinfo"""
        info = parse_cpuinfo(AMD_CPUINFO)
        self.assertEqual(info.vendor, VENDOR_AMD)
        self.assertEqual(info.family, 25)
        self.assertEqual(info.model, 33)
        self.assertEqual(info.model_string, "AMD Ryzen 7 3700X 8-Core Processor")

    def test_parse_empty_cpuinfo(self):
        """Test parsing an empty /proc/cpuinfo"""
        info = parse_cpuinfo("")
        self.assertEqual(info.vendor, "")
        self.assertIsNone(info.family)
        self.assertIsNone(info.model)
        self.assertEqual(info.model_string, "")

    def test_parse_cpuinfo_without_model_name(self):
        """Test parsing a /proc/cpuinfo that has no model name"""
        info = parse_cpuinfo(
            "vendor_id\t: GenuineIntel\ncpu family\t: 6\nmodel\t\t: 167\n"
        )
        self.assertEqual(info.vendor, VENDOR_INTEL)
        self.assertEqual(info.family, 6)
        self.assertEqual(info.model, 167)
        self.assertEqual(info.model_string, "")

    def test_parse_cpuinfo_stops_at_first_processor_block(self):
        """Test that only the first processor block is parsed"""
        contents = INTEL_CPUINFO + (
            "processor\t: 1\n"
            "vendor_id\t: GenuineIntel\n"
            "cpu family\t: 6\n"
            "model\t\t: 190\n"
            "model name\t: Some other CPU\n"
        )
        info = parse_cpuinfo(contents)
        self.assertEqual(info.model, 167)
        self.assertEqual(
            info.model_string, "11th Gen Intel(R) Core(TM) i7-11700 @ 2.50GHz"
        )

    def test_parse_cpuinfo_with_leading_blank_lines(self):
        """Test that leading blank lines don't terminate parsing early"""
        info = parse_cpuinfo("\n\n" + INTEL_CPUINFO)
        self.assertEqual(info.vendor, VENDOR_INTEL)
        self.assertEqual(info.family, 6)
        self.assertEqual(info.model, 167)

    def test_parse_cpuinfo_skips_unrelated_lines(self):
        """Test that unrelated lines in /proc/cpuinfo are ignored"""
        contents = (
            "processor\t: 0\n"
            "bogomips\t: 4992.00\n"
            "flags\t\t: fpu vme de pse\n"
            "vendor_id\t: GenuineIntel\n"
            "cpu family\t: 6\n"
            "model\t\t: 167\n"
            "model name\t: 11th Gen Intel(R) Core(TM) i7-11700 @ 2.50GHz\n"
        )
        info = parse_cpuinfo(contents)
        self.assertEqual(info.vendor, VENDOR_INTEL)
        self.assertEqual(info.family, 6)
        self.assertEqual(info.model, 167)
        self.assertEqual(
            info.model_string, "11th Gen Intel(R) Core(TM) i7-11700 @ 2.50GHz"
        )


class TestCpuInfo(unittest.TestCase):
    """Unit tests for the CpuInfo class"""

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(filename="/dev/null", level=logging.DEBUG)

    def test_is_amd(self):
        """Test that an AMD CPU is detected as AMD"""
        info = CpuInfo(vendor=VENDOR_AMD)
        self.assertTrue(info.is_amd)
        self.assertFalse(info.is_intel)

    def test_is_intel(self):
        """Test that an Intel CPU is detected as Intel"""
        info = CpuInfo(vendor=VENDOR_INTEL)
        self.assertFalse(info.is_amd)
        self.assertTrue(info.is_intel)

    def test_unknown_vendor_is_neither(self):
        """Test that an unknown vendor is neither AMD nor Intel"""
        info = CpuInfo(vendor="SomeOtherVendor")
        self.assertFalse(info.is_amd)
        self.assertFalse(info.is_intel)

    def test_str_uses_model_string(self):
        """Test that the model string is used for the description"""
        info = CpuInfo(
            vendor=VENDOR_INTEL,
            family=6,
            model=167,
            model_string="11th Gen Intel(R) Core(TM) i7-11700 @ 2.50GHz",
        )
        self.assertEqual(str(info), "11th Gen Intel(R) Core(TM) i7-11700 @ 2.50GHz")

    def test_str_falls_back_to_family_and_model(self):
        """Test that the family and model are used without a model string"""
        info = CpuInfo(vendor=VENDOR_INTEL, family=6, model=167)
        self.assertEqual(str(info), "GenuineIntel family 6 model 167")


class TestGetCpuInfo(unittest.TestCase):
    """Unit tests for the get_cpu_info helper"""

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(filename="/dev/null", level=logging.DEBUG)

    @patch("amd_debug.cpu.read_file")
    def test_get_cpu_info_reads_proc_cpuinfo(self, mock_read_file):
        """Test that get_cpu_info reads /proc/cpuinfo"""
        mock_read_file.return_value = INTEL_CPUINFO
        info = get_cpu_info()
        self.assertEqual(info.vendor, VENDOR_INTEL)
        self.assertEqual(info.family, 6)
        self.assertEqual(info.model, 167)
        mock_read_file.assert_called_once_with("/proc/cpuinfo")

    @patch("amd_debug.cpu.read_file")
    def test_get_cpu_info_missing_file(self, mock_read_file):
        """Test get_cpu_info when /proc/cpuinfo can't be read"""
        mock_read_file.side_effect = FileNotFoundError
        info = get_cpu_info()
        self.assertEqual(info.vendor, "")
        self.assertIsNone(info.family)
        self.assertIsNone(info.model)
        self.assertEqual(info.model_string, "")

    @patch("amd_debug.cpu.read_file")
    def test_get_cpu_info_permission_denied(self, mock_read_file):
        """Test get_cpu_info when /proc/cpuinfo can't be read"""
        mock_read_file.side_effect = PermissionError
        info = get_cpu_info()
        self.assertEqual(info.vendor, "")
        self.assertIsNone(info.family)
        self.assertIsNone(info.model)
        self.assertEqual(info.model_string, "")


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/python3
# SPDX-License-Identifier: MIT

"""
This module contains unit tests for the kernel log functions in the amd-debug-tools package.
"""
import logging
import unittest
import sys
import os

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from amd_debug.kernel_log import sscanf_bios_args


class TestKernelLog(unittest.TestCase):
    """Test common functions"""

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(filename="/dev/null", level=logging.DEBUG)

    def test_sscanf_bios_args(self):
        """Test sscanf_bios_args function"""

        # Test case with a valid line
        line = 'ex_trace_args: "format_string", 0x1234, 0x5678'
        expected_output = "format_string"
        result = sscanf_bios_args(line)
        self.assertEqual(result, expected_output)

        # Test case with an invalid line
        line = 'invalid_line: "format_string", 0x1234, 0x5678'
        result = sscanf_bios_args(line)
        self.assertIsNone(result)

        # Test case with a line containing "Unknown"
        line = 'ex_trace_args: "format_string", Unknown, 0x5678'
        expected_output = "format_string"
        result = sscanf_bios_args(line)
        self.assertEqual(result, expected_output)

        # make sure that lines with ex_trace_point are not parsed
        line = 'ex_trace_point: "format_string", 0x1234, 0x5678'
        result = sscanf_bios_args(line)
        self.assertTrue(result)

        # test a real post code line
        line = 'ex_trace_args: "  POST CODE: %X  ACPI TIMER: %X  TIME: %d.%d ms\\n", b0003f33, 83528798, 0, 77, 0, 0'
        expected_output = "POST CODE: B0003F33  ACPI TIMER: 83528798  TIME: 0.77 ms"
        result = sscanf_bios_args(line)
        self.assertEqual(result, expected_output)

        # test a real _REG print
        line = 'ex_trace_args:  "  OEM-ASL-PCIe Address (0x%X)._REG (%d %d)  PCSA = %d\\n", ec303000, 2, 0, 0, 0, 0'
        expected_output = "OEM-ASL-PCIe Address (0xEC303000)._REG (2 0)  PCSA = 0"
        result = sscanf_bios_args(line)
        self.assertEqual(result, expected_output)

        # test case of too may arguments
        line = 'ex_trace_args         :  "  APGE                  = %d\\n", 1, 0, 0, 0, 0, 0'
        expected_output = "APGE                  = 1"
        result = sscanf_bios_args(line)
        self.assertEqual(result, expected_output)

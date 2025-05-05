#!/usr/bin/python3
# SPDX-License-Identifier: MIT

"""
This module contains unit tests for the kernel log functions in the amd-debug-tools package.
"""
from unittest.mock import patch, mock_open

import unittest
import sys
import os

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from amd_debug.kernel import sscanf_bios_args, get_kernel_command_line


class TestKernelLog(unittest.TestCase):
    """Test common functions"""

    @classmethod
    def setUpClass(cls):
        pass  # logging.basicConfig(filename="/dev/null", level=logging.DEBUG)

    def test_get_kernel_command_line(self):
        """Test get_kernel_command_line function"""

        # Test case with a valid kernel command line that is fully filtered
        kernel_cmdline = "quiet splash"
        expected_output = ""
        with patch(
            "builtins.open", new_callable=mock_open, read_data=kernel_cmdline
        ) as _mock_file:
            result = get_kernel_command_line()
            self.assertEqual(result, expected_output)

        # Test case with an empty kernel command line
        kernel_cmdline = ""
        expected_output = ""
        with patch(
            "builtins.open", new_callable=mock_open, read_data=kernel_cmdline
        ) as _mock_file:
            result = get_kernel_command_line()
            self.assertEqual(result, expected_output)

        # Test case with a kernel command line containing special characters
        kernel_cmdline = "quiet splash --debug=1"
        expected_output = "--debug=1"
        with patch(
            "builtins.open", new_callable=mock_open, read_data=kernel_cmdline
        ) as _mock_file:
            result = get_kernel_command_line()
            self.assertEqual(result, expected_output)

        # Test case with a kernel command line containing special characters
        kernel_cmdline = "quiet splash initrd=foo modprobe.blacklist=foo"
        expected_output = "modprobe.blacklist=foo"
        with patch(
            "builtins.open", new_callable=mock_open, read_data=kernel_cmdline
        ) as _mock_file:
            result = get_kernel_command_line()
            self.assertEqual(result, expected_output)

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

        # test case for Dispatch notify
        line = "evmisc-0132 ev_queue_notify_reques: Dispatching Notify on [UBTC] (Device) Value 0x80 (Status Change) Node 00000000851b15c1"
        expected_output = (
            "Dispatching Notify on [UBTC] (Device) Value 0x80 (Status Change)"
        )
        result = sscanf_bios_args(line)
        self.assertEqual(result, expected_output)

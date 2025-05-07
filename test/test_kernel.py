#!/usr/bin/python3
# SPDX-License-Identifier: MIT

"""
This module contains unit tests for the kernel log functions in the amd-debug-tools package.
"""
from unittest.mock import patch, mock_open

import unittest
import sys
import os
import logging

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from amd_debug.kernel import sscanf_bios_args, get_kernel_command_line, DmesgLogger


class TestKernelLog(unittest.TestCase):
    """Test Common kernel scan functions"""

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(filename="/dev/null", level=logging.DEBUG)

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


class TestDmesgLogger(unittest.TestCase):
    """Test Dmesg logger functions"""

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(filename="/dev/null", level=logging.DEBUG)

    def test_dmesg_logger_initialization(self):
        """Test initialization of DmesgLogger"""

        with patch("subprocess.run") as mock_run:
            # Mock the subprocess output for dmesg -h
            mock_run.return_value.stdout = b"--since supported\n"
            mock_run.return_value.returncode = 0

            logger = DmesgLogger()
            self.assertTrue(logger.since_support)
            self.assertEqual(logger.command, ["dmesg", "-t", "-k"])

    def test_dmesg_logger_refresh_head(self):
        """Test _refresh_head method of DmesgLogger"""

        with patch("subprocess.run") as mock_run:
            # Mock the subprocess output for dmesg
            mock_run.return_value.stdout = b"line1\nline2\n"
            mock_run.return_value.returncode = 0

            logger = DmesgLogger()
            logger._refresh_head()  # pylint: disable=protected-access
            self.assertEqual(logger.buffer, "line1\nline2\n")

    def test_dmesg_logger_seek_tail(self):
        """Test seek_tail method of DmesgLogger"""

        with patch("subprocess.run") as mock_run:
            # Mock the subprocess output for dmesg
            mock_run.return_value.stdout = b"line1\nline2\n"
            mock_run.return_value.returncode = 0

            logger = DmesgLogger()
            logger.seek_tail()
            self.assertEqual(logger.buffer, "line1\nline2\n")

    def test_dmesg_logger_process_callback(self):
        """Test process_callback method of DmesgLogger"""

        with patch("subprocess.run") as mock_run:
            # Mock the subprocess output for dmesg
            mock_run.return_value.stdout = b"line1\nline2\n"
            mock_run.return_value.returncode = 0

            logger = DmesgLogger()
            logger._refresh_head()  # pylint: disable=protected-access

            mock_callback = unittest.mock.Mock()
            logger.process_callback(mock_callback)

            mock_callback.assert_any_call("line1", None)
            mock_callback.assert_any_call("line2", None)

    def test_dmesg_logger_match_line(self):
        """Test match_line method of DmesgLogger"""

        with patch("subprocess.run") as mock_run:
            # Mock the subprocess output for dmesg
            mock_run.return_value.stdout = b"line1\nline2\n"
            mock_run.return_value.returncode = 0

            logger = DmesgLogger()
            logger._refresh_head()  # pylint: disable=protected-access

            result = logger.match_line(["line1"])
            self.assertEqual(result, "line1")

            result = logger.match_line(["nonexistent"])
            self.assertEqual(result, "")

    def test_dmesg_logger_match_pattern(self):
        """Test match_pattern method of DmesgLogger"""

        with patch("subprocess.run") as mock_run:
            # Mock the subprocess output for dmesg
            mock_run.return_value.stdout = b"line1\nline2\n"
            mock_run.return_value.returncode = 0

            logger = DmesgLogger()
            logger._refresh_head()  # pylint: disable=protected-access

            result = logger.match_pattern(r"line\d")
            self.assertEqual(result, "line1")

            result = logger.match_pattern(r"nonexistent")
            self.assertEqual(result, "")

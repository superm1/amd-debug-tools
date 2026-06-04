#!/usr/bin/python3
# SPDX-License-Identifier: MIT

"""
This module contains unit tests for the kernel log functions in the amd-debug-tools package.
"""
from datetime import datetime
from unittest.mock import patch, mock_open, MagicMock

import subprocess
import unittest
import logging

from amd_debug.kernel import (
    sscanf_bios_args,
    get_kernel_command_line,
    DmesgLogger,
    InputFile,
    KernelLogger,
    get_kernel_log,
)


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
            "amd_debug.common.open", new_callable=mock_open, read_data=kernel_cmdline
        ) as _mock_file:
            result = get_kernel_command_line()
            self.assertEqual(result, expected_output)

        # Test case with an empty kernel command line
        kernel_cmdline = ""
        expected_output = ""
        with patch(
            "amd_debug.common.open", new_callable=mock_open, read_data=kernel_cmdline
        ) as _mock_file:
            result = get_kernel_command_line()
            self.assertEqual(result, expected_output)

        # Test case with a kernel command line containing special characters
        kernel_cmdline = "quiet splash --debug=1"
        expected_output = "--debug=1"
        with patch(
            "amd_debug.common.open", new_callable=mock_open, read_data=kernel_cmdline
        ) as _mock_file:
            result = get_kernel_command_line()
            self.assertEqual(result, expected_output)

        # Test case with a kernel command line containing special characters
        kernel_cmdline = "quiet splash initrd=foo modprobe.blacklist=foo"
        expected_output = "modprobe.blacklist=foo"
        with patch(
            "amd_debug.common.open", new_callable=mock_open, read_data=kernel_cmdline
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
        expected_output = "POST CODE: B0003F33  ACPI TIMER: 83528798  TIME: 0.119 ms"
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
    @patch("subprocess.run")
    def setUpClass(cls, _mock_run=None):
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

    def test_dmesg_logger_seek_refreshes_if_seeked(self):
        """seek() re-refreshes the buffer if it was previously seeked"""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = b"old\n"
            mock_run.return_value.returncode = 0
            logger = DmesgLogger()
            logger.seeked = True

            mock_run.return_value.stdout = b"new\n"
            logger.seek()
            self.assertEqual(logger.buffer, "new\n")
            self.assertFalse(logger.seeked)

    def test_dmesg_logger_seek_noop_if_not_seeked(self):
        """seek() is a no-op when not seeked"""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = b"init\n"
            mock_run.return_value.returncode = 0
            logger = DmesgLogger()
            logger.buffer = "untouched"
            logger.seeked = False
            logger.seek()
            self.assertEqual(logger.buffer, "untouched")

    def test_dmesg_logger_seek_tail_with_time_since_support(self):
        """seek_tail with timestamp uses --since when supported"""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = b"--since supported\n"
            mock_run.return_value.returncode = 0
            logger = DmesgLogger()
            self.assertTrue(logger.since_support)

            mock_run.reset_mock()
            mock_run.return_value.stdout = b"sliced\n"
            mock_run.return_value.returncode = 0
            logger.seek_tail(datetime(2025, 1, 2, 3, 4, 5))

            call_args = mock_run.call_args[0][0]
            self.assertIn("--time-format=iso", call_args)
            self.assertTrue(any(a.startswith("--since=") for a in call_args))
            self.assertEqual(logger.buffer, "sliced\n")
            self.assertTrue(logger.seeked)

    def test_dmesg_logger_seek_tail_with_time_no_since_support(self):
        """seek_tail with timestamp but without --since support runs plain dmesg"""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = b"no since here\n"
            mock_run.return_value.returncode = 0
            logger = DmesgLogger()
            self.assertFalse(logger.since_support)

            mock_run.return_value.stdout = b"plain\n"
            logger.seek_tail(datetime(2025, 1, 2, 3, 4, 5))
            self.assertEqual(logger.buffer, "plain\n")
            self.assertFalse(logger.seeked)

    def test_dmesg_logger_capture_header(self):
        """capture_header returns the first line"""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = b"first\nsecond\n"
            mock_run.return_value.returncode = 0
            logger = DmesgLogger()
            self.assertEqual(logger.capture_header(), "first")

    def test_dmesg_logger_get_full_log(self):
        """get_full_log returns the buffer"""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = b"a\nb\n"
            mock_run.return_value.returncode = 0
            logger = DmesgLogger()
            self.assertEqual(logger.get_full_log(), "a\nb\n")


class TestKernelLoggerBase(unittest.TestCase):
    """Test the KernelLogger base class default implementations"""

    def test_base_methods_return_defaults(self):
        logger = KernelLogger()
        self.assertIsNone(logger.seek())
        self.assertIsNone(logger.seek_tail())
        self.assertIsNone(logger.process_callback(lambda x, p: None))
        self.assertEqual(logger.match_line(["foo"]), "")
        self.assertEqual(logger.match_pattern("foo"), "")
        self.assertEqual(logger.get_full_log(), "")


class TestInputFile(unittest.TestCase):
    """Test the InputFile kernel logger"""

    @patch("amd_debug.kernel.read_file", return_value="alpha\nbeta\n")
    def test_input_file_init_and_full_log(self, _mock_read):
        f = InputFile("/path/to/log")
        self.assertEqual(f.get_full_log(), "alpha\nbeta\n")
        self.assertFalse(f.since_support)

    @patch("amd_debug.kernel.read_file", return_value="alpha\nbeta")
    def test_input_file_process_callback(self, _mock_read):
        f = InputFile("/path/to/log")
        cb = MagicMock()
        f.process_callback(cb, priority=3)
        cb.assert_any_call("alpha", 3)
        cb.assert_any_call("beta", 3)


class TestSscanfBiosArgsEdge(unittest.TestCase):
    """Edge cases for sscanf_bios_args"""

    def test_ex_trace_args_no_separator(self):
        """ex_trace_args without ': ' separator returns None"""
        self.assertIsNone(sscanf_bios_args("ex_trace_args nothing"))

    def test_ex_trace_args_no_format_string(self):
        """ex_trace_args present but no quoted format -> True"""
        self.assertTrue(sscanf_bios_args("ex_trace_args: nonquoted stuff"))

    def test_ex_trace_args_bad_hex(self):
        """Non-hex argument value returns None"""
        line = 'ex_trace_args: "value: %x", notHex'
        self.assertIsNone(sscanf_bios_args(line))

    def test_ev_queue_notify_no_separator(self):
        """ev_queue_notify_reques without ': ' returns None"""
        self.assertIsNone(sscanf_bios_args("ev_queue_notify_reques nothing"))


class TestGetKernelLog(unittest.TestCase):
    """Test get_kernel_log provider selection"""

    @patch("amd_debug.kernel.read_file", return_value="x")
    def test_input_file_branch(self, _mock_read):
        log = get_kernel_log(input_file="/tmp/file")
        self.assertIsInstance(log, InputFile)

    @patch("amd_debug.kernel.systemd_in_use", return_value=False)
    @patch("amd_debug.kernel.subprocess.run")
    def test_dmesg_branch(self, mock_run, _mock_systemd):
        mock_run.return_value.stdout = b""
        mock_run.return_value.returncode = 0
        log = get_kernel_log()
        self.assertIsInstance(log, DmesgLogger)

    @patch("amd_debug.kernel.fatal_error")
    @patch("amd_debug.kernel.systemd_in_use", return_value=False)
    @patch(
        "amd_debug.kernel.subprocess.run",
        side_effect=subprocess.CalledProcessError(1, "dmesg"),
    )
    def test_dmesg_failure_falls_back(self, _mock_run, _mock_systemd, mock_fatal):
        log = get_kernel_log()
        self.assertIsInstance(log, KernelLogger)
        mock_fatal.assert_called_once()

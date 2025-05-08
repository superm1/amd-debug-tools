#!/usr/bin/python3
# SPDX-License-Identifier: MIT

"""
This module contains unit tests for the bios tool in the amd-debug-tools package.
"""
import argparse
import logging
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from amd_debug.bios import AmdBios, parse_args, main


class TestAmdBios(unittest.TestCase):
    """Test AmdBios class"""

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(filename="/dev/null", level=logging.DEBUG)

    @patch("amd_debug.bios.get_kernel_log")
    def test_init(self, mock_get_kernel_log):
        """Test initialization of AmdBios class"""
        mock_kernel_log = MagicMock()
        mock_get_kernel_log.return_value = mock_kernel_log

        app = AmdBios("test_input", debug=True)

        self.assertEqual(app.kernel_log, mock_kernel_log)

    @patch("amd_debug.bios.relaunch_sudo")
    @patch("amd_debug.bios.minimum_kernel")
    @patch("amd_debug.bios.AcpicaTracer")
    @patch("amd_debug.bios.print_color")
    def test_set_tracing_enable(
        self, _mock_print, mock_acpica_tracer, mock_minimum_kernel, mock_relaunch_sudo
    ):
        """Test enabling tracing"""
        mock_minimum_kernel.return_value = True
        mock_tracer = MagicMock()
        mock_acpica_tracer.return_value = mock_tracer
        mock_tracer.trace_bios.return_value = True

        app = AmdBios(None, debug=False)
        result = app.set_tracing(enable=True)

        mock_relaunch_sudo.assert_called_once()
        mock_tracer.trace_bios.assert_called_once()
        self.assertTrue(result)

    @patch("amd_debug.bios.relaunch_sudo")
    @patch("amd_debug.bios.minimum_kernel")
    @patch("amd_debug.bios.AcpicaTracer")
    @patch("amd_debug.bios.print_color")
    def test_set_tracing_disable(
        self, _mock_print, mock_acpica_tracer, mock_minimum_kernel, mock_relaunch_sudo
    ):
        """Test disabling tracing"""
        mock_minimum_kernel.return_value = True
        mock_tracer = MagicMock()
        mock_acpica_tracer.return_value = mock_tracer
        mock_tracer.disable.return_value = True

        app = AmdBios(None, debug=False)
        result = app.set_tracing(enable=False)

        mock_relaunch_sudo.assert_called_once()
        mock_tracer.disable.assert_called_once()
        self.assertTrue(result)

    @patch("amd_debug.bios.sscanf_bios_args")
    @patch("amd_debug.bios.print_color")
    def test_analyze_kernel_log_line(self, mock_print_color, mock_sscanf_bios_args):
        """Test analyzing kernel log line"""
        mock_sscanf_bios_args.return_value = "BIOS argument found"

        app = AmdBios(None, debug=False)
        app._analyze_kernel_log_line(  # pylint: disable=protected-access
            "test log line", priority="INFO"
        )

        mock_sscanf_bios_args.assert_called_once_with("test log line")
        mock_print_color.assert_called_once_with("BIOS argument found", "🖴")

    @patch("amd_debug.bios.sscanf_bios_args")
    @patch("amd_debug.bios.print_color")
    def test_analyze_kernel_log_line_no_bios_args(
        self, mock_print_color, mock_sscanf_bios_args
    ):
        """Test analyzing kernel log line with no BIOS arguments"""
        mock_sscanf_bios_args.return_value = None

        app = AmdBios(None, debug=False)
        app._analyze_kernel_log_line(  # pylint: disable=protected-access
            "[123.456] test log line", priority="INFO"
        )

        mock_sscanf_bios_args.assert_called_once_with("[123.456] test log line")
        mock_print_color.assert_called_once_with("test log line", "INFO")

    @patch("amd_debug.bios.get_kernel_log")
    def test_run(self, _mock_run):
        """Test run method"""
        mock_kernel_log = MagicMock()
        app = AmdBios(None, debug=False)
        app.kernel_log = mock_kernel_log

        app.run()

        mock_kernel_log.process_callback.assert_called_once_with(
            app._analyze_kernel_log_line  # pylint: disable=protected-access
        )

    @patch("sys.argv", ["bios.py", "parse", "--input", "test.log", "--tool-debug"])
    def test_parse_args_parse_command(self):
        """Test parse_args with parse command"""

        args = parse_args()
        self.assertEqual(args.command, "parse")
        self.assertEqual(args.input, "test.log")
        self.assertTrue(args.tool_debug)

    @patch("sys.argv", ["bios.py", "trace", "--enable", "--tool-debug"])
    def test_parse_args_trace_enable(self):
        """Test parse_args with trace enable command"""

        args = parse_args()
        self.assertEqual(args.command, "trace")
        self.assertTrue(args.enable)
        self.assertFalse(args.disable)
        self.assertTrue(args.tool_debug)

    @patch("sys.argv", ["bios.py", "trace", "--disable"])
    def test_parse_args_trace_disable(self):
        """Test parse_args with trace disable command"""

        args = parse_args()
        self.assertEqual(args.command, "trace")
        self.assertFalse(args.enable)
        self.assertTrue(args.disable)

    @patch("sys.argv", ["bios.py", "version"])
    def test_parse_args_version_command(self):
        """Test parse_args with version command"""

        args = parse_args()
        self.assertEqual(args.command, "version")

    @patch("sys.argv", ["bios.py"])
    @patch("argparse.ArgumentParser.print_help")
    @patch("sys.exit")
    def test_parse_args_no_arguments(self, mock_exit, mock_print_help):
        """Test parse_args with no arguments"""

        parse_args()
        mock_print_help.assert_called_once()
        mock_exit.assert_called_once_with(1)

    @patch("sys.argv", ["bios.py", "trace", "--enable", "--disable"])
    @patch("sys.exit")
    def test_parse_args_conflicting_trace_arguments(self, mock_exit):
        """Test parse_args with conflicting trace arguments"""

        parse_args()
        mock_exit.assert_called_once_with("can't set both enable and disable")

    @patch("sys.argv", ["bios.py", "trace"])
    @patch("sys.exit")
    def test_parse_args_missing_trace_arguments(self, mock_exit):
        """Test parse_args with missing trace arguments"""

        parse_args()
        mock_exit.assert_called_once_with("must set either enable or disable")

    @patch("amd_debug.bios.AmdBios")
    @patch("amd_debug.bios.parse_args")
    @patch("amd_debug.bios.version")
    @patch("amd_debug.bios.show_log_info")
    def test_main_trace_command(
        self, mock_show_log_info, _mock_version, mock_parse_args, mock_amd_bios
    ):
        """Test main function with trace command"""
        mock_app = MagicMock()
        mock_amd_bios.return_value = mock_app
        mock_parse_args.return_value = argparse.Namespace(
            command="trace", enable=True, disable=False, tool_debug=True
        )
        mock_app.set_tracing.return_value = True

        result = main()

        mock_parse_args.assert_called_once()
        mock_amd_bios.assert_called_once_with(None, True)
        mock_app.set_tracing.assert_called_once_with(True)
        mock_show_log_info.assert_called_once()
        self.assertTrue(result)

    @patch("amd_debug.bios.AmdBios")
    @patch("amd_debug.bios.parse_args")
    @patch("amd_debug.bios.version")
    @patch("amd_debug.bios.show_log_info")
    def test_main_parse_command(
        self, mock_show_log_info, _mock_version, mock_parse_args, mock_amd_bios
    ):
        """Test main function with parse command"""
        mock_app = MagicMock()
        mock_amd_bios.return_value = mock_app
        mock_parse_args.return_value = argparse.Namespace(
            command="parse", input="test.log", tool_debug=True
        )
        mock_app.run.return_value = True

        result = main()

        mock_parse_args.assert_called_once()
        mock_amd_bios.assert_called_once_with("test.log", True)
        mock_app.run.assert_called_once()
        mock_show_log_info.assert_called_once()
        self.assertTrue(result)

    @patch("amd_debug.bios.parse_args")
    @patch("amd_debug.bios.version")
    @patch("amd_debug.bios.show_log_info")
    @patch("amd_debug.bios.print")
    def test_main_version_command(
        self, _mock_print, mock_show_log_info, mock_version, mock_parse_args
    ):
        """Test main function with version command"""
        mock_parse_args.return_value = argparse.Namespace(command="version")
        mock_version.return_value = "1.0.0"

        result = main()

        mock_parse_args.assert_called_once()
        mock_version.assert_called_once()
        mock_show_log_info.assert_called_once()
        self.assertEqual(result, False)

    @patch("amd_debug.bios.parse_args")
    @patch("amd_debug.bios.show_log_info")
    def test_main_invalid_command(self, mock_show_log_info, mock_parse_args):
        """Test main function with an invalid command"""
        mock_parse_args.return_value = argparse.Namespace(command="invalid")

        result = main()

        mock_parse_args.assert_called_once()
        mock_show_log_info.assert_called_once()
        self.assertFalse(result)

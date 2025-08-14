#!/usr/bin/python3
# SPDX-License-Identifier: MIT

"""
This module contains unit tests for the ttm tool in the amd-debug-tools package.
"""
import unittest
import sys
import logging
from unittest import mock

from amd_debug.ttm import main, parse_args, AmdTtmTool, maybe_reboot


class TestParseArgs(unittest.TestCase):
    """Test parse_args function"""

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(filename="/dev/null", level=logging.DEBUG)

    def setUp(self):
        self.default_sys_argv = sys.argv

    def tearDown(self):
        sys.argv = self.default_sys_argv

    @mock.patch.object(sys, "argv", new=["ttm", "--version"])
    def test_parse_args_version(self):
        """Test version argument"""
        args = parse_args()
        self.assertTrue(args.version)
        self.assertFalse(args.set)
        self.assertFalse(args.clear)

    @mock.patch.object(sys, "argv", new=["ttm", "--clear"])
    def test_parse_args_clear(self):
        """Test clear argument"""
        args = parse_args()
        self.assertFalse(args.version)
        self.assertFalse(args.set)
        self.assertTrue(args.clear)


class TestMainFunction(unittest.TestCase):
    """Test main() function logic"""

    @mock.patch("amd_debug.ttm.parse_args")
    @mock.patch("amd_debug.ttm.version", return_value="1.2.3")
    @mock.patch("builtins.print")
    def test_main_version(self, mock_print, _mock_version, mock_parse_args):
        """Test main function with version argument"""
        mock_parse_args.return_value = mock.Mock(
            version=True, set=None, clear=False, tool_debug=False
        )
        ret = main()
        mock_print.assert_called_with("1.2.3")
        self.assertIsNone(ret)

    @mock.patch("amd_debug.ttm.parse_args")
    @mock.patch("amd_debug.ttm.AmdTtmTool")
    @mock.patch("builtins.print")
    def test_main_set_invalid(self, mock_print, _mock_tool, mock_parse_args):
        """Test main function with invalid set argument"""
        mock_parse_args.return_value = mock.Mock(
            version=False, set=0, clear=False, tool_debug=False
        )
        ret = main()
        mock_print.assert_called_with("Error: GB value must be greater than 0")
        self.assertEqual(ret, 1)

    @mock.patch("amd_debug.ttm.parse_args")
    @mock.patch("amd_debug.ttm.AmdTtmTool")
    def test_main_set_valid(self, mock_tool, mock_parse_args):
        """Test main function with set argument"""
        instance = mock_tool.return_value
        instance.set.return_value = True
        mock_parse_args.return_value = mock.Mock(
            version=False, set=2, clear=False, tool_debug=False
        )
        ret = main()
        instance.set.assert_called_with(2)
        self.assertIsNone(ret)

    @mock.patch("amd_debug.ttm.parse_args")
    @mock.patch("amd_debug.ttm.AmdTtmTool")
    def test_main_set_failed(self, mock_tool, mock_parse_args):
        instance = mock_tool.return_value
        instance.set.return_value = False
        mock_parse_args.return_value = mock.Mock(
            version=False, set=2, clear=False, tool_debug=False
        )
        ret = main()
        instance.set.assert_called_with(2)
        self.assertEqual(ret, 1)

    @mock.patch("amd_debug.ttm.parse_args")
    @mock.patch("amd_debug.ttm.AmdTtmTool")
    def test_main_clear_success(self, mock_tool, mock_parse_args):
        """Test main function with clear argument"""
        instance = mock_tool.return_value
        instance.clear.return_value = True
        mock_parse_args.return_value = mock.Mock(
            version=False, set=None, clear=True, tool_debug=False
        )
        ret = main()
        instance.clear.assert_called_once()
        self.assertIsNone(ret)

    @mock.patch("amd_debug.ttm.parse_args")
    @mock.patch("amd_debug.ttm.AmdTtmTool")
    def test_main_clear_failed(self, mock_tool, mock_parse_args):
        """Test main function with clear argument failure"""
        instance = mock_tool.return_value
        instance.clear.return_value = False
        mock_parse_args.return_value = mock.Mock(
            version=False, set=None, clear=True, tool_debug=False
        )
        ret = main()
        instance.clear.assert_called_once()
        self.assertEqual(ret, 1)

    @mock.patch("amd_debug.ttm.parse_args")
    @mock.patch("amd_debug.ttm.AmdTtmTool")
    def test_main_get_success(self, mock_tool, mock_parse_args):
        """Test main function with get argument"""
        instance = mock_tool.return_value
        instance.get.return_value = True
        mock_parse_args.return_value = mock.Mock(
            version=False, set=None, clear=False, tool_debug=False
        )
        ret = main()
        instance.get.assert_called_once()
        self.assertIsNone(ret)

    @mock.patch("amd_debug.ttm.parse_args")
    @mock.patch("amd_debug.ttm.AmdTtmTool")
    def test_main_get_failed(self, mock_tool, mock_parse_args):
        """Test main function with get argument failure"""
        instance = mock_tool.return_value
        instance.get.return_value = False
        mock_parse_args.return_value = mock.Mock(
            version=False, set=None, clear=False, tool_debug=False
        )
        ret = main()
        instance.get.assert_called_once()
        self.assertEqual(ret, 1)


class TestMaybeReboot(unittest.TestCase):
    """Test maybe_reboot function"""

    @mock.patch("builtins.input", return_value="y")
    @mock.patch("amd_debug.ttm.reboot", return_value=True)
    def test_maybe_reboot_yes(self, mock_reboot, _mock_input):
        """Test reboot confirmation and execution"""
        result = maybe_reboot()
        mock_reboot.assert_called_once()
        self.assertTrue(result)

    @mock.patch("builtins.input", return_value="n")
    @mock.patch("amd_debug.ttm.reboot", return_value=True)
    def test_maybe_reboot_no(self, mock_reboot, _mock_input):
        """Test reboot confirmation without execution"""
        result = maybe_reboot()
        mock_reboot.assert_not_called()
        self.assertTrue(result)


class TestAmdTtmTool(unittest.TestCase):
    """Unit tests for AmdTtmTool class"""

    def setUp(self):
        self.tool = AmdTtmTool(logging=False)

    @mock.patch("builtins.open", new_callable=mock.mock_open, read_data="4096")
    @mock.patch("amd_debug.ttm.bytes_to_gb", return_value=4.0)
    @mock.patch("amd_debug.ttm.print_color")
    @mock.patch("amd_debug.ttm.get_system_mem", return_value=16.0)
    def test_get_success(self, _mock_mem, mock_print, _mock_bytes_to_gb, mock_open):
        """Test get() when TTM_PARAM_PATH exists"""
        result = self.tool.get()
        mock_open.assert_called_once_with(
            "/sys/module/ttm/parameters/pages_limit", "r", encoding="utf-8"
        )
        mock_print.assert_any_call(
            "Current TTM pages limit: 4096 pages (4.00 GB)", "💻"
        )
        mock_print.assert_any_call("Total system memory: 16.00 GB", "💻")
        self.assertTrue(result)

    @mock.patch("builtins.open", side_effect=FileNotFoundError)
    @mock.patch("amd_debug.ttm.print_color")
    def test_get_file_not_found(self, mock_print, _mock_open):
        """Test get() when TTM_PARAM_PATH does not exist"""
        result = self.tool.get()
        mock_print.assert_called_with(
            "Error: Could not find /sys/module/ttm/parameters/pages_limit", "❌"
        )
        self.assertFalse(result)

    @mock.patch("amd_debug.ttm.relaunch_sudo", return_value=True)
    @mock.patch("amd_debug.ttm.get_system_mem", return_value=8.0)
    @mock.patch("amd_debug.ttm.print_color")
    def test_set_gb_greater_than_total(
        self, mock_print, _mock_mem, _mock_relaunch_sudo
    ):
        """Test set() when gb_value > total system memory"""
        result = self.tool.set(16)
        mock_print.assert_any_call(
            "16.00 GB is greater than total system memory (8.00 GB)", "❌"
        )
        self.assertFalse(result)

    @mock.patch("amd_debug.ttm.relaunch_sudo", return_value=True)
    @mock.patch("amd_debug.ttm.get_system_mem", return_value=10.0)
    @mock.patch("amd_debug.ttm.print_color")
    @mock.patch("builtins.input", return_value="n")
    def test_set_gb_exceeds_max_percentage_cancel(
        self, _mock_input, mock_print, _mock_mem, mock_relaunch_sudo
    ):
        """Test set() when gb_value exceeds max percentage and user cancels"""
        result = self.tool.set(9.5)
        self.assertFalse(result)
        mock_print.assert_any_call("Operation cancelled.", "🚦")

    @mock.patch("amd_debug.ttm.relaunch_sudo", return_value=True)
    @mock.patch("amd_debug.ttm.get_system_mem", return_value=10.0)
    @mock.patch("amd_debug.ttm.gb_to_pages", return_value=20480)
    @mock.patch("amd_debug.ttm.print_color")
    @mock.patch("builtins.open", new_callable=mock.mock_open)
    @mock.patch("builtins.input", return_value="y")
    @mock.patch("amd_debug.ttm.maybe_reboot", return_value=True)
    def test_set_success(
        self,
        _mock_reboot,
        _mock_input,
        mock_open,
        mock_print,
        _mock_gb_to_pages,
        _mock_mem,
        _relaunch_sudo,
    ):
        """Test set() success path"""
        result = self.tool.set(5)
        mock_open.assert_called_once_with(
            "/etc/modprobe.d/ttm.conf", "w", encoding="utf-8"
        )
        mock_print.assert_any_call(
            "Successfully set TTM pages limit to 20480 pages (5.00 GB)", "🐧"
        )
        self.assertTrue(result)

    @mock.patch("os.path.exists", return_value=False)
    @mock.patch("amd_debug.ttm.print_color")
    def test_clear_file_not_exists(self, mock_print, _mock_exists):
        """Test clear() when config file does not exist"""
        result = self.tool.clear()
        mock_print.assert_called_with("/etc/modprobe.d/ttm.conf doesn't exist", "❌")
        self.assertFalse(result)

    @mock.patch("os.path.exists", return_value=True)
    @mock.patch("amd_debug.ttm.relaunch_sudo", return_value=True)
    @mock.patch("os.remove")
    @mock.patch("amd_debug.ttm.print_color")
    @mock.patch("amd_debug.ttm.maybe_reboot", return_value=True)
    def test_clear_success(
        self, _mock_reboot, mock_print, mock_remove, _mock_relaunch_sudo, _mock_exists
    ):
        """Test clear() success path"""
        result = self.tool.clear()
        mock_remove.assert_called_once_with("/etc/modprobe.d/ttm.conf")
        mock_print.assert_any_call(
            "Configuration /etc/modprobe.d/ttm.conf removed", "🐧"
        )
        self.assertTrue(result)

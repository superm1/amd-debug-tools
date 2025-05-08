#!/usr/bin/python3
# SPDX-License-Identifier: MIT

"""
This module contains unit tests for the launcher in the amd-debug-tools package.
"""
from unittest.mock import patch

import logging
import unittest
import sys
import os

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import amd_debug


class TestLauncher(unittest.TestCase):
    """Test launcher functions"""

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(filename="/dev/null", level=logging.DEBUG)

    def setUp(self):
        launcher = None

    def test_launcher_unknown(self):
        """Test launching as unknown exe"""

        with patch("builtins.print") as mock_print:
            amd_debug.launch_tool("unknown_exe.py")
            mock_print.assert_called_once_with(
                "\033[91mUnknown exe: unknown_exe.py\033[0m"
            )

    def test_launcher_amd_s2idle(self):
        """Test launching amd_s2idle"""

        with patch("amd_debug.s2idle.main") as mock_main:
            amd_debug.launch_tool("amd_s2idle.py")
            mock_main.assert_called_once()

    def test_launcher_amd_bios(self):
        """Test launching amd_bios"""

        with patch("amd_debug.bios.main") as mock_main:
            amd_debug.launch_tool("amd_bios.py")
            mock_main.assert_called_once()

    def test_launcher_amd_pstate(self):
        """Test launching amd_pstate"""

        with patch("amd_debug.pstate.main") as mock_main:
            amd_debug.launch_tool("amd_pstate.py")
            mock_main.assert_called_once()

    @patch("amd_debug.common.fatal_error")
    def test_helpers(self, mock_fatal_error):
        """Test that the script exits with an error when run standalone"""
        with patch.dict("sys.modules", {"amd_debug": None}):
            with self.assertRaises(SystemExit):
                import launcher as _
        with patch.dict("sys.modules", {"amd_debug.common": None}):
            with self.assertRaises(SystemExit):
                import launcher as _

        from launcher import main

        with patch("sys.argv", ["amd_s2idle.py"]), patch(
            "amd_debug.launch_tool"
        ) as mock_launch_tool:
            mock_launch_tool.return_value = True
            result = main()
            mock_launch_tool.assert_called_once_with("amd_s2idle.py")
            self.assertTrue(result)

        with patch("sys.argv", ["unknown_exe.py"]), patch(
            "amd_debug.launch_tool"
        ) as mock_launch_tool:
            mock_launch_tool.return_value = False
            result = main()
            mock_launch_tool.assert_called_once_with("unknown_exe.py")
            self.assertFalse(result)

        # Test main function when a dependency is missing"""
        with patch("sys.argv", ["amd_s2idle.py"]), patch(
            "amd_debug.launch_tool", side_effect=ModuleNotFoundError("missing_module")
        ):
            result = main()
            self.assertFalse(result)
            mock_fatal_error.assert_called_once_with(
                "Missing dependency: missing_module\n"
                "Run ./install_deps.py to install dependencies."
            )

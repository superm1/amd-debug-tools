#!/usr/bin/python3
# SPDX-License-Identifier: MIT

"""
This module contains unit tests for the launcher in the amd-debug-tools package.
"""
from unittest.mock import patch

import logging
import unittest

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
            result = amd_debug.launch_tool("unknown_exe.py")
            mock_print.assert_called_once_with(
                "\033[91mUnknown exe: unknown_exe.py\033[0m"
            )
            self.assertIsNotNone(result)

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

    def test_launcher_amd_ttm(self):
        """Test launching amd_ttm"""

        with patch("amd_debug.ttm.main") as mock_main:
            amd_debug.launch_tool("amd_ttm.py")
            mock_main.assert_called_once()

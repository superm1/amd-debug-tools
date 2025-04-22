#!/usr/bin/python3
# SPDX-License-Identifier: MIT

"""
This module contains unit tests for the validator functions in the amd-debug-tools package.
"""

from unittest.mock import patch, mock_open

import logging
import unittest
import sys
import os

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from amd_debug.validator import pm_debugging, soc_needs_irq1_wa, SleepValidator


class TestValidator(unittest.TestCase):
    """Test validator functions"""

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(filename="/dev/null", level=logging.DEBUG)

    def test_soc_needs_irq1_wa(self):
        """Test if the SOC should apply an IRQ1 workaround"""
        ret = soc_needs_irq1_wa(0x17, 0x68, "1.2.3")
        self.assertTrue(ret)
        ret = soc_needs_irq1_wa(0x17, 0x69, "1.2.3")
        self.assertFalse(ret)
        ret = soc_needs_irq1_wa(0x19, 0x51, "64.65.0")
        self.assertFalse(ret)
        ret = soc_needs_irq1_wa(0x19, 0x50, "64.65.0")
        self.assertTrue(ret)
        ret = soc_needs_irq1_wa(0x19, 0x50, "64.66.0")
        self.assertFalse(ret)

    def test_pm_debugging(self):
        """Test pm_debugging decorator"""

        @pm_debugging
        def test_function():
            return "Test function executed"

        # Mock /sys/power/pm_debug_messages existing and all ACPI existing
        with patch("builtins.open", new_callable=mock_open, read_data="0") as mock_file:
            handlers = (
                mock_file.return_value,
                mock_open(read_data="0").return_value,
                mock_open(read_data="0").return_value,
                mock_open(read_data="0").return_value,
            )
            mock_open.side_effect = handlers
            result = test_function()
            self.assertEqual(result, "Test function executed")

        # Mock /sys/power/pm_debug_messages missing
        with patch(
            "builtins.open", side_effect=FileNotFoundError("not found")
        ) as mock_file:
            with self.assertRaises(FileNotFoundError):
                result = test_function()

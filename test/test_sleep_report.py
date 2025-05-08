#!/usr/bin/python3
# SPDX-License-Identifier: MIT

"""
This module contains unit tests for the s2idle tool in the amd-debug-tools package.
"""

import sys
import os
import unittest
from datetime import datetime
from unittest.mock import patch
import pandas as pd

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from amd_debug.sleep_report import (
    remove_duplicates,
    format_gpio_as_str,
    format_irq_as_str,
    format_as_human,
    format_as_seconds,
    format_watts,
    format_percent,
    format_timedelta,
    parse_hw_sleep,
    SleepReport,
)

from amd_debug.wake import WakeGPIO, WakeIRQ


class TestSleepReportUtils(unittest.TestCase):
    """Unit tests for the sleep report utilities."""

    def test_remove_duplicates(self):
        """Test the remove_duplicates function."""
        self.assertEqual(remove_duplicates("1, 2, 2, 3"), [1, 2, 3])
        self.assertEqual(remove_duplicates("4 4 5 6"), [4, 5, 6])
        self.assertEqual(remove_duplicates(""), [])

    def test_format_gpio_as_str(self):
        """Test the format_gpio_as_str function."""
        self.assertEqual(format_gpio_as_str("1, 2, 2, 3"), "1, 2, 3")
        self.assertEqual(format_gpio_as_str("4 4 5 6"), "4, 5, 6")
        self.assertEqual(format_gpio_as_str(""), "")

    @patch("amd_debug.wake.read_file")
    @patch("os.path.exists")
    @patch("os.listdir")
    @patch("os.walk")
    def test_format_irq_as_str(
        self, _mock_os_walk, _mock_os_listdir, mock_os_path_exists, mock_read_file
    ):
        """Test the format_irq_as_str function."""
        mock_read_file.side_effect = lambda path: {
            "/sys/kernel/irq/20/chip_name": "",
            "/sys/kernel/irq/20/actions": "",
            "/sys/kernel/irq/20/wakeup": "disabled",
        }.get(path, "")

        # Mocking os.path.exists
        mock_os_path_exists.return_value = False

        self.assertEqual(format_irq_as_str("20"), "Disabled interrupt")
        self.assertEqual(format_irq_as_str(""), "")

    def test_format_as_human(self):
        """Test the format_as_human function."""
        self.assertEqual(
            format_as_human("20231010123045"),
            datetime(2023, 10, 10, 12, 30, 45),
        )
        with self.assertRaises(ValueError):
            format_as_human("invalid_date")

    def test_format_as_seconds(self):
        """Test the format_as_seconds function."""
        self.assertEqual(
            format_as_seconds("20231010123045"),
            datetime(2023, 10, 10, 12, 30, 45).timestamp(),
        )
        with self.assertRaises(ValueError):
            format_as_seconds("invalid_date")

    def test_format_watts(self):
        """Test the format_watts function."""
        self.assertEqual(format_watts(12.3456), "12.35W")
        self.assertEqual(format_watts(0), "0.00W")

    def test_format_percent(self):
        """Test the format_percent function."""
        self.assertEqual(format_percent(12.3456), "12.35%")
        self.assertEqual(format_percent(0), "0.00%")

    def test_format_timedelta(self):
        """Test the format_timedelta function."""
        self.assertEqual(format_timedelta(3600), "1:00:00")
        self.assertEqual(format_timedelta(3661), "1:01:01")

    def test_parse_hw_sleep(self):
        """Test the parse_hw_sleep function."""
        self.assertEqual(parse_hw_sleep(0.5), 50)
        self.assertEqual(parse_hw_sleep(1.0), 100)
        self.assertEqual(parse_hw_sleep(1.5), 0)


class TestSleepReport(unittest.TestCase):
    """Unit tests for the SleepReport class."""

    @patch("amd_debug.sleep_report.SleepDatabase")
    def setUp(self, MockSleepDatabase):
        """Set up a mock SleepReport instance for testing."""
        self.mock_db = MockSleepDatabase.return_value
        self.mock_db.report_summary_dataframe.return_value = pd.DataFrame(
            {
                "t0": [datetime(2023, 10, 10, 12, 0, 0).strftime("%Y%m%d%H%M%S")],
                "t1": [datetime(2023, 10, 10, 12, 30, 0).strftime("%Y%m%d%H%M%S")],
                "hw": [50],
                "requested": [1],
                "gpio": ["1, 2"],
                "wake_irq": ["1"],
                "b0": [90],
                "b1": [85],
                "full": [100],
            }
        )
        self.since = datetime(2023, 10, 9, 0, 0, 0)
        self.until = datetime(2023, 10, 12, 0, 0, 0)
        self.report = SleepReport(
            since=self.since,
            until=self.until,
            fname=None,
            fmt="txt",
            tool_debug=False,
            report_debug=False,
        )

    def test_analyze_duration(self):
        """Test the analyze_duration method."""
        self.report.analyze_duration(
            index=0,
            t0=datetime(2023, 10, 10, 12, 0, 0),
            t1=datetime(2023, 10, 10, 12, 30, 0),
            requested=20,
            hw=50,
        )
        self.assertEqual(len(self.report.failures), 2)

    @patch("amd_debug.sleep_report.Environment")
    @patch("amd_debug.sleep_report.FileSystemLoader")
    def test_build_template(self, _mock_fsl, mock_env):
        """Test the build_template method."""
        mock_template = mock_env.return_value.get_template.return_value
        mock_template.render.return_value = "Rendered Template"
        result = self.report.build_template(inc_prereq=False)
        self.assertEqual(result, "Rendered Template")

    @patch("matplotlib.pyplot.savefig")
    def test_build_battery_chart(self, mock_savefig):
        """Test the build_battery_chart method."""
        self.report.build_battery_chart()
        self.assertIsNotNone(self.report.battery_svg)
        mock_savefig.assert_called_once()

    @patch("matplotlib.pyplot.savefig")
    def test_build_hw_sleep_chart(self, mock_savefig):
        """Test the build_hw_sleep_chart method."""
        self.report.build_hw_sleep_chart()
        self.assertIsNotNone(self.report.hwsleep_svg)
        mock_savefig.assert_called_once()

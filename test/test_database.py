#!/usr/bin/python3
# SPDX-License-Identifier: MIT

"""
This module contains unit tests for the datbase functions in the amd-debug-tools package.
"""
import unittest
import sqlite3
import sys
import os

from datetime import datetime
from unittest.mock import patch, MagicMock

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from amd_debug.database import SleepDatabase


class TestSleepDatabase(unittest.TestCase):
    """Test SleepDatabase class"""

    def setUp(self):
        """Set up mocks and an in-memory database for testing"""
        # Initialize SleepDatabase after mocks are set up
        self.db = SleepDatabase(dbf=":memory:")

    def test_start_cycle(self):
        """Test starting a new sleep cycle"""
        timestamp = datetime.now()
        self.db.start_cycle(timestamp)
        self.assertEqual(self.db.last_suspend, timestamp)
        self.assertEqual(self.db.cycle_data_cnt, 0)
        self.assertEqual(self.db.debug_cnt, 0)

    def test_record_debug(self):
        """Test recording a debug message"""
        timestamp = datetime.now()
        self.db.start_cycle(timestamp)
        self.db.record_debug("Test debug message", level=5)
        cur = self.db.db.cursor()
        cur.execute(
            "SELECT message, priority FROM debug WHERE t0=?",
            (int(timestamp.strftime("%Y%m%d%H%M%S")),),
        )
        result = cur.fetchone()
        self.assertEqual(result, ("Test debug message", 5))

    def test_record_battery_energy(self):
        """Test recording battery energy"""
        timestamp = datetime.now()
        self.db.start_cycle(timestamp)
        self.db.record_battery_energy("Battery1", 50, 100, "mWh")
        cur = self.db.db.cursor()
        cur.execute(
            "SELECT name, b0, b1, full, unit FROM battery WHERE t0=?",
            (int(timestamp.strftime("%Y%m%d%H%M%S")),),
        )
        result = cur.fetchone()
        self.assertEqual(result, ("Battery1", 50, None, 100, "mWh"))

    def test_record_cycle_data(self):
        """Test recording cycle data"""
        timestamp = datetime.now()
        self.db.start_cycle(timestamp)
        self.db.record_cycle_data("Test cycle data", "symbol1")
        cur = self.db.db.cursor()
        cur.execute(
            "SELECT message, symbol FROM cycle_data WHERE t0=?",
            (int(timestamp.strftime("%Y%m%d%H%M%S")),),
        )
        result = cur.fetchone()
        self.assertEqual(result, ("Test cycle data", "symbol1"))

    def test_record_cycle(self):
        """Test recording a sleep cycle"""
        timestamp = datetime.now()
        self.db.start_cycle(timestamp)
        self.db.record_cycle(
            requested_duration=100,
            active_gpios="GPIO1",
            wakeup_irqs="IRQ1",
            kernel_duration=1.5,
            hw_sleep_duration=2.5,
        )
        cur = self.db.db.cursor()
        cur.execute(
            "SELECT requested, gpio, wake_irq, kernel, hw FROM cycle WHERE t0=?",
            (int(timestamp.strftime("%Y%m%d%H%M%S")),),
        )
        result = cur.fetchone()
        self.assertEqual(result, (100, "GPIO1", "IRQ1", 1.5, 2.5))

    def test_report_debug(self):
        """Test reporting debug messages"""
        timestamp = datetime.now()
        self.db.start_cycle(timestamp)
        self.db.record_debug("Test debug message", level=5)
        result = self.db.report_debug(timestamp)
        self.assertEqual(result, [("Test debug message", 5)])

    def test_report_battery(self):
        """Test reporting battery data"""
        timestamp = datetime.now()
        self.db.start_cycle(timestamp)
        self.db.record_battery_energy("Battery1", 50, 100, "mWh")
        result = self.db.report_battery(timestamp)
        self.assertEqual(
            result,
            [
                (
                    int(timestamp.strftime("%Y%m%d%H%M%S")),
                    "Battery1",
                    50,
                    None,
                    100,
                    "mWh",
                )
            ],
        )

    def test_record_prereq(self):
        """Test recording a prereq message"""
        timestamp = datetime.now()
        self.db.start_cycle(timestamp)
        self.db.record_prereq("Test prereq message", "symbol1")
        cur = self.db.db.cursor()
        cur.execute(
            "SELECT message, symbol FROM prereq_data WHERE t0=?",
            (int(timestamp.strftime("%Y%m%d%H%M%S")),),
        )
        result = cur.fetchone()
        self.assertEqual(result, ("Test prereq message", "symbol1"))

    def test_report_prereq(self):
        """Test reporting prereq messages"""
        timestamp = datetime.now()
        self.db.start_cycle(timestamp)
        self.db.record_prereq("Test prereq message 1", "symbol1")
        self.db.record_prereq("Test prereq message 2", "symbol2")
        result = self.db.report_prereq(timestamp)
        self.assertEqual(
            result,
            [
                (
                    int(timestamp.strftime("%Y%m%d%H%M%S")),
                    0,
                    "Test prereq message 1",
                    "symbol1",
                ),
                (
                    int(timestamp.strftime("%Y%m%d%H%M%S")),
                    1,
                    "Test prereq message 2",
                    "symbol2",
                ),
            ],
        )

    def test_report_prereq_no_data(self):
        """Test reporting prereq messages when no data exists"""
        timestamp = datetime.now()
        self.db.start_cycle(timestamp)
        result = self.db.report_prereq(timestamp)
        self.assertEqual(result, [])

    def test_report_prereq_none_timestamp(self):
        """Test reporting prereq messages with None timestamp"""
        result = self.db.report_prereq(None)
        self.assertEqual(result, [])

    def test_report_cycle(self):
        """Test reporting a cycle from the database"""
        timestamp = datetime.now()
        self.db.start_cycle(timestamp)
        self.db.record_cycle(
            requested_duration=100,
            active_gpios="GPIO1",
            wakeup_irqs="IRQ1",
            kernel_duration=1.5,
            hw_sleep_duration=2.5,
        )
        result = self.db.report_cycle(timestamp)
        self.assertEqual(
            result,
            [
                (
                    int(timestamp.strftime("%Y%m%d%H%M%S")),
                    int(datetime.now().strftime("%Y%m%d%H%M%S")),
                    100,
                    "GPIO1",
                    "IRQ1",
                    1.5,
                    2.5,
                )
            ],
        )

    def test_report_cycle_no_data(self):
        """Test reporting a cycle when no data exists"""
        timestamp = datetime.now()
        self.db.start_cycle(timestamp)
        result = self.db.report_cycle(timestamp)
        self.assertEqual(result, [])

    def test_report_cycle_none_timestamp(self):
        """Test reporting a cycle with None timestamp"""
        timestamp = datetime.now()
        self.db.start_cycle(timestamp)
        self.db.record_cycle(
            requested_duration=100,
            active_gpios="GPIO1",
            wakeup_irqs="IRQ1",
            kernel_duration=1.5,
            hw_sleep_duration=2.5,
        )
        result = self.db.report_cycle(None)
        self.assertEqual(
            result,
            [
                (
                    int(timestamp.strftime("%Y%m%d%H%M%S")),
                    int(datetime.now().strftime("%Y%m%d%H%M%S")),
                    100,
                    "GPIO1",
                    "IRQ1",
                    1.5,
                    2.5,
                )
            ],
        )

    def test_get_last_cycle(self):
        """Test getting the last cycle from the database"""
        timestamp = datetime.now()
        self.db.start_cycle(timestamp)
        self.db.record_cycle(
            requested_duration=100,
            active_gpios="GPIO1",
            wakeup_irqs="IRQ1",
            kernel_duration=1.5,
            hw_sleep_duration=2.5,
        )
        result = self.db.get_last_cycle()
        self.assertEqual(result, (int(timestamp.strftime("%Y%m%d%H%M%S")),))

    def test_get_last_cycle_no_data(self):
        """Test getting the last cycle when no data exists"""
        result = self.db.get_last_cycle()
        self.assertIsNone(result)

    def test_get_last_prereq_ts(self):
        """Test getting the last prereq timestamp from the database"""
        timestamp = datetime.now()
        self.db.start_cycle(timestamp)
        self.db.record_prereq("Test prereq message 1", "symbol1")
        self.db.record_prereq("Test prereq message 2", "symbol2")
        result = self.db.get_last_prereq_ts()
        self.assertEqual(result, int(timestamp.strftime("%Y%m%d%H%M%S")))

    def test_get_last_prereq_ts_no_data(self):
        """Test getting the last prereq timestamp when no data exists"""
        result = self.db.get_last_prereq_ts()
        self.assertIsNone(result)

    def test_report_cycle_data(self):
        """Test reporting cycle data"""
        timestamp = datetime.now()
        self.db.start_cycle(timestamp)
        self.db.record_cycle_data("Test cycle data 1", "symbol1")
        self.db.record_cycle_data("Test cycle data 2", "symbol2")
        result = self.db.report_cycle_data(timestamp)
        expected_result = "symbol1 Test cycle data 1\nsymbol2 Test cycle data 2\n"
        self.assertEqual(result, expected_result)

    def test_report_cycle_data_no_data(self):
        """Test reporting cycle data when no data exists"""
        timestamp = datetime.now()
        self.db.start_cycle(timestamp)
        result = self.db.report_cycle_data(timestamp)
        self.assertEqual(result, "")

    def test_report_cycle_data_none_timestamp(self):
        """Test reporting cycle data with None timestamp"""
        timestamp = datetime.now()
        self.db.start_cycle(timestamp)
        self.db.record_cycle_data("Test cycle data 1", "symbol1")
        result = self.db.report_cycle_data(None)
        expected_result = "symbol1 Test cycle data 1\n"
        self.assertEqual(result, expected_result)

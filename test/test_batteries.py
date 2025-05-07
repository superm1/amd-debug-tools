#!/usr/bin/python3
# SPDX-License-Identifier: MIT

"""
This module contains unit tests for the battery functions in the amd-debug-tools package.
"""
import unittest
import logging
from unittest.mock import MagicMock, patch
import sys
import os

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from amd_debug.battery import Batteries


class TestBatteries(unittest.TestCase):
    """Test battery functions"""

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(filename="/dev/null", level=logging.DEBUG)

    @patch("amd_debug.battery.Context")
    def setUp(self, mock_context):
        """Set up a mock context for testing"""
        self.mock_context = mock_context.return_value
        self.batteries = Batteries()

    def test_get_batteries(self):
        """Test getting battery names"""
        mock_device = MagicMock()
        mock_device.device_path = "/devices/LNXSYSTM:00/device:00/PNP0C0A:00"
        mock_device.properties = {"POWER_SUPPLY_NAME": "BAT0"}
        self.mock_context.list_devices.return_value = [mock_device]

        result = self.batteries.get_batteries()
        self.assertEqual(result, ["BAT0"])

    def test_get_energy_unit(self):
        """Test getting energy unit for a battery"""
        mock_device = MagicMock()
        mock_device.device_path = "/devices/LNXSYSTM:00/device:00/PNP0C0A:00"
        mock_device.properties = {
            "POWER_SUPPLY_NAME": "BAT0",
            "POWER_SUPPLY_ENERGY_NOW": "50000",
        }
        self.mock_context.list_devices.return_value = [mock_device]
        result = self.batteries.get_energy_unit("BAT0")
        self.assertEqual(result, "µWh")

    def test_get_energy(self):
        """Test getting current energy for a battery"""
        mock_device = MagicMock()
        mock_device.device_path = "/devices/LNXSYSTM:00/device:00/PNP0C0A:00"
        mock_device.properties = {
            "POWER_SUPPLY_NAME": "BAT0",
            "POWER_SUPPLY_ENERGY_NOW": "50000",
        }
        self.mock_context.list_devices.return_value = [mock_device]
        result = self.batteries.get_energy("BAT0")
        self.assertEqual(result, "50000")

    def test_get_energy_full(self):
        """Test getting full energy for a battery"""
        mock_device = MagicMock()
        mock_device.device_path = "/devices/LNXSYSTM:00/device:00/PNP0C0A:00"
        mock_device.properties = {
            "POWER_SUPPLY_NAME": "BAT0",
            "POWER_SUPPLY_ENERGY_FULL": "60000",
        }
        self.mock_context.list_devices.return_value = [mock_device]

        result = self.batteries.get_energy_full("BAT0")
        self.assertEqual(result, "60000")

    def test_get_description_string(self):
        """Test getting description string for a battery"""
        mock_device = MagicMock()
        mock_device.device_path = "/devices/LNXSYSTM:00/device:00/PNP0C0A:00"
        mock_device.properties = {
            "POWER_SUPPLY_NAME": "BAT0",
            "POWER_SUPPLY_MANUFACTURER": "ACME",
            "POWER_SUPPLY_MODEL_NAME": "SuperBattery",
            "POWER_SUPPLY_ENERGY_FULL": "60000",
            "POWER_SUPPLY_ENERGY_FULL_DESIGN": "80000",
        }
        self.mock_context.list_devices.return_value = [mock_device]

        result = self.batteries.get_description_string("BAT0")
        self.assertEqual(
            result,
            "Battery BAT0 (ACME SuperBattery) is operating at 75.00% of design",
        )

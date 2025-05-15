#!/usr/bin/python3
# SPDX-License-Identifier: MIT

"""
This module contains unit tests for the display functions in the amd-debug-tools package.
"""

import logging
import unittest
from unittest.mock import patch, MagicMock
from amd_debug.display import Display


class TestDisplay(unittest.TestCase):
    """Unit tests for the Display class in amd-debug-tools"""

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(filename="/dev/null", level=logging.DEBUG)

    @patch("amd_debug.display.Context")
    @patch("amd_debug.display.read_file")
    @patch("os.path.exists")
    def test_display_initialization(self, mock_exists, mock_read_file, mock_context):
        """Test the Display class initialization and EDID retrieval"""
        # Mock the pyudev Context and its list_devices method
        mock_device = MagicMock()
        mock_device.device_path = "/devices/card0"
        mock_device.sys_path = "/sys/devices/card0"
        mock_device.sys_name = "card0"
        mock_context.return_value.list_devices.return_value = [mock_device]

        # Mock os.path.exists and read_file behavior
        mock_exists.side_effect = lambda path: "status" in path or "enabled" in path
        mock_read_file.side_effect = lambda path: (
            "connected" if "status" in path else "enabled"
        )

        # Initialize the Display class
        display = Display()

        # Verify the EDID paths are correctly set
        expected_edid = {"card0": "/sys/devices/card0/edid"}
        self.assertEqual(display.get_edid(), expected_edid)
        mock_context.assert_called_once()

    @patch("amd_debug.display.Context")
    def test_no_connected_displays(self, mock_context):
        """Test the Display class when no connected displays are found"""
        # Mock the pyudev Context to return no devices
        mock_context.return_value.list_devices.return_value = []

        # Initialize the Display class
        display = Display()

        # Verify the EDID dictionary is empty
        self.assertEqual(display.get_edid(), {})

    @patch("amd_debug.display.Context")
    def test_device_without_card(self, mock_context):
        """Test the Display class with a device that does not have 'card' in the name"""
        # Mock the pyudev Context to return a device without 'card' in the name
        mock_device = MagicMock()
        mock_device.device_path = "/devices/other_device"
        mock_device.sys_path = "/sys/devices/other_device"
        mock_device.sys_name = "other_device"
        mock_context.return_value.list_devices.return_value = [mock_device]

        # Initialize the Display class
        display = Display()

        # Verify the EDID dictionary is empty
        self.assertEqual(display.get_edid(), {})

    @patch("amd_debug.display.Context")
    @patch("amd_debug.display.read_file")
    @patch("os.path.exists")
    def test_device_not_enabled(self, mock_exists, mock_read_file, mock_context):
        """Test the Display class with a device that is not enabled"""
        # Mock the pyudev Context to return a device that is not enabled
        mock_device = MagicMock()
        mock_device.device_path = "/devices/card0"
        mock_device.sys_path = "/sys/devices/card0"
        mock_device.sys_name = "card0"
        mock_context.return_value.list_devices.return_value = [mock_device]

        # Mock os.path.exists and read_file behavior
        mock_exists.side_effect = lambda path: "status" in path or "enabled" in path
        mock_read_file.side_effect = lambda path: (
            "connected" if "status" in path else "disabled"
        )

        # Initialize the Display class
        display = Display()

        # Verify the EDID dictionary is empty
        self.assertEqual(display.get_edid(), {})

    @patch("amd_debug.display.Context")
    @patch("amd_debug.display.read_file")
    @patch("os.path.exists")
    def test_missing_status_file(self, mock_exists, mock_read_file, mock_context):
        """Test the Display class when the status file is missing"""
        # Mock the pyudev Context to return a device with a missing status file
        mock_device = MagicMock()
        mock_device.device_path = "/devices/card0"
        mock_device.sys_path = "/sys/devices/card0"
        mock_device.sys_name = "card0"
        mock_context.return_value.list_devices.return_value = [mock_device]

        # Mock os.path.exists to return False for the status file
        mock_exists.side_effect = lambda path: "enabled" in path
        mock_read_file.side_effect = lambda path: "enabled" if "enabled" in path else ""

        # Initialize the Display class
        display = Display()

        # Verify the EDID dictionary is empty
        self.assertEqual(display.get_edid(), {})

    @patch("amd_debug.display.Context")
    @patch("amd_debug.display.read_file")
    @patch("os.path.exists")
    def test_status_not_connected(self, mock_exists, mock_read_file, mock_context):
        """Test the Display class when the status file does not indicate connected"""
        # Mock the pyudev Context to return a device with a status file that does not indicate connected
        mock_device = MagicMock()
        mock_device.device_path = "/devices/card0"
        mock_device.sys_path = "/sys/devices/card0"
        mock_device.sys_name = "card0"
        mock_context.return_value.list_devices.return_value = [mock_device]

        # Mock os.path.exists and read_file behavior
        mock_exists.side_effect = lambda path: "status" in path or "enabled" in path
        mock_read_file.side_effect = lambda path: (
            "not_connected" if "status" in path else "enabled"
        )

        # Initialize the Display class
        display = Display()

        # Verify the EDID dictionary is empty
        self.assertEqual(display.get_edid(), {})

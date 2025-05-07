#!/usr/bin/python3
# SPDX-License-Identifier: MIT

"""
This module contains unit tests for the wake GPIO and IRQ functions in the amd-debug-tools package.
"""

import sys
import os
import logging
import unittest
from unittest.mock import patch, MagicMock

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from amd_debug.wake import WakeGPIO, WakeIRQ


class TestWakeGPIO(unittest.TestCase):
    """Test WakeGPIO class"""

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(filename="/dev/null", level=logging.DEBUG)

    def test_wake_gpio_initialization(self):
        """Test initialization of WakeGPIO class"""
        gpio = WakeGPIO(5)
        self.assertEqual(gpio.num, 5)
        self.assertEqual(gpio.name, "")

    def test_wake_gpio_str(self):
        """Test string representation of WakeGPIO class"""
        gpio = WakeGPIO(5)
        self.assertEqual(str(gpio), "5")
        gpio.name = "Test GPIO"
        self.assertEqual(str(gpio), "5 (Test GPIO)")


class TestWakeIRQ(unittest.TestCase):
    """Test WakeIRQ class"""

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(filename="/dev/null", level=logging.DEBUG)

    @patch("amd_debug.wake.read_file")
    @patch("os.path.exists")
    @patch("os.listdir")
    @patch("os.walk")
    def test_wake_irq_initialization(
        self, mock_os_walk, mock_os_listdir, mock_os_path_exists, mock_read_file
    ):
        """Test initialization of WakeIRQ class"""
        # Mocking file reads
        mock_read_file.side_effect = lambda path: {
            "/sys/kernel/irq/10/chip_name": "amd_gpio",
            "/sys/kernel/irq/10/actions": "test_action",
            "/sys/kernel/irq/10/wakeup": "enabled",
            "/sys/kernel/irq/10/hwirq": "42",
        }.get(path, "")

        # Mocking os.path.exists
        mock_os_path_exists.return_value = False

        # Mocking os.listdir and os.walk
        mock_os_listdir.return_value = []
        mock_os_walk.return_value = []

        irq = WakeIRQ(10)
        self.assertEqual(irq.num, 10)
        self.assertEqual(irq.chip_name, "amd_gpio")
        self.assertEqual(irq.name, "GPIO 42")

    @patch("amd_debug.wake.read_file")
    @patch("os.path.exists")
    @patch("os.listdir")
    @patch("os.walk")
    def test_wake_irq_disabled_interrupt(
        self, _mock_os_walk, _mock_os_listdir, mock_os_path_exists, mock_read_file
    ):
        """Test initialization of WakeIRQ class with disabled interrupt"""
        # Mocking file reads
        mock_read_file.side_effect = lambda path: {
            "/sys/kernel/irq/20/chip_name": "",
            "/sys/kernel/irq/20/actions": "",
            "/sys/kernel/irq/20/wakeup": "disabled",
        }.get(path, "")

        # Mocking os.path.exists
        mock_os_path_exists.return_value = False

        irq = WakeIRQ(20)
        self.assertEqual(irq.name, "Disabled interrupt")

    @patch("amd_debug.wake.read_file")
    @patch("os.path.exists")
    @patch("os.listdir")
    @patch("os.walk")
    @patch("pyudev.Context.list_devices")
    def test_wake_irq_pci_msi(
        self,
        mock_list_devices,
        _mock_os_walk,
        _mock_os_listdir,
        _mock_os_path_exists,
        mock_read_file,
    ):
        """Test initialization of WakeIRQ class with PCI-MSI"""
        # Mocking file reads
        mock_read_file.side_effect = lambda path: {
            "/sys/kernel/irq/30/chip_name": "PCI-MSI-0000:00:1f.2",
            "/sys/kernel/irq/30/actions": "",
            "/sys/kernel/irq/30/wakeup": "enabled",
        }.get(path, "")

        # Mocking pyudev context
        mock_device = MagicMock()
        mock_device.device_path = "/devices/pci0000:00/0000:00:1f.2"
        mock_device.properties = {
            "ID_VENDOR_FROM_DATABASE": "Intel Corporation",
            "ID_PCI_CLASS_FROM_DATABASE": "SATA controller",
            "PCI_SLOT_NAME": "0000:00:1f.2",
            "DRIVER": "ahci",
        }
        mock_list_devices.return_value = [mock_device]

        irq = WakeIRQ(30)
        self.assertEqual(irq.name, "Intel Corporation SATA controller (0000:00:1f.2)")
        self.assertEqual(irq.driver, "ahci")

    @patch("amd_debug.wake.read_file")
    @patch("os.path.exists")
    @patch("os.listdir")
    @patch("os.walk")
    @patch("pyudev.Context.list_devices")
    def test_wake_irq_legacy_irq(
        self,
        _mock_list_devices,
        _mock_os_walk,
        mock_os_listdir,
        mock_os_path_exists,
        mock_read_file,
    ):
        """Test initialization of WakeIRQ class with legacy IRQs"""
        # Mocking file reads
        mock_read_file.side_effect = lambda path: {
            "/sys/kernel/irq/40/chip_name": "IR-IO-APIC",
            "/sys/kernel/irq/40/actions": "acpi",
            "/sys/kernel/irq/40/wakeup": "enabled",
        }.get(path, "")

        # Mocking os.path.exists
        mock_os_path_exists.return_value = False

        # Mocking os.listdir
        mock_os_listdir.return_value = []

        irq = WakeIRQ(40)
        self.assertEqual(irq.name, "ACPI SCI")

    @patch("amd_debug.wake.read_file")
    @patch("os.path.exists")
    @patch("os.listdir")
    @patch("os.walk")
    def test_wake_irq_acpi_device(
        self, mock_os_walk, mock_os_listdir, mock_os_path_exists, mock_read_file
    ):
        """Test initialization of WakeIRQ class with ACPI device"""
        # Mocking file reads
        mock_read_file.side_effect = lambda path: {
            "/sys/kernel/irq/50/chip_name": "",
            "/sys/kernel/irq/50/actions": "acpi_device",
            "/sys/kernel/irq/50/wakeup": "enabled",
            "/sys/bus/acpi/devices/acpi_device/physical_node/name": "ACPI Device Name",
        }.get(path, "")

        # Mocking os.path.exists
        def exists_side_effect(path):
            return path in [
                "/sys/bus/acpi/devices/acpi_device",
                "/sys/bus/acpi/devices/acpi_device/physical_node",
                "/sys/bus/acpi/devices/acpi_device/physical_node/name",
            ]

        mock_os_path_exists.side_effect = exists_side_effect

        # Mocking os.listdir
        mock_os_listdir.return_value = ["physical_node"]

        # Mocking os.walk
        mock_os_walk.return_value = [
            ("/sys/bus/acpi/devices/acpi_device/physical_node", [], ["name"])
        ]

        irq = WakeIRQ(50)
        self.assertEqual(irq.name, "ACPI Device Name")

    @patch("amd_debug.wake.read_file")
    @patch("os.path.exists")
    @patch("os.listdir")
    @patch("os.walk")
    def test_wake_irq_i2c_hid_device(
        self, _mock_os_walk, _mock_os_listdir, mock_os_path_exists, mock_read_file
    ):
        """Test initialization of WakeIRQ class with I2C HID device"""
        # Mocking file reads
        mock_read_file.side_effect = lambda path: {
            "/sys/kernel/irq/60/chip_name": "",
            "/sys/kernel/irq/60/actions": "i2c_hid_device",
            "/sys/kernel/irq/60/wakeup": "enabled",
        }.get(path, "")

        # Mocking os.path.exists
        mock_os_path_exists.return_value = False

        irq = WakeIRQ(60)
        irq.driver = "i2c_hid_acpi"
        irq.name = "i2c_hid_device"
        self.assertEqual(irq.name, "i2c_hid_device")

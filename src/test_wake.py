#!/usr/bin/python3
# SPDX-License-Identifier: MIT

"""
This module contains unit tests for the wake GPIO and IRQ functions in the amd-debug-tools package.
"""

import logging
import unittest
from unittest.mock import patch, MagicMock

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

    @patch("amd_debug.wake.read_file")
    @patch("os.path.exists")
    @patch("os.listdir")
    @patch("os.walk")
    def test_wake_irq_read_file_errors(
        self, _mock_os_walk, _mock_os_listdir, mock_os_path_exists, mock_read_file
    ):
        """Test that read_file errors for chip_name/actions/wakeup are handled"""
        mock_read_file.side_effect = FileNotFoundError()
        mock_os_path_exists.return_value = False

        irq = WakeIRQ(70)
        self.assertEqual(irq.chip_name, "")
        self.assertEqual(irq.actions, "")
        self.assertEqual(irq.name, "")
        self.assertEqual(irq.driver, "")

    @patch("amd_debug.wake.read_file")
    @patch("os.path.exists")
    @patch("os.listdir")
    @patch("os.walk")
    def test_wake_irq_amd_gpio_hwirq_error(
        self, _mock_os_walk, _mock_os_listdir, mock_os_path_exists, mock_read_file
    ):
        """Test amd_gpio chip with hwirq read failure"""
        def _read(path):
            if path.endswith("chip_name"):
                return "amd_gpio"
            if path.endswith("hwirq"):
                raise PermissionError()
            return ""

        mock_read_file.side_effect = _read
        mock_os_path_exists.return_value = False

        irq = WakeIRQ(71)
        self.assertEqual(irq.name, "GPIO (unknown)")

    @patch("amd_debug.wake.read_file")
    @patch("os.path.exists")
    @patch("os.listdir")
    @patch("os.walk")
    def test_wake_irq_legacy_i8042(
        self, _mock_os_walk, _mock_os_listdir, mock_os_path_exists, mock_read_file
    ):
        """Test IR-IO-APIC with i8042 action"""
        mock_read_file.side_effect = lambda path: {
            "/sys/kernel/irq/72/chip_name": "IR-IO-APIC",
            "/sys/kernel/irq/72/actions": "i8042",
            "/sys/kernel/irq/72/wakeup": "enabled",
        }.get(path, "")
        mock_os_path_exists.return_value = False
        irq = WakeIRQ(72)
        self.assertEqual(irq.name, "PS/2 controller")
        self.assertEqual(irq.actions, "")

    @patch("amd_debug.wake.read_file")
    @patch("os.path.exists")
    @patch("os.listdir")
    @patch("os.walk")
    def test_wake_irq_legacy_pinctrl(
        self, _mock_os_walk, _mock_os_listdir, mock_os_path_exists, mock_read_file
    ):
        """Test IR-IO-APIC with pinctrl_amd action"""
        mock_read_file.side_effect = lambda path: {
            "/sys/kernel/irq/73/chip_name": "IR-IO-APIC",
            "/sys/kernel/irq/73/actions": "pinctrl_amd",
            "/sys/kernel/irq/73/wakeup": "enabled",
        }.get(path, "")
        mock_os_path_exists.return_value = False
        irq = WakeIRQ(73)
        self.assertEqual(irq.name, "GPIO Controller")

    @patch("amd_debug.wake.read_file")
    @patch("os.path.exists")
    @patch("os.listdir")
    @patch("os.walk")
    def test_wake_irq_legacy_rtc(
        self, _mock_os_walk, _mock_os_listdir, mock_os_path_exists, mock_read_file
    ):
        """Test IR-IO-APIC with rtc0 action"""
        mock_read_file.side_effect = lambda path: {
            "/sys/kernel/irq/74/chip_name": "IR-IO-APIC",
            "/sys/kernel/irq/74/actions": "rtc0",
            "/sys/kernel/irq/74/wakeup": "enabled",
        }.get(path, "")
        mock_os_path_exists.return_value = False
        irq = WakeIRQ(74)
        self.assertEqual(irq.name, "RTC")

    @patch("amd_debug.wake.read_file")
    @patch("os.path.exists")
    @patch("os.listdir")
    @patch("os.walk")
    def test_wake_irq_legacy_timer(
        self, _mock_os_walk, _mock_os_listdir, mock_os_path_exists, mock_read_file
    ):
        """Test IR-IO-APIC with timer action"""
        mock_read_file.side_effect = lambda path: {
            "/sys/kernel/irq/75/chip_name": "IR-IO-APIC",
            "/sys/kernel/irq/75/actions": "timer",
            "/sys/kernel/irq/75/wakeup": "enabled",
        }.get(path, "")
        mock_os_path_exists.return_value = False
        irq = WakeIRQ(75)
        self.assertEqual(irq.name, "Timer")

    @patch("amd_debug.wake.read_file")
    @patch("os.path.exists")
    @patch("os.listdir")
    @patch("os.walk")
    @patch("pyudev.Context.list_devices")
    def test_wake_irq_pci_msi_interface_fallback(
        self,
        mock_list_devices,
        _mock_os_walk,
        _mock_os_listdir,
        mock_os_path_exists,
        mock_read_file,
    ):
        """PCI-MSI device with no PCI_CLASS, falls back to PCI_INTERFACE"""
        mock_read_file.side_effect = lambda path: {
            "/sys/kernel/irq/76/chip_name": "PCI-MSI-0000:00:1f.3",
            "/sys/kernel/irq/76/actions": "",
            "/sys/kernel/irq/76/wakeup": "enabled",
        }.get(path, "")
        mock_os_path_exists.return_value = False

        mock_device = MagicMock()
        mock_device.device_path = "/devices/pci0000:00/0000:00:1f.3"
        mock_device.properties = {
            "ID_VENDOR_FROM_DATABASE": "Vendor",
            "ID_PCI_INTERFACE_FROM_DATABASE": "Interface Desc",
            "PCI_SLOT_NAME": "0000:00:1f.3",
            "DRIVER": "drv",
        }
        mock_list_devices.return_value = [mock_device]

        irq = WakeIRQ(76)
        self.assertEqual(irq.name, "Vendor Interface Desc (0000:00:1f.3)")

    @patch("amd_debug.wake.read_file")
    @patch("os.path.exists")
    @patch("os.listdir")
    @patch("os.walk")
    @patch("pyudev.Context.list_devices")
    def test_wake_irq_pci_msi_no_match(
        self,
        mock_list_devices,
        _mock_os_walk,
        _mock_os_listdir,
        mock_os_path_exists,
        mock_read_file,
    ):
        """PCI-MSI where no pci device matches the BDF"""
        mock_read_file.side_effect = lambda path: {
            "/sys/kernel/irq/77/chip_name": "PCI-MSI-0000:99:99.9",
            "/sys/kernel/irq/77/actions": "",
            "/sys/kernel/irq/77/wakeup": "enabled",
        }.get(path, "")
        mock_os_path_exists.return_value = False

        mock_device = MagicMock()
        mock_device.device_path = "/devices/pci0000:00/0000:00:1f.2"
        mock_list_devices.return_value = [mock_device]

        irq = WakeIRQ(77)
        self.assertEqual(irq.name, "")

    @patch("amd_debug.wake.read_file")
    @patch("os.path.exists")
    @patch("os.listdir")
    @patch("os.walk")
    @patch("os.readlink")
    def test_wake_irq_acpi_device_with_driver(
        self,
        mock_readlink,
        mock_os_walk,
        mock_os_listdir,
        mock_os_path_exists,
        mock_read_file,
    ):
        """Test ACPI device resolution with driver symlink"""
        mock_read_file.side_effect = lambda path: {
            "/sys/kernel/irq/78/chip_name": "",
            "/sys/kernel/irq/78/actions": "ACPI0001",
            "/sys/kernel/irq/78/wakeup": "enabled",
            "/sys/bus/acpi/devices/ACPI0001/physical_node/name": "ACPI0001",
        }.get(path, "")

        def exists_side_effect(path):
            return path in (
                "/sys/bus/acpi/devices/ACPI0001",
                "/sys/bus/acpi/devices/ACPI0001/physical_node/driver",
            )

        mock_os_path_exists.side_effect = exists_side_effect
        mock_os_listdir.return_value = ["physical_node"]
        mock_os_walk.return_value = [
            ("/sys/bus/acpi/devices/ACPI0001/physical_node", [], ["name"])
        ]
        mock_readlink.return_value = "/sys/bus/i2c/drivers/i2c_hid_acpi"

        irq = WakeIRQ(78)
        self.assertEqual(irq.driver, "i2c_hid_acpi")
        # name == actions, plus i2c_hid_acpi driver -> appended
        self.assertEqual(irq.name, "ACPI0001 I2C HID device")

    @patch("amd_debug.wake.read_file")
    @patch("os.path.exists")
    @patch("os.listdir")
    @patch("os.walk")
    @patch("os.readlink")
    def test_wake_irq_acpi_driver_readlink_error(
        self,
        mock_readlink,
        mock_os_walk,
        mock_os_listdir,
        mock_os_path_exists,
        mock_read_file,
    ):
        """ACPI driver symlink readlink raises OSError; driver stays empty"""
        mock_read_file.side_effect = lambda path: {
            "/sys/kernel/irq/79/chip_name": "",
            "/sys/kernel/irq/79/actions": "ACPI0002",
            "/sys/kernel/irq/79/wakeup": "enabled",
            "/sys/bus/acpi/devices/ACPI0002/physical_node/name": "MyDev",
        }.get(path, "")

        def exists_side_effect(path):
            return path in (
                "/sys/bus/acpi/devices/ACPI0002",
                "/sys/bus/acpi/devices/ACPI0002/physical_node/driver",
            )

        mock_os_path_exists.side_effect = exists_side_effect
        mock_os_listdir.return_value = ["physical_node"]
        mock_os_walk.return_value = [
            ("/sys/bus/acpi/devices/ACPI0002/physical_node", [], ["name"])
        ]
        mock_readlink.side_effect = OSError()

        irq = WakeIRQ(79)
        self.assertEqual(irq.name, "MyDev")
        self.assertEqual(irq.driver, "")

    @patch("amd_debug.wake.read_file")
    @patch("os.path.exists")
    @patch("os.listdir")
    @patch("os.walk")
    def test_wake_irq_acpi_name_read_error(
        self, mock_os_walk, mock_os_listdir, mock_os_path_exists, mock_read_file
    ):
        """ACPI name file read raises; name stays empty"""
        def _read(path):
            if path.endswith("/name"):
                raise FileNotFoundError()
            return {
                "/sys/kernel/irq/80/chip_name": "",
                "/sys/kernel/irq/80/actions": "ACPI0003",
                "/sys/kernel/irq/80/wakeup": "enabled",
            }.get(path, "")

        mock_read_file.side_effect = _read

        def exists_side_effect(path):
            return path == "/sys/bus/acpi/devices/ACPI0003"

        mock_os_path_exists.side_effect = exists_side_effect
        mock_os_listdir.return_value = ["physical_node"]
        mock_os_walk.return_value = [
            ("/sys/bus/acpi/devices/ACPI0003/physical_node", [], ["name"])
        ]

        irq = WakeIRQ(80)
        self.assertEqual(irq.name, "")

    @patch("amd_debug.wake.read_file")
    @patch("os.path.exists")
    @patch("os.listdir")
    @patch("os.walk")
    def test_wake_irq_acpi_path_traversal(
        self, mock_os_walk, mock_os_listdir, mock_os_path_exists, mock_read_file
    ):
        """A traversal sequence in actions must not escape the ACPI device dir"""
        mock_read_file.side_effect = lambda path: {
            "/sys/kernel/irq/82/chip_name": "",
            "/sys/kernel/irq/82/actions": "../../foo",
            "/sys/kernel/irq/82/wakeup": "enabled",
        }.get(path, "")

        checked = []

        def exists_side_effect(path):
            checked.append(path)
            return False

        mock_os_path_exists.side_effect = exists_side_effect

        irq = WakeIRQ(82)

        # The action name must be reduced to its basename before being joined
        # under the ACPI devices directory, so no ".." component is ever used.
        acpi_checks = [
            p for p in checked if p.startswith("/sys/bus/acpi/devices")
        ]
        self.assertIn("/sys/bus/acpi/devices/foo", acpi_checks)
        for p in acpi_checks:
            self.assertNotIn("..", p)
        # os.walk must never run since the sanitised path does not exist.
        mock_os_walk.assert_not_called()
        self.assertEqual(irq.name, "")

    def test_wake_irq_str(self):
        """Test __str__ of WakeIRQ"""
        with patch("amd_debug.wake.read_file", side_effect=FileNotFoundError()), \
             patch("os.path.exists", return_value=False):
            irq = WakeIRQ(81)
        irq.name = "Foo"
        irq.actions = "bar"
        self.assertEqual(str(irq), "Foo (bar)")
        irq.actions = ""
        self.assertEqual(str(irq), "Foo")

#!/usr/bin/python3
# SPDX-License-Identifier: MIT

"""
This module contains unit tests for the AMD storage related prerequisite
functions in the amd-debug-tools package.
"""

import logging
import unittest
from unittest.mock import patch, MagicMock

from amd_debug.prereq.amd_storage import AmdStorageChecks
from amd_debug.failures import (
    AcpiNvmeStorageD3Enable,
    DevSlpDiskIssue,
    DevSlpHostIssue,
    MissingPcieHotplug,
    MissingThunderbolt,
    MissingXhciHcd,
    WCN6855Bug,
)


class FakeAmdStorageChecks(AmdStorageChecks):
    """Minimal stand-in for the prerequisite validator"""

    def __init__(self):
        self.db = MagicMock()
        self.failures = []
        self.pyudev = MagicMock()
        self.kernel_log = MagicMock()


class TestAmdStorageChecks(unittest.TestCase):
    """Unit tests for the AMD storage checks"""

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(filename="/dev/null", level=logging.DEBUG)

    def setUp(self):
        """Set up a mock context for testing"""
        self.validator = FakeAmdStorageChecks()

    def _mock_devices(self, nvme=None, ahci=False, sata=False):
        """Configure the pyudev mock to return the requested devices"""

        def list_devices(**kwargs):
            if kwargs.get("subsystem") == "pci" and kwargs.get("DRIVER") == "nvme":
                return nvme or []
            if kwargs.get("subsystem") == "pci" and kwargs.get("DRIVER") == "ahci":
                return [MagicMock()] if ahci else []
            if kwargs.get("subsystem") == "block" and kwargs.get("ID_BUS") == "ata":
                return [MagicMock()] if sata else []
            return []

        self.validator.pyudev.list_devices.side_effect = list_devices

    @patch("amd_debug.prereq.amd_storage.minimum_kernel", return_value=False)
    def test_check_storage_nvme_valid(self, _mock_kernel):
        """Test check_storage with an NVMe device set for simple suspend"""
        nvme = MagicMock()
        nvme.properties = {
            "PCI_SLOT_NAME": "0000:02:00.0",
            "ID_VENDOR_FROM_DATABASE": "Samsung",
            "ID_MODEL_FROM_DATABASE": "980",
        }
        self._mock_devices(nvme=[nvme])
        self.validator.kernel_log.match_pattern.return_value = True
        result = self.validator.check_storage()
        self.assertTrue(result)
        self.assertEqual(self.validator.failures, [])
        self.validator.db.record_prereq.assert_any_call(
            "NVME Samsung 980 is configured for s2idle in BIOS", "✅"
        )

    @patch("amd_debug.prereq.amd_storage.minimum_kernel", return_value=False)
    def test_check_storage_nvme_invalid(self, _mock_kernel):
        """Test check_storage with an NVMe device not set for simple suspend"""
        nvme = MagicMock()
        nvme.properties = {
            "PCI_SLOT_NAME": "0000:02:00.0",
            "ID_VENDOR_FROM_DATABASE": "Samsung",
            "ID_MODEL_FROM_DATABASE": "980",
        }
        self._mock_devices(nvme=[nvme])
        self.validator.kernel_log.match_pattern.return_value = False
        result = self.validator.check_storage()
        self.assertFalse(result)
        self.assertTrue(
            any(isinstance(f, AcpiNvmeStorageD3Enable) for f in self.validator.failures)
        )

    @patch("amd_debug.prereq.amd_storage.minimum_kernel", return_value=False)
    def test_check_storage_sata_valid(self, _mock_kernel):
        """Test check_storage with SATA supporting DevSlp"""
        self._mock_devices(sata=True, ahci=True)

        def match_pattern(pattern):
            if "Dev-Sleep" in pattern or "sadm" in pattern:
                return "matched"
            return ""

        self.validator.kernel_log.match_pattern.side_effect = match_pattern
        result = self.validator.check_storage()
        self.assertTrue(result)
        self.validator.db.record_prereq.assert_any_call(
            "SATA supports DevSlp feature", "✅"
        )

    @patch("amd_debug.prereq.amd_storage.minimum_kernel", return_value=False)
    def test_check_storage_sata_without_ahci(self, _mock_kernel):
        """Test check_storage with SATA but no AHCI controller

        Without an AHCI controller the SATA devices can't use DevSlp, so
        the check fails.
        """
        self._mock_devices(sata=True)
        self.validator.kernel_log.match_pattern.return_value = ""
        result = self.validator.check_storage()
        self.assertFalse(result)
        self.assertTrue(
            any(isinstance(f, DevSlpDiskIssue) for f in self.validator.failures)
        )

    @patch("amd_debug.prereq.amd_storage.minimum_kernel", return_value=False)
    def test_check_storage_sata_invalid(self, _mock_kernel):
        """Test check_storage with SATA not supporting DevSlp"""
        self._mock_devices(sata=True)
        self.validator.kernel_log.match_pattern.return_value = ""
        result = self.validator.check_storage()
        self.assertFalse(result)
        self.assertTrue(
            any(isinstance(f, DevSlpDiskIssue) for f in self.validator.failures)
        )
        self.validator.db.record_prereq.assert_any_call(
            "SATA does not support DevSlp feature", "❌"
        )

    @patch("amd_debug.prereq.amd_storage.minimum_kernel", return_value=False)
    def test_check_storage_ahci_valid(self, _mock_kernel):
        """Test check_storage with AHCI configured for DevSlp"""
        self._mock_devices(ahci=True)

        def match_pattern(pattern):
            if "sadm" in pattern:
                return "matched"
            return ""

        self.validator.kernel_log.match_pattern.side_effect = match_pattern
        result = self.validator.check_storage()
        self.assertTrue(result)
        self.validator.db.record_prereq.assert_any_call(
            "AHCI is configured for DevSlp in BIOS", "✅"
        )

    @patch("amd_debug.prereq.amd_storage.minimum_kernel", return_value=False)
    def test_check_storage_ahci_invalid(self, _mock_kernel):
        """Test check_storage with AHCI not configured for DevSlp"""
        self._mock_devices(ahci=True)
        self.validator.kernel_log.match_pattern.return_value = ""
        result = self.validator.check_storage()
        # The AHCI problem is reported, but the overall result depends on
        # the SATA state as well
        self.assertTrue(
            any(isinstance(f, DevSlpHostIssue) for f in self.validator.failures)
        )
        self.validator.db.record_prereq.assert_any_call(
            "AHCI is not configured for DevSlp in BIOS", "🚦"
        )

    @patch("amd_debug.prereq.amd_storage.minimum_kernel", return_value=False)
    def test_check_storage_no_devices(self, _mock_kernel):
        """Test check_storage with no storage devices at all"""
        self._mock_devices()
        self.validator.kernel_log.match_pattern.return_value = ""
        result = self.validator.check_storage()
        self.assertTrue(result)
        self.assertEqual(self.validator.failures, [])

    def test_check_wcn6855_bug_no_bug(self):
        """Test check_wcn6855_bug with a new enough firmware version"""
        self.validator.kernel_log.match_pattern.side_effect = [
            "ath11k_pci 0000:03:00.0: firmware build id 1.2.3.37",
            "ath11k_pci fw_build_id 1.2.3.37",
        ]
        result = self.validator.check_wcn6855_bug()
        self.assertTrue(result)
        self.assertEqual(self.validator.failures, [])

    def test_check_wcn6855_bug_with_bug(self):
        """Test check_wcn6855_bug with an old firmware version"""
        self.validator.kernel_log.match_pattern.side_effect = [
            "ath11k_pci 0000:03:00.0: firmware build id 1.2.3.20",
            "ath11k_pci fw_build_id 1.2.3.20",
        ]
        result = self.validator.check_wcn6855_bug()
        self.assertTrue(result)
        self.assertTrue(any(isinstance(f, WCN6855Bug) for f in self.validator.failures))

    def test_check_wcn6855_bug_no_device(self):
        """Test check_wcn6855_bug without a WCN6855 device"""
        self.validator.kernel_log.match_pattern.return_value = ""
        result = self.validator.check_wcn6855_bug()
        self.assertTrue(result)
        self.assertEqual(self.validator.failures, [])

    def test_check_usb3_no_devices(self):
        """Test check_usb3 with no USB3 controllers"""
        self._mock_devices()
        result = self.validator.check_usb3()
        self.assertTrue(result)
        self.assertEqual(self.validator.failures, [])

    def test_check_usb3_driver_missing(self):
        """Test check_usb3 when the xhci_hcd driver isn't bound"""
        dev = MagicMock()
        dev.properties = {"PCI_SLOT_NAME": "0000:00:14.0", "DRIVER": None}
        self.validator.pyudev.list_devices.return_value = [dev]
        result = self.validator.check_usb3()
        self.assertFalse(result)
        self.assertTrue(
            any(isinstance(f, MissingXhciHcd) for f in self.validator.failures)
        )

    def test_check_usb3_driver_present(self):
        """Test check_usb3 with the xhci_hcd driver bound"""
        dev = MagicMock()
        dev.properties = {"PCI_SLOT_NAME": "0000:00:14.0", "DRIVER": "xhci_hcd"}
        self.validator.pyudev.list_devices.return_value = [dev]
        result = self.validator.check_usb3()
        self.assertTrue(result)
        self.assertEqual(self.validator.failures, [])
        self.validator.db.record_prereq.assert_any_call(
            "USB3 driver `xhci_hcd` bound to 0000:00:14.0", "✅"
        )

    def test_check_usb4_no_devices(self):
        """Test check_usb4 with no USB4 routers"""
        self._mock_devices()
        result = self.validator.check_usb4()
        self.assertTrue(result)
        self.assertEqual(self.validator.failures, [])

    def test_check_usb4_driver_missing(self):
        """Test check_usb4 when the thunderbolt driver isn't bound"""
        dev = MagicMock()
        dev.properties = {"PCI_SLOT_NAME": "0000:00:1c.0", "DRIVER": None}
        self.validator.pyudev.list_devices.return_value = [dev]
        result = self.validator.check_usb4()
        self.assertFalse(result)
        self.assertTrue(
            any(isinstance(f, MissingThunderbolt) for f in self.validator.failures)
        )

    def test_check_usb4_driver_present(self):
        """Test check_usb4 with the thunderbolt driver bound"""
        dev = MagicMock()
        dev.properties = {"PCI_SLOT_NAME": "0000:00:1c.0", "DRIVER": "thunderbolt"}
        self.validator.pyudev.list_devices.return_value = [dev]
        result = self.validator.check_usb4()
        self.assertTrue(result)
        self.assertEqual(self.validator.failures, [])
        self.validator.db.record_prereq.assert_any_call(
            "USB4 driver `thunderbolt` bound to 0000:00:1c.0", "✅"
        )

    @patch("amd_debug.prereq.amd_storage.os.path.exists")
    def test_check_pcie_hotplug_loaded(self, mock_exists):
        """Test check_pcie_hotplug when the driver is loaded"""
        mock_exists.return_value = True
        result = self.validator.check_pcie_hotplug()
        self.assertTrue(result)
        self.assertEqual(self.validator.failures, [])

    @patch("amd_debug.prereq.amd_storage.os.path.exists")
    def test_check_pcie_hotplug_missing(self, mock_exists):
        """Test check_pcie_hotplug when the driver is missing"""
        mock_exists.return_value = False
        result = self.validator.check_pcie_hotplug()
        self.assertFalse(result)
        self.assertTrue(
            any(isinstance(f, MissingPcieHotplug) for f in self.validator.failures)
        )


if __name__ == "__main__":
    unittest.main()

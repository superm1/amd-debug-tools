#!/usr/bin/python3
# SPDX-License-Identifier: MIT

"""
This module contains unit tests for the vendor independent prerequisite functions in the
amd-debug-tools package.
"""

import logging
import subprocess
import unittest
from unittest.mock import patch, MagicMock, mock_open

from amd_debug.prereq.base import PrerequisiteValidator
from amd_debug.failures import *
from amd_debug.common import apply_prefix_wrapper, BIT


class TestPrerequisiteValidator(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(filename="/dev/null", level=logging.DEBUG)

    @patch("amd_debug.prereq.base.is_root", return_value=True)
    @patch("amd_debug.prereq.base.get_kernel_log")
    @patch("amd_debug.prereq.base.get_distro", return_value="Ubuntu")
    @patch("amd_debug.prereq.base.read_file", return_value="mocked_cmdline")
    @patch("amd_debug.prereq.base.pyudev.Context")
    @patch("amd_debug.prereq.base.SleepDatabase")
    def setUp(
        self,
        MockSleepDatabase,
        MockPyudev,
        _mock_read_file,
        _mock_get_distro,
        mock_get_kernel_log,
        _mock_is_root,
    ):
        self.mock_db = MockSleepDatabase.return_value
        self.mock_pyudev = MockPyudev.return_value
        self.mock_kernel_log = mock_get_kernel_log.return_value
        self.validator = PrerequisiteValidator(tool_debug=True)

    @patch("amd_debug.prereq.system.os.path.exists", return_value=True)
    def test_capture_logind_percentage(self, _mock_exists):
        """Test capture_logind tolerates a '%' in logind.conf values"""
        logind = "[Login]\nRuntimeDirectorySize=20%\n"
        with patch("builtins.open", mock_open(read_data=logind)):
            self.validator.capture_logind()
        self.mock_db.record_debug.assert_any_call("LOGIND: configuration changes:")
        self.mock_db.record_debug.assert_any_call("\truntimedirectorysize: 20%")

    def test_check_sleep_mode_not_supported(self):
        """Test check_sleep_mode with no sleep mode support"""
        with patch("os.path.exists", return_value=False):
            result = self.validator.check_sleep_mode()
            self.assertFalse(result)

    def test_check_sleep_mode_s2idle(self):
        """Test check_sleep_mode with s2idle mode"""
        with patch("os.path.exists", return_value=True), patch(
            "amd_debug.prereq.system.read_file", return_value="[s2idle]"
        ):
            result = self.validator.check_sleep_mode()
            self.assertTrue(result)

    @patch("amd_debug.prereq.system.read_file")
    def test_check_taint_not_tainted(self, mock_read_file):
        """Test check_taint when the kernel is not tainted"""
        mock_read_file.return_value = "0"
        result = self.validator.check_taint()
        self.assertTrue(result)
        self.assertFalse(
            any(isinstance(f, TaintedKernel) for f in self.validator.failures)
        )

    @patch("amd_debug.prereq.system.read_file")
    def test_check_taint_tainted(self, mock_read_file):
        """Test check_taint when the kernel is tainted"""
        mock_read_file.return_value = str(
            BIT(9) | 1
        )  # Kernel warnings ignored, other taint present
        result = self.validator.check_taint()
        self.assertTrue(result)
        self.assertTrue(
            any(isinstance(f, TaintedKernel) for f in self.validator.failures)
        )

    @patch("amd_debug.prereq.system.read_file")
    def test_check_taint_file_not_found(self, mock_read_file):
        """Test check_taint when the tainted file is not found"""
        mock_read_file.side_effect = FileNotFoundError
        with self.assertRaises(FileNotFoundError):
            self.validator.check_taint()

    @patch("amd_debug.prereq.system.read_file")
    def test_check_taint_invalid_value(self, mock_read_file):
        """Test check_taint when the tainted file contains invalid data"""
        mock_read_file.return_value = "invalid"
        with self.assertRaises(ValueError):
            self.validator.check_taint()

    @patch("amd_debug.prereq.system.read_file")
    def test_check_smt_not_supported(self, mock_read_file):
        """Test check_smt when SMT is not supported"""
        mock_read_file.side_effect = ["notsupported"]
        result = self.validator.check_smt()
        self.assertTrue(result)
        self.mock_db.record_debug.assert_called_with("SMT control: notsupported")

    @patch("amd_debug.prereq.system.read_file")
    def test_check_smt_disabled(self, mock_read_file):
        """Test check_smt when SMT is disabled"""
        mock_read_file.side_effect = ["on", "0"]
        result = self.validator.check_smt()
        self.assertFalse(result)
        self.assertTrue(
            any(isinstance(f, SMTNotEnabled) for f in self.validator.failures)
        )
        self.mock_db.record_prereq.assert_called_with("SMT is not enabled", "❌")

    @patch("amd_debug.prereq.system.read_file")
    def test_check_smt_enabled(self, mock_read_file):
        """Test check_smt when SMT is enabled"""
        mock_read_file.side_effect = ["on", "1"]
        result = self.validator.check_smt()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_called_with("SMT enabled", "✅")

    @patch("amd_debug.prereq.acpi.os.walk")
    @patch(
        "amd_debug.prereq.acpi.open",
        new_callable=unittest.mock.mock_open,
        read_data=b"mocked_data",
    )
    @patch("amd_debug.prereq.acpi.tempfile.mkdtemp", return_value="/mocked/tempdir")
    @patch("amd_debug.prereq.acpi.subprocess.check_call")
    @patch("amd_debug.prereq.acpi.shutil.rmtree")
    def test_capture_acpi_success(
        self, mock_rmtree, mock_check_call, mock_mkdtemp, mock_open, mock_walk
    ):
        """Test capture_acpi when ACPI tables are successfully captured"""
        mock_walk.return_value = [
            ("/sys/firmware/acpi/tables", [], ["SSDT1", "IVRS", "OTHER"]),
        ]
        result = self.validator.capture_acpi()
        self.assertTrue(result)
        mock_check_call.assert_called_with(
            [
                "iasl",
                "-p",
                "/mocked/tempdir/acpi",
                "-d",
                "/sys/firmware/acpi/tables/IVRS",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.mock_db.record_debug_file.assert_called_with("/mocked/tempdir/acpi.dsl")
        mock_rmtree.assert_called_with("/mocked/tempdir")

    @patch("amd_debug.prereq.acpi.os.walk")
    @patch(
        "amd_debug.prereq.acpi.open",
        new_callable=unittest.mock.mock_open,
        read_data=b"mocked_data",
    )
    @patch("amd_debug.prereq.acpi.tempfile.mkdtemp", return_value="/mocked/tempdir")
    @patch(
        "amd_debug.prereq.acpi.subprocess.check_call",
        side_effect=subprocess.CalledProcessError(1, "iasl"),
    )
    @patch("amd_debug.prereq.acpi.shutil.rmtree")
    def test_capture_acpi_subprocess_error(
        self, mock_rmtree, mock_check_call, mock_mkdtemp, mock_open, mock_walk
    ):
        """Test capture_acpi when subprocess.check_call raises an error"""
        mock_walk.return_value = [
            ("/sys/firmware/acpi/tables", [], ["SSDT1", "IVRS", "OTHER"]),
        ]
        result = self.validator.capture_acpi()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_called_with(
            "Failed to capture ACPI table: None", "👀"
        )
        mock_rmtree.assert_called_with("/mocked/tempdir")

    @patch("amd_debug.prereq.acpi.os.walk")
    @patch(
        "amd_debug.prereq.acpi.open",
        new_callable=unittest.mock.mock_open,
        read_data=b"mocked_data",
    )
    @patch("amd_debug.prereq.acpi.tempfile.mkdtemp", return_value="/mocked/tempdir")
    @patch("amd_debug.prereq.acpi.subprocess.check_call")
    @patch("amd_debug.prereq.acpi.shutil.rmtree")
    def test_capture_acpi_no_matching_files(
        self, mock_rmtree, mock_check_call, mock_mkdtemp, mock_open, mock_walk
    ):
        """Test capture_acpi when no matching ACPI tables are found"""
        mock_walk.return_value = [
            ("/sys/firmware/acpi/tables", [], ["OTHER"]),
        ]
        result = self.validator.capture_acpi()
        self.assertTrue(result)
        mock_check_call.assert_not_called()
        self.mock_db.record_debug_file.assert_not_called()
        mock_rmtree.assert_not_called()

    @patch("amd_debug.prereq.acpi.os.path.exists")
    @patch("amd_debug.prereq.acpi.read_file")
    @patch("amd_debug.prereq.acpi.os.readlink")
    def test_map_acpi_path_with_devices(
        self, mock_readlink, mock_read_file, mock_path_exists
    ):
        """Test map_acpi_path with valid ACPI devices"""
        mock_path_exists.side_effect = lambda p: "path" in p or "driver" in p
        mock_read_file.side_effect = lambda p: "mocked_path" if "path" in p else "1"
        mock_readlink.return_value = "/mocked/driver"
        self.mock_pyudev.list_devices.return_value = [
            MagicMock(sys_path="/sys/devices/acpi/device1", sys_name="device1"),
            MagicMock(sys_path="/sys/devices/acpi/device2", sys_name="device2"),
        ]

        result = self.validator.map_acpi_path()
        self.assertTrue(result)
        self.mock_db.record_debug.assert_called_with(
            "ACPI name | ACPI path | Kernel driver\ndevice1 | mocked_path | driver\ndevice2 | mocked_path | driver\n"
        )

    @patch("amd_debug.prereq.acpi.os.path.exists")
    @patch("amd_debug.prereq.acpi.read_file")
    def test_map_acpi_path_no_devices(self, mock_read_file, mock_path_exists):
        """Test map_acpi_path with no valid ACPI devices"""
        mock_path_exists.return_value = False
        self.mock_pyudev.list_devices.return_value = []

        result = self.validator.map_acpi_path()
        self.assertTrue(result)

    @patch("amd_debug.prereq.acpi.os.path.exists")
    @patch("amd_debug.prereq.acpi.read_file")
    def test_map_acpi_path_device_with_status_zero(
        self, mock_read_file, mock_path_exists
    ):
        """Test map_acpi_path when a device has status 0"""
        mock_path_exists.side_effect = lambda p: "path" in p or "status" in p
        mock_read_file.side_effect = lambda p: "mocked_path" if "path" in p else "0"
        self.mock_pyudev.list_devices.return_value = [
            MagicMock(sys_path="/sys/devices/acpi/device1", sys_name="device1")
        ]

        result = self.validator.map_acpi_path()
        self.assertTrue(result)

    @patch("amd_debug.prereq.acpi.os.path.exists")
    @patch("amd_debug.prereq.acpi.read_file")
    def test_map_acpi_path_device_without_driver(
        self, mock_read_file, mock_path_exists
    ):
        """Test map_acpi_path when a device does not have a driver"""
        mock_path_exists.side_effect = lambda p: "path" in p
        mock_read_file.side_effect = lambda p: "mocked_path"
        self.mock_pyudev.list_devices.return_value = [
            MagicMock(sys_path="/sys/devices/acpi/device1", sys_name="device1")
        ]

        result = self.validator.map_acpi_path()
        self.assertTrue(result)
        self.mock_db.record_debug.assert_called_with(
            "ACPI name | ACPI path | Kernel driver\ndevice1 | mocked_path | None\n"
        )

    @patch("amd_debug.prereq.devices.read_file")
    @patch("amd_debug.prereq.devices.os.path.exists")
    def test_capture_pci_acpi_with_acpi_path(self, mock_path_exists, mock_read_file):
        """Test capture_pci_acpi when ACPI paths exist for devices"""
        mock_path_exists.side_effect = lambda p: "firmware_node/path" in p
        mock_read_file.side_effect = lambda p: "mocked_acpi_path"
        self.mock_pyudev.list_devices.return_value = [
            MagicMock(
                properties={
                    "PCI_ID": "1234abcd",
                    "PCI_SLOT_NAME": "0000:00:1f.0",
                    "ID_PCI_SUBCLASS_FROM_DATABASE": "ISA bridge",
                    "ID_VENDOR_FROM_DATABASE": "Intel Corporation",
                },
                parent=MagicMock(subsystem="platform"),
                sys_path="/sys/devices/pci0000:00/0000:00:1f.0",
            )
        ]

        self.validator.capture_pci_acpi()
        self.mock_db.record_debug.assert_called_with(
            "PCI Slot | Vendor | Class | ID | ACPI path\n└─0000:00:1f.0 | Intel Corporation | ISA bridge | 1234abcd | mocked_acpi_path\n"
        )

    @patch("amd_debug.prereq.devices.read_file")
    @patch("amd_debug.prereq.devices.os.path.exists")
    def test_capture_pci_acpi_without_acpi_path(self, mock_path_exists, mock_read_file):
        """Test capture_pci_acpi when ACPI paths do not exist for devices"""
        mock_path_exists.return_value = False
        self.mock_pyudev.list_devices.return_value = [
            MagicMock(
                properties={
                    "PCI_ID": "5678efgh",
                    "PCI_SLOT_NAME": "0000:01:00.0",
                    "ID_PCI_SUBCLASS_FROM_DATABASE": "VGA compatible controller",
                    "ID_VENDOR_FROM_DATABASE": "NVIDIA Corporation",
                },
                parent=MagicMock(subsystem="pci"),
                sys_path="/sys/devices/pci0000:01/0000:01:00.0",
            )
        ]

        self.validator.capture_pci_acpi()
        self.mock_db.record_debug.assert_called_with(
            "PCI Slot | Vendor | Class | ID | ACPI path\n└─0000:01:00.0 | NVIDIA Corporation | VGA compatible controller | 5678efgh | \n"
        )

    @patch("amd_debug.prereq.devices.read_file")
    @patch("amd_debug.prereq.devices.os.path.exists")
    def test_capture_pci_acpi_multiple_devices(self, mock_path_exists, mock_read_file):
        """Test capture_pci_acpi with multiple devices"""
        mock_path_exists.side_effect = lambda p: "firmware_node/path" in p
        mock_read_file.side_effect = lambda p: "mocked_acpi_path" if "path" in p else ""
        self.mock_pyudev.list_devices.return_value = [
            MagicMock(
                properties={
                    "PCI_ID": "1234abcd",
                    "PCI_SLOT_NAME": "0000:00:1f.0",
                    "ID_PCI_SUBCLASS_FROM_DATABASE": "ISA bridge",
                    "ID_VENDOR_FROM_DATABASE": "Intel Corporation",
                },
                parent=MagicMock(subsystem="platform"),
                sys_path="/sys/devices/pci0000:00/0000:00:1f.0",
            ),
            MagicMock(
                properties={
                    "PCI_ID": "5678efgh",
                    "PCI_SLOT_NAME": "0000:01:00.0",
                    "ID_PCI_SUBCLASS_FROM_DATABASE": "VGA compatible controller",
                    "ID_VENDOR_FROM_DATABASE": "NVIDIA Corporation",
                },
                parent=MagicMock(subsystem="pci"),
                sys_path="/sys/devices/pci0000:01/0000:01:00.0",
            ),
        ]

        self.validator.capture_pci_acpi()
        self.mock_db.record_debug.assert_called_with(
            "PCI Slot | Vendor | Class | ID | ACPI path\n│ 0000:00:1f.0 | Intel Corporation | ISA bridge | 1234abcd | mocked_acpi_path\n└─0000:01:00.0 | NVIDIA Corporation | VGA compatible controller | 5678efgh | mocked_acpi_path\n"
        )

    def test_capture_pci_acpi_no_devices(self):
        """Test capture_pci_acpi when no PCI devices are found"""
        self.mock_pyudev.list_devices.return_value = []

        self.validator.capture_pci_acpi()
        self.mock_db.record_debug.assert_called_with(
            "PCI Slot | Vendor | Class | ID | ACPI path\n"
        )

    @patch("amd_debug.prereq.devices.read_file")
    def test_check_aspm_default_policy(self, mock_read_file):
        """Test check_aspm when the policy is set to default"""
        mock_read_file.return_value = "[default]"
        result = self.validator.check_aspm()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_called_with(
            "ASPM policy set to 'default'", "✅"
        )

    @patch("amd_debug.prereq.devices.read_file")
    def test_check_aspm_non_default_policy(self, mock_read_file):
        """Test check_aspm when the policy is not set to default"""
        mock_read_file.return_value = "[performance]"
        result = self.validator.check_aspm()
        self.assertFalse(result)
        self.mock_db.record_prereq.assert_called_with(
            "ASPM policy set to [performance]", "❌"
        )
        self.assertTrue(any(isinstance(f, ASpmWrong) for f in self.validator.failures))

    @patch("amd_debug.prereq.devices.read_file")
    def test_check_aspm_empty_policy(self, mock_read_file):
        """Test check_aspm when the policy file is empty"""
        mock_read_file.return_value = ""
        result = self.validator.check_aspm()
        self.assertFalse(result)
        self.mock_db.record_prereq.assert_called_with("ASPM policy set to ", "❌")
        self.assertTrue(any(isinstance(f, ASpmWrong) for f in self.validator.failures))

    @patch("amd_debug.prereq.devices.read_file")
    def test_check_aspm_file_not_found(self, mock_read_file):
        """Test check_aspm when the policy file is not found"""
        mock_read_file.side_effect = FileNotFoundError
        with self.assertRaises(FileNotFoundError):
            self.validator.check_aspm()

    def test_check_aspm_disabled_on_cmdline(self):
        """Test check_aspm when pcie_aspm=off is on the kernel command line"""
        self.validator.cmdline = "quiet pcie_aspm=off rw"
        result = self.validator.check_aspm()
        self.assertFalse(result)
        self.mock_db.record_prereq.assert_called_with(
            "ASPM disabled on kernel command line (pcie_aspm=off)", "❌"
        )
        self.assertTrue(any(isinstance(f, ASpmWrong) for f in self.validator.failures))

    @patch("amd_debug.prereq.devices.read_file")
    def test_check_aspm_cmdline_without_aspm_off(self, mock_read_file):
        """Test check_aspm still reads the policy when cmdline is clean"""
        self.validator.cmdline = "quiet splash rw"
        mock_read_file.return_value = "[default]"
        result = self.validator.check_aspm()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_called_with(
            "ASPM policy set to 'default'", "✅"
        )

    @patch("amd_debug.prereq.devices.os.path.exists")
    @patch("amd_debug.prereq.devices.read_file")
    def test_check_i2c_hid_no_devices(self, mock_read_file, mock_path_exists):
        """Test check_i2c_hid when no I2C HID devices are found"""
        self.mock_pyudev.list_devices.return_value = []
        result = self.validator.check_i2c_hid()
        self.assertTrue(result)

    @patch("amd_debug.prereq.devices.os.path.exists")
    @patch("amd_debug.prereq.devices.read_file")
    def test_check_i2c_hid_with_devices(self, mock_read_file, mock_path_exists):
        """Test check_i2c_hid when I2C HID devices are found"""
        mock_path_exists.side_effect = (
            lambda p: "firmware_node/path" in p or "firmware_node/hid" in p
        )
        mock_read_file.side_effect = lambda p: (
            "mocked_path" if "path" in p else "mocked_hid"
        )
        self.mock_pyudev.list_devices.return_value = [
            MagicMock(
                properties={"NAME": "I2C Device 1"},
                find_parent=MagicMock(
                    return_value=MagicMock(sys_path="/sys/devices/i2c-1")
                ),
            ),
            MagicMock(
                properties={"NAME": "I2C Device 2"},
                find_parent=MagicMock(
                    return_value=MagicMock(sys_path="/sys/devices/i2c-2")
                ),
            ),
        ]

        result = self.validator.check_i2c_hid()
        self.assertTrue(result)
        self.mock_db.record_debug.assert_called_with(
            "I2C HID devices:\n"
            "│ I2C Device 1 [mocked_hid] : mocked_path\n"
            "└─I2C Device 2 [mocked_hid] : mocked_path\n"
        )

    @patch("amd_debug.prereq.devices.os.path.exists")
    @patch("amd_debug.prereq.devices.read_file")
    def test_check_i2c_hid_with_buggy_device(self, mock_read_file, mock_path_exists):
        """Test check_i2c_hid when a buggy I2C HID device is found"""
        mock_path_exists.side_effect = (
            lambda p: "firmware_node/path" in p or "firmware_node/hid" in p
        )
        mock_read_file.side_effect = lambda p: (
            "mocked_path" if "path" in p else "mocked_hid"
        )
        self.mock_pyudev.list_devices.return_value = [
            MagicMock(
                properties={"NAME": "IDEA5002"},
                find_parent=MagicMock(
                    return_value=MagicMock(
                        sys_path="/sys/devices/i2c-1", driver="mock_driver"
                    )
                ),
            )
        ]

        result = self.validator.check_i2c_hid()
        self.assertFalse(result)
        self.mock_db.record_prereq.assert_called_with(
            "IDEA5002 may cause spurious wakeups", "❌"
        )
        self.assertTrue(any(isinstance(f, I2CHidBug) for f in self.validator.failures))

    @patch("amd_debug.prereq.devices.os.path.exists")
    @patch("amd_debug.prereq.devices.read_file")
    def test_check_i2c_hid_missing_firmware_node(
        self, mock_read_file, mock_path_exists
    ):
        """Test check_i2c_hid when firmware_node paths are missing"""
        mock_path_exists.return_value = False
        self.mock_pyudev.list_devices.return_value = [
            MagicMock(
                properties={"NAME": "I2C Device 1"},
                find_parent=MagicMock(
                    return_value=MagicMock(sys_path="/sys/devices/i2c-1")
                ),
            )
        ]

        result = self.validator.check_i2c_hid()
        self.assertTrue(result)
        self.mock_db.record_debug.assert_called_with(
            "I2C HID devices:\n└─I2C Device 1 [] : \n"
        )

    @patch("amd_debug.prereq.acpi.os.path.exists", return_value=True)
    @patch(
        "amd_debug.prereq.acpi.open",
        new_callable=unittest.mock.mock_open,
        read_data=b"\x00" * 0x70 + b"\x20\x00\x00\x00",
    )
    @patch("amd_debug.prereq.acpi.struct.unpack", return_value=(0x00200000,))
    def test_check_fadt_supports_low_power_idle(
        self, mock_unpack, mock_open, mock_path_exists
    ):
        """Test check_fadt when ACPI FADT supports Low-power S0 idle"""
        self.mock_kernel_log.match_line.return_value = False
        result = self.validator.check_fadt()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_called_with(
            "ACPI FADT supports Low-power S0 idle", "✅"
        )

    @patch("amd_debug.prereq.acpi.os.path.exists", return_value=True)
    @patch(
        "amd_debug.prereq.acpi.open",
        new_callable=unittest.mock.mock_open,
        read_data=b"\x00" * 0x70 + b"\x00\x00\x00\x00",
    )
    @patch("amd_debug.prereq.acpi.struct.unpack", return_value=(0x00000000,))
    def test_check_fadt_does_not_support_low_power_idle(
        self, mock_unpack, mock_open, mock_path_exists
    ):
        """Test check_fadt when ACPI FADT does not support Low-power S0 idle"""
        self.mock_kernel_log.match_line.return_value = False
        result = self.validator.check_fadt()
        self.assertFalse(result)
        self.assertTrue(any(isinstance(f, FadtWrong) for f in self.validator.failures))

    @patch("amd_debug.prereq.acpi.os.path.exists", return_value=True)
    @patch("amd_debug.prereq.acpi.open", side_effect=FileNotFoundError)
    def test_check_fadt_file_not_found(self, _mock_open, _mock_exists):
        """Test check_fadt when FADT file is not found"""
        self.mock_kernel_log.match_line.return_value = False
        result = self.validator.check_fadt()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_called_with("FADT check unavailable", "🚦")

    @patch("amd_debug.prereq.acpi.os.path.exists", return_value=True)
    @patch("amd_debug.prereq.acpi.open", side_effect=PermissionError)
    def test_check_fadt_permission_error(self, mock_open, mock_path_exists):
        """Test check_fadt when there is a permission error accessing the FADT file"""
        self.mock_kernel_log.match_line.return_value = False
        result = self.validator.check_fadt()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_called_with("FADT check unavailable", "🚦")

    def test_check_fadt_kernel_log_match(self):
        """Test check_fadt when kernel log contains the required message"""
        self.mock_kernel_log.match_line.return_value = True
        result = self.validator.check_fadt()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_called_with(
            "ACPI FADT supports Low-power S0 idle", "✅"
        )

    @patch(
        "amd_debug.prereq.acpi.open",
        new_callable=unittest.mock.mock_open,
        read_data=b"\x00" * 0x70 + b"\x00\x00\x00\x00",
    )
    def test_check_fadt_no_kernel_log(self, _mock_open):
        """Test check_fadt when kernel log is not available"""
        self.validator.kernel_log = None
        result = self.validator.check_fadt()
        self.assertFalse(result)
        self.mock_db.record_prereq.assert_called_with(
            "ACPI FADT doesn't support Low-power S0 idle", "❌"
        )

    @patch("amd_debug.prereq.base.read_file")
    def test_get_cpu_vendor_all_fields_present(self, mock_read_file):
        """Test get_cpu_vendor when all fields are present in /proc/cpuinfo"""
        mock_read_file.return_value = (
            "vendor_id\t: AuthenticAMD\n"
            "cpu family\t: 23\n"
            "model\t\t: 1\n"
            "model name\t: AMD Ryzen 7 3700X\n"
        )
        vendor = self.validator.get_cpu_vendor()
        self.assertEqual(vendor, "AuthenticAMD")
        self.assertEqual(self.validator.cpu_family, 23)
        self.assertEqual(self.validator.cpu_model, 1)
        self.assertEqual(self.validator.cpu_model_string, "AMD Ryzen 7 3700X")
        self.mock_db.record_prereq.assert_called_with(
            "AMD Ryzen 7 3700X (family 17 model 1)", "💻"
        )

    @patch("amd_debug.prereq.base.read_file")
    def test_get_cpu_vendor_missing_model_name(self, mock_read_file):
        """Test get_cpu_vendor when model name is missing in /proc/cpuinfo"""
        mock_read_file.return_value = (
            "vendor_id\t: AuthenticAMD\n" "cpu family\t: 23\n" "model\t\t: 1\n"
        )
        vendor = self.validator.get_cpu_vendor()
        self.assertEqual(vendor, "AuthenticAMD")
        self.assertEqual(self.validator.cpu_family, 23)
        self.assertEqual(self.validator.cpu_model, 1)
        self.assertIsNone(self.validator.cpu_model_string)
        self.mock_db.record_prereq.assert_not_called()

    @patch("amd_debug.prereq.base.read_file")
    def test_get_cpu_vendor_missing_vendor_id(self, mock_read_file):
        """Test get_cpu_vendor when vendor_id is missing in /proc/cpuinfo"""
        mock_read_file.return_value = (
            "cpu family\t: 23\n" "model\t\t: 1\n" "model name\t: AMD Ryzen 7 3700X\n"
        )
        vendor = self.validator.get_cpu_vendor()
        self.assertEqual(vendor, "")
        self.assertEqual(self.validator.cpu_family, 23)
        self.assertEqual(self.validator.cpu_model, 1)
        self.assertEqual(self.validator.cpu_model_string, "AMD Ryzen 7 3700X")
        self.mock_db.record_prereq.assert_called_with(
            "AMD Ryzen 7 3700X (family 17 model 1)", "💻"
        )

    @patch("amd_debug.prereq.base.read_file")
    def test_get_cpu_vendor_missing_cpu_family(self, mock_read_file):
        """Test get_cpu_vendor when cpu family is missing in /proc/cpuinfo"""
        mock_read_file.return_value = (
            "vendor_id\t: AuthenticAMD\n"
            "model\t\t: 1\n"
            "model name\t: AMD Ryzen 7 3700X\n"
        )
        vendor = self.validator.get_cpu_vendor()
        self.assertEqual(vendor, "AuthenticAMD")
        self.assertIsNone(self.validator.cpu_family)
        self.assertEqual(self.validator.cpu_model, 1)
        self.assertEqual(self.validator.cpu_model_string, "AMD Ryzen 7 3700X")
        self.mock_db.record_prereq.assert_not_called()

    @patch("amd_debug.prereq.base.read_file")
    def test_get_cpu_vendor_missing_model(self, mock_read_file):
        """Test get_cpu_vendor when model is missing in /proc/cpuinfo"""
        mock_read_file.return_value = (
            "vendor_id\t: AuthenticAMD\n"
            "cpu family\t: 23\n"
            "model name\t: AMD Ryzen 7 3700X\n"
        )
        vendor = self.validator.get_cpu_vendor()
        self.assertEqual(vendor, "AuthenticAMD")
        self.assertEqual(self.validator.cpu_family, 23)
        self.assertIsNone(self.validator.cpu_model)
        self.assertEqual(self.validator.cpu_model_string, "AMD Ryzen 7 3700X")
        self.mock_db.record_prereq.assert_not_called()

    @patch("amd_debug.prereq.base.read_file")
    def test_get_cpu_vendor_empty_cpuinfo(self, mock_read_file):
        """Test get_cpu_vendor when /proc/cpuinfo is empty"""
        mock_read_file.return_value = ""
        vendor = self.validator.get_cpu_vendor()
        self.assertEqual(vendor, "")
        self.assertIsNone(self.validator.cpu_family)
        self.assertIsNone(self.validator.cpu_model)
        self.assertIsNone(self.validator.cpu_model_string)
        self.mock_db.record_prereq.assert_not_called()

    @patch("amd_debug.prereq.system.os.path.exists", return_value=False)
    def test_capture_smbios_not_setup(self, mock_path_exists):
        """Test capture_smbios when DMI data is not set up"""
        self.validator.capture_smbios()
        self.mock_db.record_prereq.assert_called_with("DMI data was not setup", "🚦")
        self.assertTrue(
            any(isinstance(f, DmiNotSetup) for f in self.validator.failures)
        )

    @patch("amd_debug.prereq.system.os.walk")
    @patch("amd_debug.prereq.system.read_file")
    @patch("amd_debug.prereq.system.os.path.exists", return_value=True)
    def test_capture_smbios_success(
        self, mock_path_exists, mock_read_file, mock_os_walk
    ):
        """Test capture_smbios when DMI data is successfully captured"""
        mock_os_walk.return_value = [
            (
                "/sys/class/dmi/id",
                [],
                ["sys_vendor", "product_name", "product_family", "chassis_type"],
            )
        ]
        mock_read_file.side_effect = lambda path: {
            "/sys/class/dmi/id/sys_vendor": "MockVendor",
            "/sys/class/dmi/id/product_name": "MockProduct",
            "/sys/class/dmi/id/product_family": "MockFamily",
            "/sys/class/dmi/id/chassis_type": "Desktop",
        }.get(path, "")
        result = self.validator.capture_smbios()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_called_with(
            "MockVendor MockProduct (MockFamily)", "💻"
        )
        self.mock_db.record_debug.assert_called_with(
            "DMI|value\nchassis_type| Desktop\n"
        )

    @patch("amd_debug.prereq.system.os.walk")
    @patch("amd_debug.prereq.system.read_file")
    @patch("amd_debug.prereq.system.os.path.exists", return_value=True)
    def test_capture_smbios_filtered_keys(
        self, _mock_path_exists, mock_read_file, mock_os_walk
    ):
        """Test capture_smbios when filtered keys are present"""
        mock_os_walk.return_value = [
            (
                "/sys/class/dmi/id",
                [],
                ["sys_vendor", "product_name", "product_family", "product_serial"],
            )
        ]
        mock_read_file.side_effect = lambda path: {
            "/sys/class/dmi/id/sys_vendor": "MockVendor",
            "/sys/class/dmi/id/product_name": "MockProduct",
            "/sys/class/dmi/id/product_family": "MockFamily",
            "/sys/class/dmi/id/product_serial": "12345",
        }.get(path, "")
        result = self.validator.capture_smbios()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_called_with(
            "MockVendor MockProduct (MockFamily)", "💻"
        )
        self.mock_db.record_debug.assert_called_with("DMI|value\n")

    @patch("amd_debug.prereq.system.os.walk")
    @patch("amd_debug.prereq.system.read_file")
    @patch("amd_debug.prereq.system.os.path.exists", return_value=True)
    def test_capture_smbios_missing_keys(
        self, _mock_path_exists, mock_read_file, mock_os_walk
    ):
        """Test capture_smbios when required keys are missing"""
        mock_os_walk.return_value = [("/sys/class/dmi/id", [], ["chassis_type"])]
        mock_read_file.side_effect = lambda path: {
            "/sys/class/dmi/id/chassis_type": "Desktop",
        }.get(path, "")
        result = self.validator.capture_smbios()
        self.assertTrue(
            any(isinstance(f, DmiNotSetup) for f in self.validator.failures)
        )
        self.assertFalse(result)

    @patch("amd_debug.prereq.acpi.os.path.exists")
    @patch("amd_debug.prereq.acpi.read_file")
    def test_check_lps0_enabled(self, mock_read_file, mock_path_exists):
        """Test check_lps0 when LPS0 is enabled"""
        mock_path_exists.return_value = True
        mock_read_file.return_value = "N"
        result = self.validator.check_lps0()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_called_with("LPS0 _DSM enabled", "✅")

    @patch("amd_debug.prereq.acpi.os.path.exists")
    @patch("amd_debug.prereq.acpi.read_file")
    def test_check_lps0_disabled(self, mock_read_file, mock_path_exists):
        """Test check_lps0 when LPS0 is disabled"""
        mock_path_exists.return_value = True
        mock_read_file.return_value = "Y"
        result = self.validator.check_lps0()
        self.assertFalse(result)
        self.mock_db.record_prereq.assert_called_with("LPS0 _DSM disabled", "❌")

    @patch("amd_debug.prereq.acpi.os.path.exists")
    def test_check_lps0_not_found(self, mock_path_exists):
        """Test check_lps0 when LPS0 parameter is not found"""
        mock_path_exists.return_value = False
        result = self.validator.check_lps0()
        self.assertFalse(result)
        self.mock_db.record_prereq.assert_called_with("LPS0 _DSM not found", "👀")

    @patch("amd_debug.prereq.base.os.listdir")
    @patch("amd_debug.prereq.base.os.path.isdir")
    @patch("amd_debug.prereq.base.WakeIRQ")
    def test_capture_irq_with_irqs(self, MockWakeIRQ, mock_isdir, mock_listdir):
        """Test capture_irq when IRQ directories are present"""
        mock_listdir.return_value = ["1", "2", "3"]
        mock_isdir.side_effect = lambda path: path.endswith(("1", "2", "3"))
        MockWakeIRQ.side_effect = lambda irq, pyudev: f"WakeIRQ-{irq}"

        result = self.validator.capture_irq()

        self.assertTrue(result)
        self.assertEqual(
            self.validator.irqs,
            [[1, "WakeIRQ-1"], [2, "WakeIRQ-2"], [3, "WakeIRQ-3"]],
        )
        self.mock_db.record_debug.assert_any_call("Interrupts")
        self.mock_db.record_debug.assert_any_call("│ 1: WakeIRQ-1")
        self.mock_db.record_debug.assert_any_call("│ 2: WakeIRQ-2")
        self.mock_db.record_debug.assert_any_call("└─3: WakeIRQ-3")

    @patch("amd_debug.prereq.base.os.listdir")
    @patch("amd_debug.prereq.base.os.path.isdir")
    def test_capture_irq_no_irqs(self, mock_isdir, mock_listdir):
        """Test capture_irq when no IRQ directories are present"""
        mock_listdir.return_value = []
        mock_isdir.return_value = False

        result = self.validator.capture_irq()

        self.assertTrue(result)
        self.assertEqual(self.validator.irqs, [])
        self.mock_db.record_debug.assert_called_with("Interrupts")

    @patch("amd_debug.prereq.base.os.listdir")
    @patch("amd_debug.prereq.base.os.path.isdir")
    @patch("amd_debug.prereq.base.WakeIRQ")
    def test_capture_irq_mixed_entries(self, mock_wake_irq, mock_isdir, mock_listdir):
        """Test capture_irq with mixed valid and invalid IRQ directories"""
        mock_listdir.return_value = ["1", "invalid", "2"]
        mock_isdir.side_effect = lambda path: path.endswith(("1", "2"))
        mock_wake_irq.side_effect = lambda irq, pyudev: f"WakeIRQ-{irq}"

        result = self.validator.capture_irq()

        self.assertTrue(result)
        self.assertEqual(
            self.validator.irqs,
            [[1, "WakeIRQ-1"], [2, "WakeIRQ-2"]],
        )
        self.mock_db.record_debug.assert_any_call("Interrupts")
        self.mock_db.record_debug.assert_any_call("│ 1: WakeIRQ-1")
        self.mock_db.record_debug.assert_any_call("└─2: WakeIRQ-2")

    @patch("amd_debug.prereq.system.os.path.exists", return_value=True)
    @patch("builtins.open", new_callable=unittest.mock.mock_open)
    def test_check_permissions_success(self, _mock_open, _mock_path_exists):
        """Test check_permissions when the user has write permissions"""
        result = self.validator.check_permissions()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_not_called()

    @patch("amd_debug.prereq.system.os.path.exists", return_value=True)
    @patch("builtins.open", side_effect=PermissionError)
    def test_check_permissions_permission_error(self, _mock_open, _mock_path_exists):
        """Test check_permissions when the user lacks write permissions"""
        result = self.validator.check_permissions()
        self.assertFalse(result)

    @patch("amd_debug.prereq.system.os.path.exists", return_value=False)
    @patch("builtins.open", side_effect=FileNotFoundError)
    def test_check_permissions_file_not_found(self, _mock_open, _mock_path_exists):
        """Test check_permissions when the /sys/power/state file is not found"""
        result = self.validator.check_permissions()
        self.assertFalse(result)
        self.mock_db.record_prereq.assert_called_with(
            "Kernel doesn't support power management", "❌"
        )

    @patch("amd_debug.prereq.system.subprocess.check_output")
    def test_check_network_wol_supported_and_enabled(self, mock_check_output):
        """Test check_network when WoL is supported and enabled"""
        self.mock_pyudev.list_devices.return_value = [
            MagicMock(properties={"INTERFACE": "eth0"})
        ]
        mock_check_output.return_value = (
            "Supports Wake-on: g\n" "Wake-on: g\n"
        ).encode("utf-8")

        result = self.validator.check_network()
        self.assertTrue(result)
        self.mock_db.record_debug.assert_called_with("eth0 supports WoL")
        self.mock_db.record_prereq.assert_called_with("eth0 has WoL enabled", "✅")

    @patch("amd_debug.prereq.system.subprocess.check_output")
    def test_check_network_wol_supported_but_disabled(self, mock_check_output):
        """Test check_network when WoL is supported but disabled"""
        self.mock_pyudev.list_devices.return_value = [
            MagicMock(properties={"INTERFACE": "eth0"})
        ]
        mock_check_output.return_value = (
            "Supports Wake-on: g\n" "Wake-on: d\n"
        ).encode("utf-8")

        result = self.validator.check_network()
        self.assertTrue(result)
        self.mock_db.record_debug.assert_called_with("eth0 supports WoL")
        self.mock_db.record_prereq.assert_called_with(
            "Platform may have low hardware sleep residency with Wake-on-lan disabled. Run `ethtool -s eth0 wol g` to enable it if necessary.",
            "🚦",
        )

    @patch("amd_debug.prereq.system.subprocess.check_output")
    def test_check_network_wol_not_supported(self, mock_check_output):
        """Test check_network when WoL is not supported"""
        self.mock_pyudev.list_devices.return_value = [
            MagicMock(properties={"INTERFACE": "eth0"})
        ]
        mock_check_output.return_value = ("Supports Wake-on: d\n").encode("utf-8")

        result = self.validator.check_network()
        self.assertTrue(result)
        self.mock_db.record_debug.assert_called_with("eth0 doesn't support WoL (d)")

    @patch("amd_debug.prereq.system.subprocess.check_output")
    def test_check_network_no_devices(self, mock_check_output):
        """Test check_network when no network devices are found"""
        self.mock_pyudev.list_devices.return_value = []

        result = self.validator.check_network()
        self.assertTrue(result)
        self.mock_db.record_debug.assert_not_called()
        self.mock_db.record_prereq.assert_not_called()

    @patch(
        "amd_debug.prereq.system.subprocess.check_output",
        side_effect=subprocess.CalledProcessError(1, "ethtool"),
    )
    def test_check_network_ethtool_error(self, mock_check_output):
        """Test check_network when ethtool command fails"""
        self.mock_pyudev.list_devices.return_value = [
            MagicMock(properties={"INTERFACE": "eth0"})
        ]

        with self.assertRaises(subprocess.CalledProcessError):
            self.validator.check_network()
        self.mock_db.record_debug.assert_not_called()
        self.mock_db.record_prereq.assert_not_called()

    def test_check_wlan_no_devices(self):
        """Test check_wlan when no WLAN devices are found"""
        self.mock_pyudev.list_devices.return_value = []
        result = self.validator.check_wlan()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_not_called()

    def test_check_wlan_missing_driver(self):
        """Test check_wlan when a WLAN device is missing a driver"""
        self.mock_pyudev.list_devices.return_value = [
            MagicMock(properties={"PCI_SLOT_NAME": "0000:00:1f.0", "DRIVER": None})
        ]
        result = self.validator.check_wlan()
        self.assertFalse(result)
        self.mock_db.record_prereq.assert_called_with(
            "WLAN device in 0000:00:1f.0 missing driver", "🚦"
        )
        self.assertTrue(
            any(isinstance(f, MissingDriver) for f in self.validator.failures)
        )

    def test_check_wlan_with_driver(self):
        """Test check_wlan when a WLAN device has a driver"""
        self.mock_pyudev.list_devices.return_value = [
            MagicMock(properties={"PCI_SLOT_NAME": "0000:00:1f.0", "DRIVER": "iwlwifi"})
        ]
        result = self.validator.check_wlan()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_called_with(
            "WLAN driver `iwlwifi` bound to 0000:00:1f.0", "✅"
        )

    def test_check_wlan_multiple_devices(self):
        """Test check_wlan with multiple WLAN devices"""
        self.mock_pyudev.list_devices.return_value = [
            MagicMock(
                properties={"PCI_SLOT_NAME": "0000:00:1f.0", "DRIVER": "iwlwifi"}
            ),
            MagicMock(properties={"PCI_SLOT_NAME": "0000:00:1f.1", "DRIVER": None}),
        ]
        result = self.validator.check_wlan()
        self.assertFalse(result)
        self.mock_db.record_prereq.assert_any_call(
            "WLAN driver `iwlwifi` bound to 0000:00:1f.0", "✅"
        )
        self.mock_db.record_prereq.assert_any_call(
            "WLAN device in 0000:00:1f.1 missing driver", "🚦"
        )
        self.assertTrue(
            any(isinstance(f, MissingDriver) for f in self.validator.failures)
        )

    @patch("amd_debug.prereq.devices.subprocess.check_output")
    def test_capture_edid_no_edid_data(self, mock_check_output):
        """Test capture_edid when no EDID data is found"""
        self.validator.display.get_edid = MagicMock(return_value={})
        result = self.validator.capture_edid()
        self.assertTrue(result)
        self.mock_db.record_debug.assert_called_with("No EDID data found")
        mock_check_output.assert_not_called()

    @patch("amd_debug.prereq.devices.subprocess.check_output")
    def test_capture_edid_file_not_found(self, mock_check_output):
        """Test capture_edid when edid-decode is not installed"""
        self.validator.display.get_edid = MagicMock(
            return_value={"Monitor1": "/path/to/edid"}
        )
        mock_check_output.side_effect = FileNotFoundError
        result = self.validator.capture_edid()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_called_with(
            "Failed to capture EDID table", "👀"
        )

    @patch("amd_debug.prereq.devices.subprocess.check_output")
    def test_capture_edid_subprocess_error(self, mock_check_output):
        """Test capture_edid when subprocess.check_output raises an error"""
        self.validator.display.get_edid = MagicMock(
            return_value={"Monitor1": "/path/to/edid"}
        )
        mock_check_output.side_effect = subprocess.CalledProcessError(
            returncode=1, cmd="edid-decode", output=b"Error decoding EDID"
        )
        result = self.validator.capture_edid()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_called_with(
            "Failed to capture EDID table", "👀"
        )

    @patch("amd_debug.prereq.devices.subprocess.check_output")
    def test_capture_edid_success(self, mock_check_output):
        """Test capture_edid when EDID data is successfully decoded"""
        self.validator.display.get_edid = MagicMock(
            return_value={"Monitor1": "/path/to/edid"}
        )
        mock_check_output.return_value = b"Decoded EDID data"
        result = self.validator.capture_edid()
        self.assertTrue(result)
        self.mock_db.record_debug.assert_called_with(
            apply_prefix_wrapper("EDID for Monitor1:", "Decoded EDID data")
        )

    @patch("amd_debug.prereq.base.clear_temporary_message")
    def test_run_failure_records_kernel_log(self, _mock_clear):
        """Test that the whole kernel log is recorded when prerequisites fail"""
        # Mock every host accessing method that run() invokes
        check_methods = [
            # base capture methods
            "capture_smbios",
            "capture_kernel_version",
            "capture_battery",
            "capture_logind",
            "capture_pci_acpi",
            "capture_edid",
            "capture_nvidia",
            "capture_nvidia_power",
            "capture_cstates",
            # base checks
            "check_fadt",
            "check_logger",
            "check_lps0",
            "check_permissions",
            "check_wlan",
            "check_taint",
            "capture_acpi",
            "map_acpi_path",
            "check_device_firmware",
            "check_network",
            # nvidia checks
            "check_nvidia_s0ix",
            "check_nvidia_video_memory",
            "check_nvidia_suspend_units",
            "check_nvidia_powerd",
        ]
        for method in check_methods:
            setattr(self.validator, method, MagicMock(return_value=True))

        # Mock one check to fail
        self.validator.check_permissions.return_value = False

        # Mock get_cpu_vendor
        self.validator.get_cpu_vendor = MagicMock(return_value="AuthenticAMD")

        # Set a mock kernel log
        mock_log_content = "Mocked full kernel log content"
        self.mock_kernel_log.get_full_log.return_value = mock_log_content

        # Run the validator
        with patch("amd_debug.prereq.base.print_temporary_message", return_value="msg"):
            result = self.validator.run()

        self.assertFalse(result)
        # Verify Headers.BrokenPrerequisites was recorded
        from amd_debug.prereq.base import Headers

        self.mock_db.record_prereq.assert_any_call(Headers.BrokenPrerequisites, "🚫")
        # Verify the whole kernel log was recorded to debug
        self.mock_db.record_debug.assert_called_with(mock_log_content)

    @patch("amd_debug.prereq.base.os.path.exists")
    def test_capture_nvidia_version_file_missing(self, mock_exists):
        """Test capture_nvidia when /proc/driver/nvidia/version does not exist"""
        mock_exists.side_effect = lambda p: False if "version" in p else True
        result = self.validator.capture_nvidia()
        self.assertTrue(result)
        self.mock_db.record_debug_file.assert_not_called()
        self.mock_db.record_prereq.assert_not_called()

    @patch("amd_debug.prereq.base.os.path.exists")
    def test_capture_nvidia_gpus_dir_missing(self, mock_exists):
        """Test capture_nvidia when /proc/driver/nvidia/gpus does not exist"""

        def exists_side_effect(path):
            if "version" in path:
                return True
            if "gpus" in path:
                return False
            return True

        mock_exists.side_effect = exists_side_effect
        result = self.validator.capture_nvidia()
        self.assertTrue(result)
        self.mock_db.record_debug_file.assert_called_once_with(
            "/proc/driver/nvidia/version"
        )
        self.mock_db.record_prereq.assert_not_called()

    @patch("amd_debug.prereq.base.os.walk")
    @patch("amd_debug.prereq.base.os.path.exists")
    def test_capture_nvidia_success(self, mock_exists, mock_walk):
        """Test capture_nvidia when NVIDIA GPU files are present and readable"""
        mock_exists.side_effect = lambda p: True
        mock_walk.return_value = [
            ("/proc/driver/nvidia/gpus/0000:01:00.0", [], ["info", "power"])
        ]
        result = self.validator.capture_nvidia()
        self.assertTrue(result)
        self.mock_db.record_debug_file.assert_any_call("/proc/driver/nvidia/version")
        self.mock_db.record_debug.assert_any_call("NVIDIA info")
        self.mock_db.record_debug_file.assert_any_call(
            "/proc/driver/nvidia/gpus/0000:01:00.0/info"
        )
        self.mock_db.record_debug.assert_any_call("NVIDIA power")
        self.mock_db.record_debug_file.assert_any_call(
            "/proc/driver/nvidia/gpus/0000:01:00.0/power"
        )

    @patch("amd_debug.prereq.base.os.walk")
    @patch("amd_debug.prereq.base.os.path.exists")
    def test_capture_nvidia_permission_error_on_version(self, mock_exists, mock_walk):
        """Test capture_nvidia when PermissionError occurs reading version file"""
        mock_exists.side_effect = lambda p: True if "version" in p else False
        self.mock_db.record_debug_file.side_effect = PermissionError
        result = self.validator.capture_nvidia()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_called_with(
            "NVIDIA GPU version not readable", "👀"
        )

    @patch("amd_debug.prereq.base.os.walk")
    @patch("amd_debug.prereq.base.os.path.exists")
    def test_capture_nvidia_permission_error_on_gpu_file(self, mock_exists, mock_walk):
        """Test capture_nvidia when PermissionError occurs reading a GPU file"""
        mock_exists.side_effect = lambda p: True
        mock_walk.return_value = [
            ("/proc/driver/nvidia/gpus/0000:01:00.0", [], ["info"])
        ]
        self.mock_db.record_debug_file.side_effect = [None, PermissionError]
        result = self.validator.capture_nvidia()
        self.assertTrue(result)
        self.mock_db.record_debug.assert_any_call("NVIDIA info")
        self.mock_db.record_prereq.assert_called_with(
            "NVIDIA GPU info not readable", "👀"
        )

    @patch("amd_debug.prereq.acpi.os.walk")
    @patch(
        "builtins.open",
        new_callable=unittest.mock.mock_open,
        read_data=b"C1 state info",
    )
    def test_capture_cstates_single_file(self, mock_open, mock_walk):
        """Test capture_cstates with a single cpuidle file"""
        mock_walk.return_value = [
            ("/sys/bus/cpu/devices/cpu0/cpuidle", [], ["state1"]),
        ]
        self.validator.capture_cstates()
        self.mock_db.record_debug.assert_called_with(
            "ACPI C-state information\n└─/sys/bus/cpu/devices/cpu0/cpuidle/state1: C1 state info"
        )

    @patch("amd_debug.prereq.acpi.os.walk")
    @patch("builtins.open", new_callable=mock_open)
    def test_capture_cstates_multiple_files(self, mock_open_func, mock_walk):
        """Test capture_cstates with multiple cpuidle files"""
        # Setup mock file reads for two files
        file_contents = {
            "/sys/bus/cpu/devices/cpu0/cpuidle/state1": b"C1 info",
            "/sys/bus/cpu/devices/cpu0/cpuidle/state2": b"C2 info",
        }

        def side_effect(path, mode="rb"):
            mock_file = mock_open(read_data=file_contents[path])()
            return mock_file

        mock_open_func.side_effect = side_effect
        mock_walk.return_value = [
            ("/sys/bus/cpu/devices/cpu0/cpuidle", [], ["state1", "state2"]),
        ]
        self.validator.capture_cstates()
        # The prefix logic is based on order, so check for both lines
        debug_call = self.mock_db.record_debug.call_args[0][0]
        self.assertIn("/sys/bus/cpu/devices/cpu0/cpuidle/state1: C1 info", debug_call)
        self.assertIn("/sys/bus/cpu/devices/cpu0/cpuidle/state2: C2 info", debug_call)
        self.assertTrue(debug_call.startswith("ACPI C-state information\n"))

    @patch("amd_debug.prereq.acpi.os.walk")
    @patch("builtins.open", new_callable=mock_open, read_data=b"")
    def test_capture_cstates_empty_files(self, _mock_open, mock_walk):
        """Test capture_cstates with empty cpuidle files"""
        mock_walk.return_value = [
            ("/sys/bus/cpu/devices/cpu0/cpuidle", [], ["state1"]),
        ]
        self.validator.capture_cstates()
        self.mock_db.record_debug.assert_called_with(
            "ACPI C-state information\n└─/sys/bus/cpu/devices/cpu0/cpuidle/state1: "
        )

    @patch("amd_debug.prereq.acpi.os.walk")
    @patch("amd_debug.prereq.acpi.open", side_effect=PermissionError)
    def test_capture_cstates_permission_error(self, _mock_open, mock_walk):
        """Test capture_cstates when reading cpuidle files raises PermissionError"""
        mock_walk.return_value = [
            ("/sys/bus/cpu/devices/cpu0/cpuidle", [], ["state1"]),
        ]
        with self.assertRaises(PermissionError):
            self.validator.capture_cstates()
        self.mock_db.record_debug.assert_not_called()

    @patch("amd_debug.prereq.acpi.os.walk")
    def test_capture_cstates_no_files(self, mock_walk):
        """Test capture_cstates when no cpuidle files are present"""
        mock_walk.return_value = [
            ("/sys/bus/cpu/devices/cpu0/cpuidle", [], []),
        ]
        self.validator.capture_cstates()
        self.mock_db.record_debug.assert_called_with("ACPI C-state information\n")


class TestBaseCoverageBranches(unittest.TestCase):
    """Test the remaining base, system and device check branches"""

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(filename="/dev/null", level=logging.DEBUG)

    def setUp(self):
        with patch("amd_debug.prereq.base.SleepDatabase") as mock_db, patch(
            "amd_debug.prereq.base.get_kernel_log"
        ), patch("amd_debug.prereq.base.is_root", return_value=True), patch(
            "amd_debug.prereq.base.pyudev.Context"
        ) as mock_pyudev, patch(
            "amd_debug.prereq.base.get_distro", return_value="Test OS"
        ), patch(
            "amd_debug.prereq.base.read_file", return_value="quiet"
        ), patch("amd_debug.prereq.base.Display"):
            self.validator = PrerequisiteValidator(tool_debug=True)
            self.mock_db = mock_db.return_value
            self.mock_pyudev = mock_pyudev.return_value

    def test_init_requires_root(self):
        """Test that construction fails without root"""
        with patch(
            "amd_debug.prereq.base.get_kernel_log"
        ), patch("amd_debug.prereq.base.is_root", return_value=False):
            with self.assertRaises(PermissionError):
                PrerequisiteValidator(tool_debug=True)

    @patch("amd_debug.prereq.base.read_file", side_effect=FileNotFoundError)
    def test_get_cpu_vendor_unreadable(self, _mock_read):
        """Test the cpu vendor lookup with an unreadable cpuinfo"""
        self.validator.get_cpu_vendor()
        self.assertEqual(self.validator.cpu_family, None)

    def test_capture_once_runs_without_prereq_data(self):
        """Test that capture_once runs when there is no prereq data"""
        self.mock_db.get_last_prereq_ts.return_value = None
        with patch.object(self.validator, "run") as mock_run:
            self.validator.capture_once()
            mock_run.assert_called_once()

    def test_capture_once_skips_with_prereq_data(self):
        """Test that capture_once does not run with prereq data present"""
        self.mock_db.get_last_prereq_ts.return_value = "20230101000000"
        with patch.object(self.validator, "run") as mock_run:
            self.validator.capture_once()
            mock_run.assert_not_called()

    def test_report(self):
        """Test the prereq report output"""
        from amd_debug.failures import SleepModeWrong

        self.mock_db.get_last_prereq_ts.return_value = "20230101000000"
        self.mock_db.report_prereq.return_value = [
            ("20230101000000", 0, "some message", "✅")
        ]
        self.mock_db.report_debug.return_value = [("debug line\nsecond",)]
        for debug in (True, False):
            self.validator.debug = debug
            with patch(
                "amd_debug.prereq.base.print_color"
            ) as mock_print, patch(
                "amd_debug.prereq.base.logging.debug"
            ):
                self.validator.failures = [SleepModeWrong()]
                self.validator.report()
        self.assertTrue(mock_print.called)

    @patch(
        "amd_debug.prereq.system.subprocess.check_output",
        side_effect=FileNotFoundError,
    )
    @patch("os.path.exists", return_value=True)
    def test_check_network_ethtool_missing(self, _mock_exists, _mock_output):
        """Test the wake on lan check without ethtool

        A r8169 network device is returned so that the check reaches the
        ethtool lookup and hits the missing ethtool path.
        """
        net_dev = MagicMock()
        net_dev.properties = {
            "INTERFACE": "eth0",
            "ID_NET_DRIVER": "r8169",
        }
        self.mock_pyudev.list_devices.return_value = [net_dev]
        result = self.validator.check_network()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_called_with("ethtool is missing", "👀")

    @patch("amd_debug.prereq.system.configparser.ConfigParser")
    @patch("os.path.exists", return_value=True)
    def test_capture_logind(self, _mock_exists, mock_config):
        """Test the logind configuration capture"""
        config = MagicMock()
        config.read.return_value = None
        section = MagicMock()
        section.keys.return_value = ["IdleAction"]
        section.__getitem__.side_effect = lambda key: "ignore"
        config.__getitem__.return_value = section
        mock_config.return_value = config
        self.validator.capture_logind()
        self.mock_db.record_debug.assert_any_call("LOGIND: configuration changes:")
        self.mock_db.record_debug.assert_any_call("\tIdleAction: ignore")

    @patch("amd_debug.prereq.system.configparser.ConfigParser")
    @patch("os.path.exists", return_value=True)
    def test_capture_logind_no_changes(self, _mock_exists, mock_config):
        """Test the logind capture with an empty configuration"""
        config = MagicMock()
        config.read.return_value = None
        section = MagicMock()
        section.keys.return_value = []
        config.__getitem__.return_value = section
        mock_config.return_value = config
        self.validator.capture_logind()
        self.mock_db.record_debug.assert_called_once_with(
            "LOGIND: no configuration changes"
        )

    def test_check_logger_dmesg_wrapped(self):
        """Test the logger check with a wrapped kernel ring buffer"""
        from amd_debug.kernel import DmesgLogger
        from amd_debug.failures import KernelRingBufferWrapped

        logger = DmesgLogger.__new__(DmesgLogger)
        logger.capture_header = lambda: "no version here"
        self.validator.kernel_log = logger
        result = self.validator.check_logger()
        self.assertFalse(result)
        self.assertTrue(
            any(
                isinstance(f, KernelRingBufferWrapped)
                for f in self.validator.failures
            )
        )

    def test_check_logger_systemd(self):
        """Test the logger check with the systemd journal"""
        from amd_debug.kernel import SystemdLogger

        logger = SystemdLogger.__new__(SystemdLogger)
        self.validator.kernel_log = logger
        result = self.validator.check_logger()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_called_with(
            "Logs are provided via systemd", "✅"
        )

    def test_check_device_firmware_no_fwupd(self):
        """Test the device firmware check without fwupd bindings"""
        import amd_debug.prereq.devices as devices_module

        with patch.object(devices_module, "FWUPD", False):
            result = self.validator.check_device_firmware()
        self.assertTrue(result)
        self.mock_db.record_debug.assert_called_with(
            "Device firmware checks unavailable without gobject introspection"
        )

    def test_check_device_firmware_known_bad_version(self):
        """Test the detection of the known problematic firmware version

        The fwupd bindings are injected as fake modules so that the test
        runs on systems where the real bindings are unavailable.
        """
        import importlib
        import sys
        import types

        import amd_debug.prereq.devices as devices_module

        fake_fwupd = types.ModuleType("gi.repository.Fwupd")
        fake_fwupd.Client = MagicMock
        fake_gi = types.ModuleType("gi")
        fake_gi.require_version = MagicMock()
        fake_repository = types.ModuleType("gi.repository")
        fake_repository.GLib = types.ModuleType("gi.repository.GLib")
        fake_repository.Fwupd = fake_fwupd
        fake_modules = {
            "gi": fake_gi,
            "gi.repository": fake_repository,
            "gi.repository.GLib": fake_repository.GLib,
            "gi.repository.Fwupd": fake_fwupd,
        }

        try:
            with patch.dict(sys.modules, fake_modules):
                importlib.reload(devices_module)
                self.assertTrue(devices_module.FWUPD)

                device = MagicMock()
                device.get_guids.return_value = []
                device.get_instance_ids.return_value = [
                    "8c36f7ee-cc11-4a36-b090-6363f54ecac2"
                ]
                device.get_version.return_value = "0.1.26"
                device.get_plugin.return_value = "nvme"
                device.get_name.return_value = "NVME DEVICE"
                with patch.object(
                    devices_module.Fwupd, "Client"
                ) as mock_client:
                    mock_client.return_value.get_devices.return_value = [device]
                    result = self.validator.check_device_firmware()
        finally:
            # restore the module with the real bindings
            importlib.reload(devices_module)

        self.assertTrue(result)
        self.mock_db.record_prereq.assert_called_once()
        self.assertIn("Upgrade the firmware", self.mock_db.record_prereq.call_args[0][0])

    def test_capture_pci_acpi_single_device(self):
        """Test the pci to acpi mapping table prefixes"""
        dev = MagicMock()
        dev.properties = {
            "PCI_ID": "8086:7D01",
            "PCI_SLOT_NAME": "0000:00:00.0",
        }
        dev.parent.subsystem = "pci"
        self.mock_pyudev.list_devices.return_value = [dev]
        with patch(
            "amd_debug.prereq.devices.get_property_pyudev", return_value=""
        ), patch("os.path.exists", return_value=False):
            self.validator.capture_pci_acpi()
        debug = self.mock_db.record_debug.call_args[0][0]
        self.assertIn("└─0000:00:00.0", debug)

    def test_check_i2c_hid_no_devices(self):
        """Test the i2c hid check with no i2c devices"""
        dev = MagicMock()
        dev.properties = {"NAME": "touchpad"}
        dev.find_parent.return_value = None
        self.mock_pyudev.list_devices.return_value = [dev]
        result = self.validator.check_i2c_hid()
        self.assertTrue(result)
        self.mock_db.record_debug.assert_not_called()

    @patch("os.path.exists", side_effect=lambda p: "FACP" in p or p.endswith("status"))
    def test_map_acpi_path_missing_path(self, _mock_exists):
        """Test the acpi path mapping with a device without a path"""
        dev = MagicMock()
        dev.sys_path = "/sys/devices/LNXSYSTM"
        self.mock_pyudev.list_devices.return_value = [dev]
        self.validator.map_acpi_path()


if __name__ == "__main__":
    unittest.main()

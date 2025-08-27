#!/usr/bin/python3
# SPDX-License-Identifier: MIT

"""
This module contains unit tests for the prerequisite functions in the amd-debug-tools package.
"""

import logging
import unittest
import subprocess
from unittest.mock import patch, MagicMock, mock_open

from amd_debug.prerequisites import PrerequisiteValidator
from amd_debug.failures import *
from amd_debug.common import apply_prefix_wrapper, BIT


class TestPrerequisiteValidator(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(filename="/dev/null", level=logging.DEBUG)

    @patch("amd_debug.prerequisites.is_root", return_value=True)
    @patch("amd_debug.prerequisites.get_kernel_log")
    @patch("amd_debug.prerequisites.get_distro", return_value="Ubuntu")
    @patch("amd_debug.prerequisites.read_file", return_value="mocked_cmdline")
    @patch("amd_debug.prerequisites.pyudev.Context")
    @patch("amd_debug.prerequisites.SleepDatabase")
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

    def test_check_amdgpu_no_driver(self):
        """Test check_amdgpu with no driver present"""
        self.mock_pyudev.list_devices.return_value = [
            MagicMock(
                properties={"PCI_CLASS": "30000", "PCI_ID": "1002abcd", "DRIVER": None}
            )
        ]
        result = self.validator.check_amdgpu()
        self.assertFalse(result)
        self.assertTrue(
            any(isinstance(f, MissingAmdgpu) for f in self.validator.failures)
        )

    def test_check_amdgpu_with_driver(self):
        """Test check_amdgpu with driver present"""
        self.mock_pyudev.list_devices.return_value = [
            MagicMock(
                properties={
                    "PCI_CLASS": "30000",
                    "PCI_ID": "1002abcd",
                    "DRIVER": "amdgpu",
                }
            )
        ]
        result = self.validator.check_amdgpu()
        self.assertTrue(result)

    def test_check_wcn6855_bug_no_bug(self):
        """Test check_wcn6855_bug with no bug present"""
        self.mock_kernel_log.match_pattern.side_effect = lambda pattern: None
        result = self.validator.check_wcn6855_bug()
        self.assertTrue(result)

    def test_check_storage_no_nvme(self):
        """Test check_storage with no NVMe devices"""
        self.mock_pyudev.list_devices.return_value = []
        result = self.validator.check_storage()
        self.assertTrue(result)

    @patch("amd_debug.prerequisites.minimum_kernel", return_value=True)
    def test_check_amd_hsmp_new_kernel(self, _mock_minimum_kernel):
        """Test check_amd_hsmp with CONFIG_AMD_HSMP=y and kernel version >= 6.10"""
        result = self.validator.check_amd_hsmp()
        self.assertTrue(result)

    @patch("amd_debug.prerequisites.read_file", return_value="CONFIG_AMD_HSMP=y")
    @patch("os.path.exists", return_value=True)
    @patch("amd_debug.prerequisites.minimum_kernel", return_value=False)
    def test_check_amd_hsmp_conflict(
        self, _mock_min_kernel, _mock_exists, _mock_read_file
    ):
        """Test check_amd_hsmp with CONFIG_AMD_HSMP=y and kernel version < 6.10"""
        result = self.validator.check_amd_hsmp()
        self.assertFalse(result)
        self.assertTrue(any(isinstance(f, AmdHsmpBug) for f in self.validator.failures))

    def test_check_amd_pmc_no_driver(self):
        """Test check_amd_pmc with no driver"""
        self.mock_pyudev.list_devices.return_value = []
        result = self.validator.check_amd_pmc()
        self.assertFalse(result)
        self.assertTrue(
            any(isinstance(f, MissingAmdPmc) for f in self.validator.failures)
        )

    def test_check_sleep_mode_not_supported(self):
        """Test check_sleep_mode with no sleep mode support"""
        with patch("os.path.exists", return_value=False):
            result = self.validator.check_sleep_mode()
            self.assertFalse(result)

    def test_check_sleep_mode_s2idle(self):
        """Test check_sleep_mode with s2idle mode"""
        with patch("os.path.exists", return_value=True), patch(
            "amd_debug.prerequisites.read_file", return_value="[s2idle]"
        ):
            result = self.validator.check_sleep_mode()
            self.assertTrue(result)

    def test_check_port_pm_override_non_family_19(self):
        """Test check_port_pm_override with non-family 0x19 CPU"""
        self.validator.cpu_family = 0x18
        result = self.validator.check_port_pm_override()
        self.assertTrue(result)

    def test_check_port_pm_override_non_matching_model(self):
        """Test check_port_pm_override with non-matching CPU model"""
        self.validator.cpu_family = 0x19
        self.validator.cpu_model = 0x72
        result = self.validator.check_port_pm_override()
        self.assertTrue(result)

    @patch("amd_debug.prerequisites.version.parse")
    def test_check_port_pm_override_smu_version_too_high(self, mock_version_parse):
        """Test check_port_pm_override with SMU version > 76.60.0"""
        self.validator.cpu_family = 0x19
        self.validator.cpu_model = 0x74
        mock_version_parse.side_effect = lambda v: v if isinstance(v, str) else None
        self.validator.smu_version = "76.61.0"
        result = self.validator.check_port_pm_override()
        self.assertTrue(result)

    @patch("amd_debug.prerequisites.version.parse")
    def test_check_port_pm_override_smu_version_missing(self, mock_version_parse):
        """Test check_port_pm_override with SMU version undefined"""
        self.validator.cpu_family = 0x19
        self.validator.cpu_model = 0x74
        mock_version_parse.side_effect = lambda v: v if isinstance(v, str) else None
        self.validator.smu_version = ""
        result = self.validator.check_port_pm_override()
        self.assertTrue(result)

    @patch("amd_debug.prerequisites.version.parse")
    def test_check_port_pm_override_smu_version_too_low(self, mock_version_parse):
        """Test check_port_pm_override with SMU version < 76.18.0"""
        self.validator.cpu_family = 0x19
        self.validator.cpu_model = 0x74
        mock_version_parse.side_effect = lambda v: v if isinstance(v, str) else None
        self.validator.smu_version = "76.17.0"
        result = self.validator.check_port_pm_override()
        self.assertTrue(result)

    @patch("amd_debug.prerequisites.read_file", return_value="pcie_port_pm=off")
    def test_check_port_pm_override_cmdline_override(self, mock_read_file):
        """Test check_port_pm_override with pcie_port_pm=off in cmdline"""
        self.validator.cpu_family = 0x19
        self.validator.cpu_model = 0x74
        self.validator.smu_version = "76.50.0"
        result = self.validator.check_port_pm_override()
        self.assertTrue(result)

    @patch("amd_debug.prerequisites.read_file", return_value="mocked_cmdline")
    def test_check_port_pm_override_no_override(self, mock_read_file):
        """Test check_port_pm_override without pcie_port_pm=off in cmdline"""
        self.validator.cpu_family = 0x19
        self.validator.cpu_model = 0x74
        self.validator.smu_version = "76.50.0"
        result = self.validator.check_port_pm_override()
        self.assertFalse(result)

    def test_check_iommu_disabled(self):
        """Test check_iommu when IOMMU is disabled"""
        self.validator.cpu_family = 0x1A
        self.validator.cpu_model = 0x20
        self.mock_pyudev.list_devices.return_value = []
        result = self.validator.check_iommu()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_called_with("IOMMU disabled", "✅")

    @patch(
        "amd_debug.prerequisites.open",
        new_callable=unittest.mock.mock_open,
        read_data=b"\x00" * 45,
    )
    @patch("amd_debug.prerequisites.os.path.exists", return_value=True)
    def test_check_iommu_no_dma_protection_no_msft0201(self, _mock_open, _mock_exists):
        """Test check_iommu when DMA protection is not enabled and no MSFT0201 in IVRS"""
        self.validator.cpu_family = 0x1A
        self.validator.cpu_model = 0x20
        iommu_device = MagicMock(sys_path="/sys/devices/iommu")
        acpi_device = MagicMock(sys_path="/sys/devices/acpi/MSFT0201")
        platform_device = MagicMock(sys_path="/sys/devices/platform/MSFT0201")
        self.mock_pyudev.list_devices.side_effect = [
            [iommu_device],
            [acpi_device],
            [platform_device],
        ]
        result = self.validator.check_iommu()
        self.assertFalse(result)
        self.assertTrue(
            any(isinstance(f, DMArNotEnabled) for f in self.validator.failures)
        )
        self.mock_db.record_prereq.assert_called_with(
            "IOMMU is misconfigured: Pre-boot DMA protection not enabled", "❌"
        )

    @patch(
        "amd_debug.prerequisites.open",
        new_callable=unittest.mock.mock_open,
        read_data=b"\x00" * 45 + "MSFT0201".encode("utf-8"),
    )
    @patch("amd_debug.prerequisites.os.path.exists", return_value=True)
    def test_check_iommu_no_dma_protection_BUT_msft0201(self, _mock_open, _mock_exists):
        """Test check_iommu when DMA protection is not enabled BUT MSFT0201 is in IVRS"""
        self.validator.cpu_family = 0x1A
        self.validator.cpu_model = 0x20
        iommu_device = MagicMock(sys_path="/sys/devices/iommu")
        acpi_device = MagicMock(sys_path="/sys/devices/acpi/MSFT0201")
        platform_device = MagicMock(sys_path="/sys/devices/platform/MSFT0201")
        self.mock_pyudev.list_devices.side_effect = [
            [iommu_device],
            [acpi_device],
            [platform_device],
        ]
        result = self.validator.check_iommu()
        self.assertTrue(result)

    @patch(
        "amd_debug.prerequisites.open",
        new_callable=unittest.mock.mock_open,
        read_data=b"\x00" * 36 + b"\xff" * 4,
    )
    def test_check_iommu_missing_acpi_device(self, _mock_open):
        """Test check_iommu when MSFT0201 ACPI device is missing"""
        self.validator.cpu_family = 0x1A
        self.validator.cpu_model = 0x20
        iommu_device = MagicMock(sys_path="/sys/devices/iommu")
        self.mock_pyudev.list_devices.side_effect = [
            [iommu_device],
            [],
            [],
        ]
        result = self.validator.check_iommu()
        self.assertFalse(result)
        self.assertTrue(
            any(isinstance(f, MissingIommuACPI) for f in self.validator.failures)
        )
        self.mock_db.record_prereq.assert_called_with(
            "IOMMU is misconfigured: missing MSFT0201 ACPI device", "❌"
        )

    @patch(
        "amd_debug.prerequisites.open",
        new_callable=unittest.mock.mock_open,
        read_data=b"\x00" * 36 + b"\xff" * 4,
    )
    def test_check_iommu_missing_policy(self, _mock_open):
        """Test check_iommu when policy is not bound to MSFT0201"""
        self.validator.cpu_family = 0x1A
        self.validator.cpu_model = 0x20
        iommu_device = MagicMock(sys_path="/sys/devices/iommu")
        acpi_device = MagicMock(sys_path="/sys/devices/acpi/MSFT0201")
        platform_device = MagicMock(sys_path="/sys/devices/platform/MSFT0201")
        self.mock_pyudev.list_devices.side_effect = [
            [iommu_device],
            [acpi_device],
            [platform_device],
        ]
        result = self.validator.check_iommu()
        self.assertFalse(result)
        self.assertTrue(
            any(isinstance(f, MissingIommuPolicy) for f in self.validator.failures)
        )

    @patch(
        "amd_debug.prerequisites.open",
        new_callable=unittest.mock.mock_open,
        read_data=b"\x00" * 36 + b"\xff" * 4,
    )
    @patch("amd_debug.prerequisites.os.path.exists", return_value=True)
    def test_check_iommu_properly_configured(self, _mock_open, _mock_exists):
        """Test check_iommu when IOMMU is properly configured"""
        self.validator.cpu_family = 0x1A
        self.validator.cpu_model = 0x20
        iommu_device = MagicMock(sys_path="/sys/devices/iommu")
        acpi_device = MagicMock(sys_path="/sys/devices/acpi/MSFT0201")
        platform_device = MagicMock(sys_path="/sys/devices/platform/MSFT0201")
        self.mock_pyudev.list_devices.side_effect = [
            [iommu_device],
            [acpi_device],
            [platform_device],
        ]
        result = self.validator.check_iommu()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_called_with("IOMMU properly configured", "✅")

    @patch("amd_debug.prerequisites.read_file")
    @patch("amd_debug.validator.print_color")
    def test_check_taint_not_tainted(self, _mock_print_color, mock_read_file):
        """Test check_taint when the kernel is not tainted"""
        mock_read_file.return_value = "0"
        result = self.validator.check_taint()
        self.assertTrue(result)
        self.assertFalse(
            any(isinstance(f, TaintedKernel) for f in self.validator.failures)
        )

    @patch("amd_debug.prerequisites.read_file")
    @patch("amd_debug.validator.print_color")
    def test_check_taint_tainted(self, _mock_print_color, mock_read_file):
        """Test check_taint when the kernel is tainted"""
        mock_read_file.return_value = str(
            BIT(9) | 1
        )  # Kernel warnings ignored, other taint present
        result = self.validator.check_taint()
        self.assertTrue(result)
        self.assertTrue(
            any(isinstance(f, TaintedKernel) for f in self.validator.failures)
        )

    @patch("amd_debug.prerequisites.read_file")
    @patch("amd_debug.validator.print_color")
    def test_check_taint_file_not_found(self, _mock_print_color, mock_read_file):
        """Test check_taint when the tainted file is not found"""
        mock_read_file.side_effect = FileNotFoundError
        with self.assertRaises(FileNotFoundError):
            self.validator.check_taint()

    @patch("amd_debug.prerequisites.read_file")
    @patch("amd_debug.validator.print_color")
    def test_check_taint_invalid_value(self, _mock_print_color, mock_read_file):
        """Test check_taint when the tainted file contains invalid data"""
        mock_read_file.return_value = "invalid"
        with self.assertRaises(ValueError):
            self.validator.check_taint()

    @patch("amd_debug.prerequisites.read_file")
    def test_check_smt_not_supported(self, mock_read_file):
        """Test check_smt when SMT is not supported"""
        mock_read_file.side_effect = ["notsupported"]
        result = self.validator.check_smt()
        self.assertTrue(result)
        self.mock_db.record_debug.assert_called_with("SMT control: notsupported")

    @patch("amd_debug.prerequisites.read_file")
    def test_check_smt_disabled(self, mock_read_file):
        """Test check_smt when SMT is disabled"""
        mock_read_file.side_effect = ["on", "0"]
        result = self.validator.check_smt()
        self.assertFalse(result)
        self.assertTrue(
            any(isinstance(f, SMTNotEnabled) for f in self.validator.failures)
        )
        self.mock_db.record_prereq.assert_called_with("SMT is not enabled", "❌")

    @patch("amd_debug.prerequisites.read_file")
    def test_check_smt_enabled(self, mock_read_file):
        """Test check_smt when SMT is enabled"""
        mock_read_file.side_effect = ["on", "1"]
        result = self.validator.check_smt()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_called_with("SMT enabled", "✅")

    @patch("amd_debug.prerequisites.read_msr")
    def test_check_msr_pc6_disabled(self, mock_read_msr):
        """Test check_msr when PC6 is disabled"""
        mock_read_msr.side_effect = lambda reg, _: (
            0 if reg == 0xC0010292 else BIT(22) | BIT(14) | BIT(6)
        )
        result = self.validator.check_msr()
        self.assertFalse(result)
        self.assertTrue(any(isinstance(f, MSRFailure) for f in self.validator.failures))

    @patch("amd_debug.prerequisites.read_msr")
    def test_check_msr_cc6_disabled(self, mock_read_msr):
        """Test check_msr when CC6 is disabled"""
        mock_read_msr.side_effect = lambda reg, _: BIT(32) if reg == 0xC0010292 else 0
        result = self.validator.check_msr()
        self.assertFalse(result)
        self.assertTrue(any(isinstance(f, MSRFailure) for f in self.validator.failures))

    @patch("amd_debug.prerequisites.read_msr")
    def test_check_msr_enabled(self, mock_read_msr):
        """Test check_msr when PC6 and CC6 are enabled"""
        mock_read_msr.side_effect = lambda reg, _: (
            BIT(32) if reg == 0xC0010292 else (BIT(22) | BIT(14) | BIT(6))
        )
        result = self.validator.check_msr()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_called_with("PC6 and CC6 enabled", "✅")

    @patch("amd_debug.prerequisites.read_msr")
    def test_check_msr_file_not_found(self, mock_read_msr):
        """Test check_msr when MSR file is not found"""
        mock_read_msr.side_effect = FileNotFoundError
        result = self.validator.check_msr()
        self.assertFalse(result)
        self.mock_db.record_prereq.assert_called_with(
            "Unable to check MSRs: MSR kernel module not loaded", "❌"
        )

    @patch("amd_debug.prerequisites.read_msr")
    def test_check_msr_permission_error(self, mock_read_msr):
        """Test check_msr when there is a permission error"""
        mock_read_msr.side_effect = PermissionError
        result = self.validator.check_msr()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_called_with("MSR checks unavailable", "🚦")

    @patch("amd_debug.prerequisites.read_file")
    @patch("amd_debug.prerequisites.os.path.exists", return_value=True)
    def test_check_cpu_unsupported_model(self, mock_path_exists, mock_read_file):
        """Test check_cpu with an unsupported CPU model"""
        self.validator.cpu_family = 0x19
        self.validator.cpu_model = 0x08
        mock_read_file.return_value = "7"
        result = self.validator.check_cpu()
        self.assertFalse(result)
        self.assertTrue(
            any(isinstance(f, UnsupportedModel) for f in self.validator.failures)
        )
        self.mock_db.record_prereq.assert_called_with(
            "This CPU model does not support hardware sleep over s2idle", "❌"
        )

    @patch("amd_debug.prerequisites.os.walk")
    @patch(
        "amd_debug.prerequisites.open",
        new_callable=unittest.mock.mock_open,
        read_data=b"mocked_data",
    )
    @patch("amd_debug.prerequisites.tempfile.mkdtemp", return_value="/mocked/tempdir")
    @patch("amd_debug.prerequisites.subprocess.check_call")
    @patch("amd_debug.prerequisites.shutil.rmtree")
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

    @patch("amd_debug.prerequisites.os.walk")
    @patch(
        "amd_debug.prerequisites.open",
        new_callable=unittest.mock.mock_open,
        read_data=b"mocked_data",
    )
    @patch("amd_debug.prerequisites.tempfile.mkdtemp", return_value="/mocked/tempdir")
    @patch(
        "amd_debug.prerequisites.subprocess.check_call",
        side_effect=subprocess.CalledProcessError(1, "iasl"),
    )
    @patch("amd_debug.prerequisites.shutil.rmtree")
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

    @patch("amd_debug.prerequisites.os.walk")
    @patch(
        "amd_debug.prerequisites.open",
        new_callable=unittest.mock.mock_open,
        read_data=b"mocked_data",
    )
    @patch("amd_debug.prerequisites.tempfile.mkdtemp", return_value="/mocked/tempdir")
    @patch("amd_debug.prerequisites.subprocess.check_call")
    @patch("amd_debug.prerequisites.shutil.rmtree")
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

    @patch("amd_debug.prerequisites.os.path.exists")
    @patch("amd_debug.prerequisites.read_file")
    @patch("amd_debug.prerequisites.os.readlink")
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

    @patch("amd_debug.prerequisites.os.path.exists")
    @patch("amd_debug.prerequisites.read_file")
    def test_map_acpi_path_no_devices(self, mock_read_file, mock_path_exists):
        """Test map_acpi_path with no valid ACPI devices"""
        mock_path_exists.return_value = False
        self.mock_pyudev.list_devices.return_value = []

        result = self.validator.map_acpi_path()
        self.assertTrue(result)

    @patch("amd_debug.prerequisites.os.path.exists")
    @patch("amd_debug.prerequisites.read_file")
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

    @patch("amd_debug.prerequisites.os.path.exists")
    @patch("amd_debug.prerequisites.read_file")
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

    @patch("amd_debug.prerequisites.read_file")
    @patch("amd_debug.prerequisites.os.path.exists")
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

    @patch("amd_debug.prerequisites.read_file")
    @patch("amd_debug.prerequisites.os.path.exists")
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

    @patch("amd_debug.prerequisites.read_file")
    @patch("amd_debug.prerequisites.os.path.exists")
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

    @patch("amd_debug.prerequisites.read_file")
    def test_check_aspm_default_policy(self, mock_read_file):
        """Test check_aspm when the policy is set to default"""
        mock_read_file.return_value = "[default]"
        result = self.validator.check_aspm()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_called_with(
            "ASPM policy set to 'default'", "✅"
        )

    @patch("amd_debug.prerequisites.read_file")
    def test_check_aspm_non_default_policy(self, mock_read_file):
        """Test check_aspm when the policy is not set to default"""
        mock_read_file.return_value = "[performance]"
        result = self.validator.check_aspm()
        self.assertFalse(result)
        self.mock_db.record_prereq.assert_called_with(
            "ASPM policy set to [performance]", "❌"
        )
        self.assertTrue(any(isinstance(f, ASpmWrong) for f in self.validator.failures))

    @patch("amd_debug.prerequisites.read_file")
    def test_check_aspm_empty_policy(self, mock_read_file):
        """Test check_aspm when the policy file is empty"""
        mock_read_file.return_value = ""
        result = self.validator.check_aspm()
        self.assertFalse(result)
        self.mock_db.record_prereq.assert_called_with("ASPM policy set to ", "❌")
        self.assertTrue(any(isinstance(f, ASpmWrong) for f in self.validator.failures))

    @patch("amd_debug.prerequisites.read_file")
    def test_check_aspm_file_not_found(self, mock_read_file):
        """Test check_aspm when the policy file is not found"""
        mock_read_file.side_effect = FileNotFoundError
        with self.assertRaises(FileNotFoundError):
            self.validator.check_aspm()

    @patch("amd_debug.prerequisites.os.path.exists")
    @patch("amd_debug.prerequisites.read_file")
    def test_check_i2c_hid_no_devices(self, mock_read_file, mock_path_exists):
        """Test check_i2c_hid when no I2C HID devices are found"""
        self.mock_pyudev.list_devices.return_value = []
        result = self.validator.check_i2c_hid()
        self.assertTrue(result)

    @patch("amd_debug.prerequisites.os.path.exists")
    @patch("amd_debug.prerequisites.read_file")
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

    @patch("amd_debug.prerequisites.os.path.exists")
    @patch("amd_debug.prerequisites.read_file")
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

    @patch("amd_debug.prerequisites.os.path.exists")
    @patch("amd_debug.prerequisites.read_file")
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

    @patch("amd_debug.prerequisites.os.path.exists", return_value=True)
    @patch(
        "amd_debug.prerequisites.open",
        new_callable=unittest.mock.mock_open,
        read_data=b"\x00" * 0x70 + b"\x20\x00\x00\x00",
    )
    @patch("amd_debug.prerequisites.struct.unpack", return_value=(0x00200000,))
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

    @patch("amd_debug.prerequisites.os.path.exists", return_value=True)
    @patch(
        "amd_debug.prerequisites.open",
        new_callable=unittest.mock.mock_open,
        read_data=b"\x00" * 0x70 + b"\x00\x00\x00\x00",
    )
    @patch("amd_debug.prerequisites.struct.unpack", return_value=(0x00000000,))
    def test_check_fadt_does_not_support_low_power_idle(
        self, mock_unpack, mock_open, mock_path_exists
    ):
        """Test check_fadt when ACPI FADT does not support Low-power S0 idle"""
        self.mock_kernel_log.match_line.return_value = False
        result = self.validator.check_fadt()
        self.assertFalse(result)
        self.assertTrue(any(isinstance(f, FadtWrong) for f in self.validator.failures))

    def test_check_fadt_file_not_found(self):
        """Test check_fadt when FADT file is not found"""
        self.mock_kernel_log.match_line.return_value = False
        result = self.validator.check_fadt()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_called_with("FADT check unavailable", "🚦")

    @patch("amd_debug.prerequisites.os.path.exists", return_value=True)
    @patch("amd_debug.prerequisites.open", side_effect=PermissionError)
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
        "amd_debug.prerequisites.open",
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

    @patch("amd_debug.prerequisites.read_file")
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

    @patch("amd_debug.prerequisites.read_file")
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

    @patch("amd_debug.prerequisites.read_file")
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

    @patch("amd_debug.prerequisites.read_file")
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

    @patch("amd_debug.prerequisites.read_file")
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

    @patch("amd_debug.prerequisites.read_file")
    def test_get_cpu_vendor_empty_cpuinfo(self, mock_read_file):
        """Test get_cpu_vendor when /proc/cpuinfo is empty"""
        mock_read_file.return_value = ""
        vendor = self.validator.get_cpu_vendor()
        self.assertEqual(vendor, "")
        self.assertIsNone(self.validator.cpu_family)
        self.assertIsNone(self.validator.cpu_model)
        self.assertIsNone(self.validator.cpu_model_string)
        self.mock_db.record_prereq.assert_not_called()

    def test_check_usb4_driver_missing(self):
        """Test check_usb4 when the thunderbolt driver is missing"""
        self.mock_pyudev.list_devices.return_value = [
            MagicMock(
                properties={
                    "PCI_SLOT_NAME": "0000:00:1d.0",
                    "DRIVER": None,
                }
            )
        ]
        result = self.validator.check_usb4()
        self.assertFalse(result)
        self.assertTrue(
            any(isinstance(f, MissingThunderbolt) for f in self.validator.failures)
        )
        self.mock_db.record_prereq.assert_called_with(
            "USB4 driver `thunderbolt` missing", "❌"
        )

    def test_check_usb4_driver_present(self):
        """Test check_usb4 when the thunderbolt driver is present"""
        self.mock_pyudev.list_devices.return_value = [
            MagicMock(
                properties={
                    "PCI_SLOT_NAME": "0000:00:1d.0",
                    "DRIVER": "thunderbolt",
                }
            )
        ]
        result = self.validator.check_usb4()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_called_with(
            "USB4 driver `thunderbolt` bound to 0000:00:1d.0", "✅"
        )

    def test_check_usb4_no_devices(self):
        """Test check_usb4 when no USB4 devices are found"""
        self.mock_pyudev.list_devices.return_value = []
        result = self.validator.check_usb4()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_not_called()

    @patch("amd_debug.prerequisites.os.path.exists", return_value=False)
    def test_capture_smbios_not_setup(self, mock_path_exists):
        """Test capture_smbios when DMI data is not set up"""
        self.validator.capture_smbios()
        self.mock_db.record_prereq.assert_called_with("DMI data was not setup", "🚦")
        self.assertTrue(
            any(isinstance(f, DmiNotSetup) for f in self.validator.failures)
        )

    @patch("amd_debug.prerequisites.os.walk")
    @patch("amd_debug.prerequisites.read_file")
    @patch("amd_debug.prerequisites.os.path.exists", return_value=True)
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

    @patch("amd_debug.prerequisites.os.walk")
    @patch("amd_debug.prerequisites.read_file")
    @patch("amd_debug.prerequisites.os.path.exists", return_value=True)
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

    @patch("amd_debug.prerequisites.os.walk")
    @patch("amd_debug.prerequisites.read_file")
    @patch("amd_debug.prerequisites.os.path.exists", return_value=True)
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

    @patch("amd_debug.prerequisites.os.path.exists")
    @patch("amd_debug.prerequisites.read_file")
    def test_check_lps0_enabled(self, mock_read_file, mock_path_exists):
        """Test check_lps0 when LPS0 is enabled"""
        mock_path_exists.return_value = True
        mock_read_file.return_value = "N"
        result = self.validator.check_lps0()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_called_with("LPS0 _DSM enabled", "✅")

    @patch("amd_debug.prerequisites.os.path.exists")
    @patch("amd_debug.prerequisites.read_file")
    def test_check_lps0_disabled(self, mock_read_file, mock_path_exists):
        """Test check_lps0 when LPS0 is disabled"""
        mock_path_exists.return_value = True
        mock_read_file.return_value = "Y"
        result = self.validator.check_lps0()
        self.assertFalse(result)
        self.mock_db.record_prereq.assert_called_with("LPS0 _DSM disabled", "❌")

    @patch("amd_debug.prerequisites.os.path.exists")
    def test_check_lps0_not_found(self, mock_path_exists):
        """Test check_lps0 when LPS0 parameter is not found"""
        mock_path_exists.return_value = False
        result = self.validator.check_lps0()
        self.assertFalse(result)
        self.mock_db.record_prereq.assert_called_with("LPS0 _DSM not found", "👀")

    @patch("amd_debug.prerequisites.os.path.exists")
    @patch(
        "builtins.open",
        new_callable=unittest.mock.mock_open,
        read_data="ignore_wake_value",
    )
    def test_capture_disabled_pins_with_parameters(self, _mock_open, mock_path_exists):
        """Test capture_disabled_pins when parameters are present and configured"""
        mock_path_exists.side_effect = (
            lambda path: "ignore_wake" in path or "ignore_interrupt" in path
        )
        self.validator.capture_disabled_pins()
        self.mock_db.record_debug.assert_called_with(
            "Disabled pins:\n/sys/module/gpiolib_acpi/parameters/ignore_wake is configured to ignore_wake_value\n/sys/module/gpiolib_acpi/parameters/ignore_interrupt is configured to ignore_wake_value\n"
        )

    @patch("amd_debug.prerequisites.os.path.exists")
    @patch("builtins.open", new_callable=unittest.mock.mock_open, read_data="(null)")
    def test_capture_disabled_pins_with_null_values(self, _mock_open, mock_path_exists):
        mock_path_exists.side_effect = (
            lambda path: "ignore_wake" in path or "ignore_interrupt" in path
        )
        self.validator.capture_disabled_pins()
        self.mock_db.record_debug.assert_not_called()

    @patch("amd_debug.prerequisites.os.path.exists", return_value=False)
    def test_capture_disabled_pins_no_parameters(self, _mock_path_exists):
        """Test capture_disabled_pins when parameters are not present"""
        self.validator.capture_disabled_pins()
        self.mock_db.record_debug.assert_not_called()

    @patch("amd_debug.prerequisites.os.listdir")
    @patch("amd_debug.prerequisites.os.path.isdir")
    @patch("amd_debug.prerequisites.WakeIRQ")
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

    @patch("amd_debug.prerequisites.os.listdir")
    @patch("amd_debug.prerequisites.os.path.isdir")
    def test_capture_irq_no_irqs(self, mock_isdir, mock_listdir):
        """Test capture_irq when no IRQ directories are present"""
        mock_listdir.return_value = []
        mock_isdir.return_value = False

        result = self.validator.capture_irq()

        self.assertTrue(result)
        self.assertEqual(self.validator.irqs, [])
        self.mock_db.record_debug.assert_called_with("Interrupts")

    @patch("amd_debug.prerequisites.os.listdir")
    @patch("amd_debug.prerequisites.os.path.isdir")
    @patch("amd_debug.prerequisites.WakeIRQ")
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

    @patch("amd_debug.prerequisites.os.path.exists", return_value=True)
    @patch("builtins.open", new_callable=unittest.mock.mock_open)
    def test_check_permissions_success(self, _mock_open, _mock_path_exists):
        """Test check_permissions when the user has write permissions"""
        result = self.validator.check_permissions()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_not_called()

    @patch("amd_debug.prerequisites.os.path.exists", return_value=True)
    @patch("builtins.open", side_effect=PermissionError)
    def test_check_permissions_permission_error(self, _mock_open, _mock_path_exists):
        """Test check_permissions when the user lacks write permissions"""
        result = self.validator.check_permissions()
        self.assertFalse(result)

    @patch("amd_debug.prerequisites.os.path.exists", return_value=False)
    @patch("builtins.open", side_effect=FileNotFoundError)
    def test_check_permissions_file_not_found(self, _mock_open, _mock_path_exists):
        """Test check_permissions when the /sys/power/state file is not found"""
        result = self.validator.check_permissions()
        self.assertFalse(result)
        self.mock_db.record_prereq.assert_called_with(
            "Kernel doesn't support power management", "❌"
        )

    @patch("amd_debug.prerequisites.read_file")
    @patch("amd_debug.prerequisites.os.path.exists", return_value=True)
    def test_check_pinctrl_amd_driver_loaded(self, mock_path_exists, mock_read_file):
        """Test check_pinctrl_amd when the driver is loaded and debug information is available"""
        mock_read_file.return_value = (
            "trigger\n" "edge\n" "level\n" "WAKE_INT_MASTER_REG: 8000\n"
        )
        self.mock_pyudev.list_devices.return_value = [
            MagicMock(properties={"DRIVER": "amd_gpio"})
        ]

        result = self.validator.check_pinctrl_amd()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_called_with(
            "GPIO driver `pinctrl_amd` available", "✅"
        )
        self.mock_db.record_debug.assert_called_with("trigger\nedge\nlevel\n")

    @patch("amd_debug.prerequisites.read_file")
    @patch("amd_debug.prerequisites.os.path.exists", return_value=True)
    def test_check_pinctrl_amd_driver_loaded_with_permission_error(
        self, mock_path_exists, mock_read_file
    ):
        """Test check_pinctrl_amd when the driver is loaded but debug file cannot be read due to permission error"""
        mock_read_file.side_effect = PermissionError
        self.mock_pyudev.list_devices.return_value = [
            MagicMock(properties={"DRIVER": "amd_gpio"})
        ]

        result = self.validator.check_pinctrl_amd()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_called_with(
            "GPIO driver `pinctrl_amd` available", "✅"
        )
        self.mock_db.record_debug.assert_called_with(
            "Unable to capture /sys/kernel/debug/gpio"
        )

    @patch("amd_debug.prerequisites.read_file")
    @patch("amd_debug.prerequisites.os.path.exists", return_value=True)
    def test_check_pinctrl_amd_unserviced_gpio(self, _mock_path_exists, mock_read_file):
        """Test check_pinctrl_amd when unserviced GPIO is detected"""
        mock_read_file.return_value = "🔥"
        self.mock_pyudev.list_devices.return_value = [
            MagicMock(properties={"DRIVER": "amd_gpio"})
        ]

        result = self.validator.check_pinctrl_amd()
        self.assertFalse(result)
        self.assertTrue(
            any(isinstance(f, UnservicedGpio) for f in self.validator.failures)
        )

    @patch("amd_debug.prerequisites.read_file")
    @patch("amd_debug.prerequisites.os.path.exists", return_value=True)
    def test_check_pinctrl_amd_no_debug_info(self, mock_path_exists, mock_read_file):
        """Test check_pinctrl_amd when the driver is loaded but no debug information is available"""
        mock_read_file.return_value = ""
        self.mock_pyudev.list_devices.return_value = [
            MagicMock(properties={"DRIVER": "amd_gpio"})
        ]

        result = self.validator.check_pinctrl_amd()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_called_with(
            "GPIO driver `pinctrl_amd` available", "✅"
        )
        self.mock_db.record_debug.assert_not_called()

    def test_check_pinctrl_amd_driver_not_loaded(self):
        """Test check_pinctrl_amd when the driver is not loaded"""
        self.mock_pyudev.list_devices.return_value = []

        result = self.validator.check_pinctrl_amd()
        self.assertFalse(result)
        self.mock_db.record_prereq.assert_called_with(
            "GPIO driver `pinctrl_amd` not loaded", "❌"
        )

    @patch("amd_debug.prerequisites.os.path.exists")
    @patch("amd_debug.prerequisites.read_file")
    def test_check_asus_rog_ally_mcu_version_too_old(
        self, mock_read_file, mock_path_exists
    ):
        """Test check_asus_rog_ally when MCU version is too old"""
        mock_path_exists.side_effect = lambda p: "mcu_version" in p
        mock_read_file.side_effect = lambda p: "318" if "mcu_version" in p else ""
        self.mock_pyudev.list_devices.side_effect = [
            [MagicMock(sys_path="/sys/devices/hid1", properties={"HID_ID": "1ABE"})],
            [],
        ]

        result = self.validator.check_asus_rog_ally()
        self.assertFalse(result)
        self.mock_db.record_prereq.assert_called_with(
            "ROG Ally MCU firmware too old", "❌"
        )
        self.assertTrue(
            any(isinstance(f, RogAllyOldMcu) for f in self.validator.failures)
        )

    @patch("amd_debug.prerequisites.os.path.exists")
    @patch("amd_debug.prerequisites.read_file")
    def test_check_asus_rog_ally_mcu_version_valid(
        self, mock_read_file, mock_path_exists
    ):
        """Test check_asus_rog_ally when MCU version is valid"""
        mock_path_exists.side_effect = lambda p: "mcu_version" in p
        mock_read_file.side_effect = lambda p: "320" if "mcu_version" in p else ""
        self.mock_pyudev.list_devices.side_effect = [
            [MagicMock(sys_path="/sys/devices/hid1", properties={"HID_ID": "1ABE"})],
            [],
        ]

        result = self.validator.check_asus_rog_ally()
        self.assertTrue(result)

    @patch("amd_debug.prerequisites.os.path.exists")
    @patch("amd_debug.prerequisites.read_file")
    def test_check_asus_rog_ally_mcu_powersave_disabled(
        self, mock_read_file, mock_path_exists
    ):
        """Test check_asus_rog_ally when MCU powersave is disabled"""
        mock_path_exists.side_effect = lambda p: "current_value" in p
        mock_read_file.side_effect = lambda p: "0" if "current_value" in p else ""
        self.mock_pyudev.list_devices.side_effect = [
            [],
            [MagicMock(sys_path="/sys/devices/firmware1")],
        ]

        result = self.validator.check_asus_rog_ally()
        self.assertFalse(result)
        self.mock_db.record_prereq.assert_called_with(
            "Rog Ally doesn't have MCU powersave enabled", "❌"
        )
        self.assertTrue(
            any(isinstance(f, RogAllyMcuPowerSave) for f in self.validator.failures)
        )

    @patch("amd_debug.prerequisites.os.path.exists")
    @patch("amd_debug.prerequisites.read_file")
    def test_check_asus_rog_ally_mcu_powersave_enabled(
        self, mock_read_file, mock_path_exists
    ):
        """Test check_asus_rog_ally when MCU powersave is enabled"""
        mock_path_exists.side_effect = lambda p: "current_value" in p
        mock_read_file.side_effect = lambda p: "1" if "current_value" in p else ""
        self.mock_pyudev.list_devices.side_effect = [
            [],
            [MagicMock(sys_path="/sys/devices/firmware1")],
        ]

        result = self.validator.check_asus_rog_ally()
        self.assertTrue(result)

    @patch("amd_debug.prerequisites.os.path.exists")
    @patch("amd_debug.prerequisites.read_file")
    def test_check_asus_rog_ally_no_devices(self, _mock_read_file, mock_path_exists):
        """Test check_asus_rog_ally when no devices are found"""
        mock_path_exists.return_value = False
        self.mock_pyudev.list_devices.side_effect = [[], []]

        result = self.validator.check_asus_rog_ally()
        self.assertTrue(result)

    @patch("amd_debug.prerequisites.subprocess.check_output")
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

    @patch("amd_debug.prerequisites.subprocess.check_output")
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

    @patch("amd_debug.prerequisites.subprocess.check_output")
    def test_check_network_wol_not_supported(self, mock_check_output):
        """Test check_network when WoL is not supported"""
        self.mock_pyudev.list_devices.return_value = [
            MagicMock(properties={"INTERFACE": "eth0"})
        ]
        mock_check_output.return_value = ("Supports Wake-on: d\n").encode("utf-8")

        result = self.validator.check_network()
        self.assertTrue(result)
        self.mock_db.record_debug.assert_called_with("eth0 doesn't support WoL (d)")

    @patch("amd_debug.prerequisites.subprocess.check_output")
    def test_check_network_no_devices(self, mock_check_output):
        """Test check_network when no network devices are found"""
        self.mock_pyudev.list_devices.return_value = []

        result = self.validator.check_network()
        self.assertTrue(result)
        self.mock_db.record_debug.assert_not_called()
        self.mock_db.record_prereq.assert_not_called()

    @patch(
        "amd_debug.prerequisites.subprocess.check_output",
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

    @patch("amd_debug.prerequisites.version.parse")
    def test_check_amd_cpu_hpet_wa_family_17_model_68(self, mock_version_parse):
        """Test check_amd_cpu_hpet_wa for family 0x17, model 0x68"""
        self.validator.cpu_family = 0x17
        self.validator.cpu_model = 0x68
        result = self.validator.check_amd_cpu_hpet_wa()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_called_with(
            "Timer based wakeup doesn't work properly for your ASIC/firmware, please manually wake the system",
            "🚦",
        )

    @patch("amd_debug.prerequisites.version.parse")
    def test_check_amd_cpu_hpet_wa_family_17_model_60(self, mock_version_parse):
        """Test check_amd_cpu_hpet_wa for family 0x17, model 0x60"""
        self.validator.cpu_family = 0x17
        self.validator.cpu_model = 0x60
        result = self.validator.check_amd_cpu_hpet_wa()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_called_with(
            "Timer based wakeup doesn't work properly for your ASIC/firmware, please manually wake the system",
            "🚦",
        )

    @patch("amd_debug.prerequisites.version.parse")
    def test_check_amd_cpu_hpet_wa_family_19_model_50_smu_version_low(
        self, mock_version_parse
    ):
        """Test check_amd_cpu_hpet_wa for family 0x19, model 0x50 with SMU version < 64.53.0"""
        self.validator.cpu_family = 0x19
        self.validator.cpu_model = 0x50
        self.validator.smu_version = "64.52.0"
        mock_version_parse.side_effect = lambda v: v if isinstance(v, str) else None
        result = self.validator.check_amd_cpu_hpet_wa()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_called_with(
            "Timer based wakeup doesn't work properly for your ASIC/firmware, please manually wake the system",
            "🚦",
        )

    @patch("amd_debug.prerequisites.version.parse")
    def test_check_amd_cpu_hpet_wa_family_19_model_50_smu_version_high(
        self, mock_version_parse
    ):
        """Test check_amd_cpu_hpet_wa for family 0x19, model 0x50 with SMU version >= 64.53.0"""
        self.validator.cpu_family = 0x19
        self.validator.cpu_model = 0x50
        self.validator.smu_version = "64.53.0"
        mock_version_parse.side_effect = lambda v: v if isinstance(v, str) else None
        result = self.validator.check_amd_cpu_hpet_wa()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_not_called()

    def test_check_amd_cpu_hpet_wa_family_19_non_matching_model(self):
        """Test check_amd_cpu_hpet_wa for family 0x19 with non-matching model"""
        self.validator.cpu_family = 0x19
        self.validator.cpu_model = 0x51
        result = self.validator.check_amd_cpu_hpet_wa()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_not_called()

    def test_check_amd_cpu_hpet_wa_non_matching_family(self):
        """Test check_amd_cpu_hpet_wa for non-matching CPU family"""
        self.validator.cpu_family = 0x18
        self.validator.cpu_model = 0x68
        result = self.validator.check_amd_cpu_hpet_wa()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_not_called()

    @patch("amd_debug.prerequisites.os.path.exists")
    def test_capture_linux_firmware_debug_files_exist(self, mock_path_exists):
        """Test capture_linux_firmware when debug files exist"""
        mock_path_exists.side_effect = lambda path: "amdgpu_firmware_info" in path

        self.validator.distro = "ubuntu"
        self.validator.capture_linux_firmware()

        self.mock_db.record_debug_file.assert_any_call(
            "/sys/kernel/debug/dri/0/amdgpu_firmware_info"
        )
        self.mock_db.record_debug_file.assert_any_call(
            "/sys/kernel/debug/dri/1/amdgpu_firmware_info"
        )

    @patch("amd_debug.prerequisites.os.path.exists")
    def test_capture_linux_firmware_debug_files_missing(self, mock_path_exists):
        """Test capture_linux_firmware when debug files are missing"""
        mock_path_exists.return_value = False

        self.validator.distro = "ubuntu"
        self.validator.capture_linux_firmware()

        self.mock_db.record_debug_file.assert_not_called()

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

    def test_check_usb3_no_devices(self):
        """Test check_usb3 when no USB3 devices are found"""
        self.mock_pyudev.list_devices.return_value = []
        result = self.validator.check_usb3()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_not_called()

    def test_check_usb3_driver_missing(self):
        """Test check_usb3 when the xhci_hcd driver is missing"""
        self.mock_pyudev.list_devices.return_value = [
            MagicMock(
                properties={
                    "PCI_SLOT_NAME": "0000:00:1d.0",
                    "DRIVER": None,
                }
            )
        ]
        result = self.validator.check_usb3()
        self.assertFalse(result)
        self.assertTrue(
            any(isinstance(f, MissingXhciHcd) for f in self.validator.failures)
        )
        self.mock_db.record_prereq.assert_called_with(
            "USB3 controller for 0000:00:1d.0 not using `xhci_hcd` driver", "❌"
        )

    def test_check_usb3_driver_present(self):
        """Test check_usb3 when the xhci_hcd driver is present"""
        self.mock_pyudev.list_devices.return_value = [
            MagicMock(
                properties={
                    "PCI_SLOT_NAME": "0000:00:1d.0",
                    "DRIVER": "xhci_hcd",
                }
            )
        ]
        result = self.validator.check_usb3()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_called_with(
            "USB3 driver `xhci_hcd` bound to 0000:00:1d.0", "✅"
        )

    def test_check_usb3_multiple_devices(self):
        """Test check_usb3 with multiple USB3 devices"""
        self.mock_pyudev.list_devices.return_value = [
            MagicMock(
                properties={
                    "PCI_SLOT_NAME": "0000:00:1d.0",
                    "DRIVER": "xhci_hcd",
                }
            ),
            MagicMock(
                properties={
                    "PCI_SLOT_NAME": "0000:00:1d.1",
                    "DRIVER": None,
                }
            ),
        ]
        result = self.validator.check_usb3()
        self.assertFalse(result)
        self.mock_db.record_prereq.assert_any_call(
            "USB3 controller for 0000:00:1d.1 not using `xhci_hcd` driver", "❌"
        )
        self.assertTrue(
            any(isinstance(f, MissingXhciHcd) for f in self.validator.failures)
        )

    def test_check_amd_pmc_driver_loaded(self):
        """Test check_amd_pmc when the driver is loaded"""
        self.mock_pyudev.list_devices.return_value = [
            MagicMock(
                sys_path="/sys/devices/platform/amd_pmc",
                properties={"DRIVER": "amd_pmc"},
            )
        ]
        with patch("amd_debug.prerequisites.os.path.exists", return_value=True), patch(
            "amd_debug.prerequisites.read_file",
            side_effect=["mock_version", "mock_program"],
        ):
            result = self.validator.check_amd_pmc()
            self.assertTrue(result)
            self.mock_db.record_prereq.assert_called_with(
                "PMC driver `amd_pmc` loaded (Program mock_program Firmware mock_version)",
                "✅",
            )

    def test_check_amd_pmc_driver_loaded_timeout_error(self):
        """Test check_amd_pmc when a TimeoutError occurs while reading files"""
        self.mock_pyudev.list_devices.return_value = [
            MagicMock(
                sys_path="/sys/devices/platform/amd_pmc",
                properties={"DRIVER": "amd_pmc"},
            )
        ]
        with patch("amd_debug.prerequisites.os.path.exists", return_value=True), patch(
            "amd_debug.prerequisites.read_file", side_effect=TimeoutError
        ):
            result = self.validator.check_amd_pmc()
            self.assertFalse(result)
            self.mock_db.record_prereq.assert_called_with(
                "failed to communicate using `amd_pmc` driver", "❌"
            )

    def test_check_amd_pmc_driver_not_loaded(self):
        """Test check_amd_pmc when the driver is not loaded"""
        self.mock_pyudev.list_devices.return_value = []
        result = self.validator.check_amd_pmc()
        self.assertFalse(result)
        self.assertTrue(
            any(isinstance(f, MissingAmdPmc) for f in self.validator.failures)
        )
        self.mock_db.record_prereq.assert_called_with(
            "PMC driver `amd_pmc` did not bind to any ACPI device", "❌"
        )

    def test_check_amd_pmc_driver_loaded_no_version_info(self):
        """Test check_amd_pmc when the driver is loaded but version info is missing"""
        self.mock_pyudev.list_devices.return_value = [
            MagicMock(
                sys_path="/sys/devices/platform/amd_pmc",
                properties={"DRIVER": "amd_pmc"},
            )
        ]
        with patch("amd_debug.prerequisites.os.path.exists", return_value=False):
            result = self.validator.check_amd_pmc()
            self.assertTrue(result)
            self.mock_db.record_prereq.assert_called_with(
                "PMC driver `amd_pmc` loaded", "✅"
            )

    @patch("amd_debug.prerequisites.minimum_kernel", return_value=True)
    def test_check_storage_new_kernel(self, _mock_minimum_kernel):
        """Test check_storage when kernel version >= 6.10"""
        self.mock_pyudev.list_devices.return_value = [
            MagicMock(properties={"PCI_SLOT_NAME": "0000:00:1f.0", "DRIVER": "nvme"})
        ]
        result = self.validator.check_storage()
        self.assertTrue(result)

    def test_check_storage_no_kernel_log(self):
        """Test check_storage when kernel log is unavailable"""
        self.validator.kernel_log = None
        result = self.validator.check_storage()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_called_with(
            "Unable to test storage from kernel log", "🚦"
        )

    @patch("amd_debug.prerequisites.subprocess.check_output")
    def test_capture_edid_no_edid_data(self, mock_check_output):
        """Test capture_edid when no EDID data is found"""
        self.validator.display.get_edid = MagicMock(return_value={})
        result = self.validator.capture_edid()
        self.assertTrue(result)
        self.mock_db.record_debug.assert_called_with("No EDID data found")
        mock_check_output.assert_not_called()

    @patch("amd_debug.prerequisites.subprocess.check_output")
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

    @patch("amd_debug.prerequisites.subprocess.check_output")
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

    @patch("amd_debug.prerequisites.subprocess.check_output")
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

    @patch("amd_debug.prerequisites.find_ip_version", return_value=True)
    @patch("amd_debug.prerequisites.os.path.exists")
    @patch("amd_debug.prerequisites.read_file")
    def test_check_dpia_pg_dmcub_usb4_found(
        self, mock_read_file, mock_path_exists, mock_find_ip_version
    ):
        """Test check_dpia_pg_dmcub when USB4 routers are found"""
        usb4_device = MagicMock()
        self.mock_pyudev.list_devices.side_effect = [
            [usb4_device],  # First call: USB4 present
        ]
        result = self.validator.check_dpia_pg_dmcub()
        self.assertTrue(result)
        self.mock_db.record_debug.assert_called_with(
            "USB4 routers found, no need to check DMCUB version"
        )

    @patch("amd_debug.prerequisites.find_ip_version", return_value=True)
    @patch("amd_debug.prerequisites.os.path.exists", return_value=True)
    @patch("amd_debug.prerequisites.read_file", return_value="0x90001B01")
    def test_check_dpia_pg_dmcub_dmcub_fw_version_new_enough(
        self, mock_read_file, mock_path_exists, mock_find_ip_version
    ):
        """Test check_dpia_pg_dmcub when DMCUB firmware version is new enough"""
        self.mock_pyudev.list_devices.side_effect = [
            [],  # First call: no USB4
            [
                MagicMock(
                    properties={
                        "PCI_CLASS": "30000",
                        "PCI_ID": "1002abcd",
                        "PCI_SLOT_NAME": "0000:01:00.0",
                    },
                    sys_path="/sys/devices/pci0000:01/0000:01:00.0",
                )
            ],
        ]
        with patch("builtins.open", new_callable=mock_open, read_data="3") as mock_file:
            handlers = (
                mock_file.return_value,
                mock_open(read_data="5").return_value,
                mock_open(read_data="0").return_value,
            )
            mock_open.side_effect = handlers
            result = self.validator.check_dpia_pg_dmcub()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_not_called()

    @patch("amd_debug.prerequisites.find_ip_version", return_value=True)
    @patch("amd_debug.prerequisites.os.path.exists", return_value=True)
    @patch("amd_debug.prerequisites.read_file", return_value="0x8001B00")
    def test_check_dpia_pg_dmcub_dmcub_fw_version_too_old(
        self, mock_read_file, mock_path_exists, mock_find_ip_version
    ):
        """Test check_dpia_pg_dmcub when DMCUB firmware version is too old"""
        self.mock_pyudev.list_devices.side_effect = [
            [],  # First call: no USB4
            [
                MagicMock(
                    properties={
                        "PCI_CLASS": "30000",
                        "PCI_ID": "1002abcd",
                        "PCI_SLOT_NAME": "0000:01:00.0",
                    },
                    sys_path="/sys/devices/pci0000:01/0000:01:00.0",
                )
            ],
        ]
        result = self.validator.check_dpia_pg_dmcub()
        self.assertFalse(result)
        self.mock_db.record_prereq.assert_called_with(
            "DMCUB Firmware is outdated", "❌"
        )
        self.assertTrue(
            any(isinstance(f, DmcubTooOld) for f in self.validator.failures)
        )

    @patch("amd_debug.prerequisites.find_ip_version", return_value=True)
    @patch("amd_debug.prerequisites.os.path.exists", return_value=False)
    @patch(
        "amd_debug.prerequisites.read_file",
        side_effect=[
            "",  # sysfs read returns empty, so fallback to debugfs
            "DMCUB fw: 09001B00\nOther line\n",  # debugfs read
        ],
    )
    def test_check_dpia_pg_dmcub_debugfs_version_new_enough(
        self, mock_read_file, mock_path_exists, mock_find_ip_version
    ):
        """Test check_dpia_pg_dmcub when DMCUB version is found in debugfs and is new enough"""
        self.mock_pyudev.list_devices.side_effect = [
            [],  # First call: no USB4
            [
                MagicMock(
                    properties={
                        "PCI_CLASS": "30000",
                        "PCI_ID": "1002abcd",
                        "PCI_SLOT_NAME": "0",
                    },
                    sys_path="/sys/devices/pci0000:01/0000:01:00.0",
                )
            ],
        ]
        result = self.validator.check_dpia_pg_dmcub()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_not_called()

    @patch("amd_debug.prerequisites.find_ip_version", return_value=True)
    @patch("amd_debug.prerequisites.os.path.exists", return_value=False)
    @patch(
        "amd_debug.prerequisites.read_file",
        side_effect=[
            "DMCUB fw: 0x08001B00\nOther line\n",  # debugfs read
        ],
    )
    def test_check_dpia_pg_dmcub_debugfs_version_too_old(
        self, mock_read_file, mock_path_exists, mock_find_ip_version
    ):
        """Test check_dpia_pg_dmcub when DMCUB version is found in debugfs and is too old"""
        self.mock_pyudev.list_devices.side_effect = [
            [],  # First call: no USB4
            [
                MagicMock(
                    properties={
                        "PCI_CLASS": "30000",
                        "PCI_ID": "1002abcd",
                        "PCI_SLOT_NAME": "0",
                    },
                    sys_path="/sys/devices/pci0000:01/0000:01:00.0",
                )
            ],
        ]
        result = self.validator.check_dpia_pg_dmcub()
        self.assertFalse(result)
        self.mock_db.record_prereq.assert_called_with(
            "DMCUB Firmware is outdated", "❌"
        )
        self.assertTrue(
            any(isinstance(f, DmcubTooOld) for f in self.validator.failures)
        )

    @patch("amd_debug.prerequisites.find_ip_version", return_value=False)
    def test_check_dpia_pg_dmcub_no_matching_dcn(self, mock_find_ip_version):
        """Test check_dpia_pg_dmcub when no matching DCN is found"""
        self.mock_pyudev.list_devices.side_effect = [
            [],  # First call: no USB4
            [
                MagicMock(
                    properties={
                        "PCI_CLASS": "30000",
                        "PCI_ID": "1002abcd",
                        "PCI_SLOT_NAME": "0",
                    },
                    sys_path="/sys/devices/pci0000:01/0000:01:00.0",
                )
            ],
        ]
        result = self.validator.check_dpia_pg_dmcub()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_not_called()

    @patch("amd_debug.prerequisites.os.path.exists")
    def test_capture_nvidia_version_file_missing(self, mock_exists):
        """Test capture_nvidia when /proc/driver/nvidia/version does not exist"""
        mock_exists.side_effect = lambda p: False if "version" in p else True
        result = self.validator.capture_nvidia()
        self.assertTrue(result)
        self.mock_db.record_debug_file.assert_not_called()
        self.mock_db.record_prereq.assert_not_called()

    @patch("amd_debug.prerequisites.os.path.exists")
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

    @patch("amd_debug.prerequisites.os.walk")
    @patch("amd_debug.prerequisites.os.path.exists")
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

    @patch("amd_debug.prerequisites.os.walk")
    @patch("amd_debug.prerequisites.os.path.exists")
    def test_capture_nvidia_permission_error_on_version(self, mock_exists, mock_walk):
        """Test capture_nvidia when PermissionError occurs reading version file"""
        mock_exists.side_effect = lambda p: True if "version" in p else False
        self.mock_db.record_debug_file.side_effect = PermissionError
        result = self.validator.capture_nvidia()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_called_with(
            "NVIDIA GPU version not readable", "👀"
        )

    @patch("amd_debug.prerequisites.os.walk")
    @patch("amd_debug.prerequisites.os.path.exists")
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
            "NVIDIA GPU {f} not readable", "👀"
        )

    @patch("amd_debug.prerequisites.os.walk")
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

    @patch("amd_debug.prerequisites.os.walk")
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

    @patch("amd_debug.prerequisites.os.walk")
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

    @patch("amd_debug.prerequisites.os.walk")
    @patch("builtins.open", side_effect=PermissionError)
    def test_capture_cstates_permission_error(self, _mock_open, mock_walk):
        """Test capture_cstates when reading cpuidle files raises PermissionError"""
        mock_walk.return_value = [
            ("/sys/bus/cpu/devices/cpu0/cpuidle", [], ["state1"]),
        ]
        with self.assertRaises(PermissionError):
            self.validator.capture_cstates()
        self.mock_db.record_debug.assert_not_called()

    @patch("amd_debug.prerequisites.os.walk")
    def test_capture_cstates_no_files(self, mock_walk):
        """Test capture_cstates when no cpuidle files are present"""
        mock_walk.return_value = [
            ("/sys/bus/cpu/devices/cpu0/cpuidle", [], []),
        ]
        self.validator.capture_cstates()
        self.mock_db.record_debug.assert_called_with("ACPI C-state information\n")

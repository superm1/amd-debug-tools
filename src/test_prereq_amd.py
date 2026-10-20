#!/usr/bin/python3
# SPDX-License-Identifier: MIT

"""
This module contains unit tests for the AMD specific prerequisite functions in the
amd-debug-tools package.
"""

import logging
import struct
import subprocess
import unittest
from unittest.mock import patch, MagicMock, mock_open

from amd_debug.prereq.amd import AmdPrerequisiteValidator
from amd_debug.failures import *
from amd_debug.common import apply_prefix_wrapper, BIT


class TestAmdPrerequisiteValidator(unittest.TestCase):

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
        self.validator = AmdPrerequisiteValidator(tool_debug=True)

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

    @patch("amd_debug.prereq.amd_platform.minimum_kernel", return_value=True)
    def test_check_amd_hsmp_new_kernel(self, _mock_minimum_kernel):
        """Test check_amd_hsmp with CONFIG_AMD_HSMP=y and kernel version >= 6.10"""
        result = self.validator.check_amd_hsmp()
        self.assertTrue(result)

    @patch("amd_debug.prereq.amd_platform.read_file", return_value="CONFIG_AMD_HSMP=y")
    @patch("os.path.exists", return_value=True)
    @patch("amd_debug.prereq.amd_platform.minimum_kernel", return_value=False)
    def test_check_amd_hsmp_conflict(
        self, _mock_min_kernel, _mock_exists, _mock_read_file
    ):
        """Test check_amd_hsmp with CONFIG_AMD_HSMP=y and kernel version < 6.10"""
        result = self.validator.check_amd_hsmp()
        self.assertFalse(result)
        self.assertTrue(any(isinstance(f, AmdHsmpBug) for f in self.validator.failures))

    @patch("amd_debug.prereq.amd_platform.os.path.exists")
    def test_check_amd_xdna_no_driver(self, mock_exists):
        """Test check_amd_xdna when driver is not loaded"""
        mock_exists.return_value = False
        result = self.validator.check_amd_xdna()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_not_called()

    @patch("amd_debug.prereq.amd_platform.os.path.exists")
    def test_check_amd_xdna_no_iommu(self, mock_exists):
        """Test check_amd_xdna when IOMMU is disabled"""
        mock_exists.side_effect = lambda p: True if "amdxdna" in p else False

        def mock_list_devices(**kwargs):
            if kwargs.get("subsystem") == "iommu":
                return []
            if kwargs.get("subsystem") == "pci":
                return [
                    MagicMock(
                        properties={
                            "PCI_SLOT_NAME": "0000:01:00.0",
                            "PCI_ID": "1022:1234",
                            "DRIVER": "amdxdna",
                        }
                    )
                ]
            return []

        self.mock_pyudev.list_devices.side_effect = mock_list_devices

        result = self.validator.check_amd_xdna()
        self.assertFalse(result)
        self.assertTrue(any(isinstance(f, NpuIommu) for f in self.validator.failures))
        self.mock_db.record_prereq.assert_called_with(
            "NPU is not supported with IOMMU disabled", "❌"
        )

    @patch("amd_debug.prereq.amd_platform.os.path.exists")
    def test_check_amd_xdna_missing_driver(self, mock_exists):
        """Test check_amd_xdna when NPU is found but no driver is bound"""
        mock_exists.side_effect = lambda p: True if "amdxdna" in p else False

        def mock_list_devices(**kwargs):
            if kwargs.get("subsystem") == "iommu":
                return [MagicMock()]
            if kwargs.get("subsystem") == "pci":
                return [
                    MagicMock(
                        properties={
                            "PCI_SLOT_NAME": "0000:01:00.0",
                            "PCI_ID": "1022:1234",
                            "DRIVER": None,
                        }
                    )
                ]
            return []

        self.mock_pyudev.list_devices.side_effect = mock_list_devices

        result = self.validator.check_amd_xdna()
        self.assertTrue(result)
        self.assertTrue(
            any(isinstance(f, MissingDriver) for f in self.validator.failures)
        )
        self.mock_db.record_prereq.assert_called_with(
            "NPU device in 0000:01:00.0 didn't bind a driver", "🚦"
        )

    @patch("amd_debug.prereq.amd_platform.read_file")
    @patch("amd_debug.prereq.amd_platform.os.path.exists")
    def test_check_amd_xdna_success(self, mock_exists, mock_read_file):
        """Test check_amd_xdna when driver is loaded, NPU is bound, and IOMMU is enabled"""
        mock_exists.side_effect = lambda p: True
        mock_read_file.return_value = "1.0.0"

        def mock_list_devices(**kwargs):
            if kwargs.get("subsystem") == "iommu":
                return [MagicMock()]
            if kwargs.get("subsystem") == "pci":
                return [
                    MagicMock(
                        sys_path="/sys/devices/pci",
                        properties={
                            "PCI_SLOT_NAME": "0000:01:00.0",
                            "PCI_ID": "1022:1234",
                            "DRIVER": "amdxdna",
                        },
                    )
                ]
            return []

        self.mock_pyudev.list_devices.side_effect = mock_list_devices

        result = self.validator.check_amd_xdna()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_called_with(
            "NPU loaded with firmware 1.0.0", "✅"
        )

    @patch("amd_debug.prereq.amd_platform.os.path.exists")
    def test_check_amd_xdna_non_amd(self, mock_exists):
        """Test check_amd_xdna when the NPU is not an AMD device"""
        mock_exists.side_effect = lambda p: True if "amdxdna" in p else False

        def mock_list_devices(**kwargs):
            if kwargs.get("subsystem") == "iommu":
                return [MagicMock()]
            if kwargs.get("subsystem") == "pci":
                return [
                    MagicMock(
                        properties={
                            "PCI_SLOT_NAME": "0000:01:00.0",
                            "PCI_ID": "8086:abcd",
                            "DRIVER": "amdxdna",
                        }
                    )
                ]
            return []

        self.mock_pyudev.list_devices.side_effect = mock_list_devices

        result = self.validator.check_amd_xdna()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_not_called()

    def test_check_amd_pmc_no_driver(self):
        """Test check_amd_pmc with no driver"""
        self.mock_pyudev.list_devices.return_value = []
        result = self.validator.check_amd_pmc()
        self.assertFalse(result)
        self.assertTrue(
            any(isinstance(f, MissingAmdPmc) for f in self.validator.failures)
        )

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

    @patch("amd_debug.prereq.amd_platform.version.parse")
    def test_check_port_pm_override_smu_version_too_high(self, mock_version_parse):
        """Test check_port_pm_override with SMU version > 76.60.0"""
        self.validator.cpu_family = 0x19
        self.validator.cpu_model = 0x74
        mock_version_parse.side_effect = lambda v: v if isinstance(v, str) else None
        self.validator.smu_version = "76.61.0"
        result = self.validator.check_port_pm_override()
        self.assertTrue(result)

    @patch("amd_debug.prereq.amd_platform.version.parse")
    def test_check_port_pm_override_smu_version_missing(self, mock_version_parse):
        """Test check_port_pm_override with SMU version undefined"""
        self.validator.cpu_family = 0x19
        self.validator.cpu_model = 0x74
        mock_version_parse.side_effect = lambda v: v if isinstance(v, str) else None
        self.validator.smu_version = ""
        result = self.validator.check_port_pm_override()
        self.assertTrue(result)

    @patch("amd_debug.prereq.amd_platform.version.parse")
    def test_check_port_pm_override_smu_version_too_low(self, mock_version_parse):
        """Test check_port_pm_override with SMU version < 76.18.0"""
        self.validator.cpu_family = 0x19
        self.validator.cpu_model = 0x74
        mock_version_parse.side_effect = lambda v: v if isinstance(v, str) else None
        self.validator.smu_version = "76.17.0"
        result = self.validator.check_port_pm_override()
        self.assertTrue(result)

    @patch("amd_debug.prereq.amd_platform.read_file", return_value="pcie_port_pm=off")
    def test_check_port_pm_override_cmdline_override(self, mock_read_file):
        """Test check_port_pm_override with pcie_port_pm=off in cmdline"""
        self.validator.cpu_family = 0x19
        self.validator.cpu_model = 0x74
        self.validator.smu_version = "76.50.0"
        result = self.validator.check_port_pm_override()
        self.assertTrue(result)

    @patch("amd_debug.prereq.amd_platform.read_file", return_value="mocked_cmdline")
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
        "amd_debug.prereq.amd_platform.open",
        new_callable=unittest.mock.mock_open,
        read_data=(
            b"\x00" * 40  # IVRS header with DMA protection cleared
            + b"bad_pattern"  # no MSFT0201
        ),
    )
    @patch("amd_debug.prereq.amd_platform.os.path.exists", return_value=True)
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

    def test_check_iommu_no_dma_protection_BUT_msft0201_single_device(self):
        """Test check_iommu when DMA protection disabled but MSFT0201 has IVMD (0x21)."""
        self.validator.cpu_family = 0x1A
        self.validator.cpu_model = 0x20
        from amd_debug.ivrs_fixtures import (
            make_ivrs_table,
            _pack_ivmd_single_device,
        )

        ivrs = make_ivrs_table(
            dma_remap=False,
            msft0201_devid=0x60,
            ivmd_entries=[_pack_ivmd_single_device(0x60, 0x100000)],
        )

        with patch(
            "amd_debug.prereq.amd_platform.open",
            new_callable=unittest.mock.mock_open,
            read_data=ivrs,
        ):
            with patch(
                "amd_debug.prereq.amd_platform.os.path.exists", return_value=True
            ):
                iommu_device = MagicMock(sys_path="/sys/devices/iommu")
                acpi_device = MagicMock(sys_path="/sys/devices/acpi/MSFT0201")
                platform_device = MagicMock(
                    sys_path="/sys/devices/platform/MSFT0201",
                    attributes={"iommu": MagicMock()},
                )
                self.mock_pyudev.list_devices.side_effect = [
                    [iommu_device],
                    [acpi_device],
                    [platform_device],
                ]
                result = self.validator.check_iommu()
                self.assertTrue(result)
                self.mock_db.record_prereq.assert_called_with(
                    "IOMMU properly configured", "✅"
                )

    def test_check_iommu_no_dma_protection_BUT_msft0201_all_devices(self):
        """Test check_iommu when DMA protection disabled but IVMD 0x20 covers all devices."""
        self.validator.cpu_family = 0x1A
        self.validator.cpu_model = 0x20
        from amd_debug.ivrs_fixtures import (
            make_ivrs_table,
            _pack_ivmd_all_devices,
        )

        ivrs = make_ivrs_table(
            dma_remap=False,
            msft0201_devid=0x60,
            ivmd_entries=[_pack_ivmd_all_devices(memory_length=0x100000)],
        )

        with patch(
            "amd_debug.prereq.amd_platform.open",
            new_callable=unittest.mock.mock_open,
            read_data=ivrs,
        ):
            with patch(
                "amd_debug.prereq.amd_platform.os.path.exists", return_value=True
            ):
                iommu_device = MagicMock(sys_path="/sys/devices/iommu")
                acpi_device = MagicMock(sys_path="/sys/devices/acpi/MSFT0201")
                platform_device = MagicMock(
                    sys_path="/sys/devices/platform/MSFT0201",
                    attributes={"iommu": MagicMock()},
                )
                self.mock_pyudev.list_devices.side_effect = [
                    [iommu_device],
                    [acpi_device],
                    [platform_device],
                ]
                result = self.validator.check_iommu()
                self.assertTrue(result)
                self.mock_db.record_prereq.assert_called_with(
                    "IOMMU properly configured", "✅"
                )

    def test_check_iommu_msft0201_no_ivmd_mapping(self):
        """Test check_iommu when MSFT0201 is in IVHD but has no IVMD mapping."""
        self.validator.cpu_family = 0x1A
        self.validator.cpu_model = 0x20
        from amd_debug.ivrs_fixtures import make_ivrs_table

        ivrs = make_ivrs_table(
            dma_remap=False,
            msft0201_devid=0x60,
            ivmd_entries=[],  # No IVMD entries
        )

        with patch(
            "amd_debug.prereq.amd_platform.open",
            new_callable=unittest.mock.mock_open,
            read_data=ivrs,
        ):
            with patch(
                "amd_debug.prereq.amd_platform.os.path.exists", return_value=True
            ):
                iommu_device = MagicMock(sys_path="/sys/devices/iommu")
                acpi_device = MagicMock(sys_path="/sys/devices/acpi/MSFT0201")
                platform_device = MagicMock(
                    sys_path="/sys/devices/platform/MSFT0201",
                    attributes={"iommu": MagicMock()},
                )
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
                    "IOMMU is misconfigured: MSFT0201 declared in IVRS but no DMA mapping",
                    "❌",
                )

    def test_check_iommu_msft0201_wrong_ivmd_device_id(self):
        """Test check_iommu when IVMD exists but device ID doesn't match MSFT0201."""
        self.validator.cpu_family = 0x1A
        self.validator.cpu_model = 0x20
        from amd_debug.ivrs_fixtures import (
            make_ivrs_table,
            _pack_ivmd_single_device,
        )

        # IVMD for device 0x70, but MSFT0201 is at 0x60
        ivrs = make_ivrs_table(
            dma_remap=False,
            msft0201_devid=0x60,
            ivmd_entries=[_pack_ivmd_single_device(0x70, 0x100000)],
        )

        with patch(
            "amd_debug.prereq.amd_platform.open",
            new_callable=unittest.mock.mock_open,
            read_data=ivrs,
        ):
            with patch(
                "amd_debug.prereq.amd_platform.os.path.exists", return_value=True
            ):
                iommu_device = MagicMock(sys_path="/sys/devices/iommu")
                acpi_device = MagicMock(sys_path="/sys/devices/acpi/MSFT0201")
                platform_device = MagicMock(
                    sys_path="/sys/devices/platform/MSFT0201",
                    attributes={"iommu": MagicMock()},
                )
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
                    "IOMMU is misconfigured: MSFT0201 declared in IVRS but no DMA mapping",
                    "❌",
                )

    def test_check_iommu_msft0201_in_ivmd_exclusion_range(self):
        """Test check_iommu when MSFT0201 is covered by IVMD 0x22 range."""
        self.validator.cpu_family = 0x1A
        self.validator.cpu_model = 0x20
        from amd_debug.ivrs_fixtures import (
            make_ivrs_table,
            _pack_ivmd_exclusion_range,
        )

        ivrs = make_ivrs_table(
            dma_remap=False,
            msft0201_devid=0x60,
            ivmd_entries=[
                _pack_ivmd_exclusion_range(
                    device_id=0x50, end_device_id=0x70, memory_length=0x100000
                )
            ],
        )

        with patch(
            "amd_debug.prereq.amd_platform.open",
            new_callable=unittest.mock.mock_open,
            read_data=ivrs,
        ):
            with patch(
                "amd_debug.prereq.amd_platform.os.path.exists", return_value=True
            ):
                iommu_device = MagicMock(sys_path="/sys/devices/iommu")
                acpi_device = MagicMock(sys_path="/sys/devices/acpi/MSFT0201")
                platform_device = MagicMock(
                    sys_path="/sys/devices/platform/MSFT0201",
                    attributes={"iommu": MagicMock()},
                )
                self.mock_pyudev.list_devices.side_effect = [
                    [iommu_device],
                    [acpi_device],
                    [platform_device],
                ]
                result = self.validator.check_iommu()
                self.assertTrue(result)
                self.mock_db.record_prereq.assert_called_with(
                    "IOMMU properly configured", "✅"
                )

    def test_check_iommu_no_dma_protection_type11_msft0201_single_device(self):
        """Test check_iommu for an IVHD type 11h table with valid IVMD mapping."""
        self.validator.cpu_family = 0x1A
        self.validator.cpu_model = 0x20
        from amd_debug.ivrs_fixtures import (
            make_ivrs_table,
            _pack_ivmd_single_device,
        )

        ivrs = make_ivrs_table(
            dma_remap=False,
            msft0201_devid=0x60,
            ivmd_entries=[_pack_ivmd_single_device(0x60, 0x100000)],
            ivhd_type=0x11,
        )

        with patch(
            "amd_debug.prereq.amd_platform.open",
            new_callable=unittest.mock.mock_open,
            read_data=ivrs,
        ):
            with patch(
                "amd_debug.prereq.amd_platform.os.path.exists", return_value=True
            ):
                iommu_device = MagicMock(sys_path="/sys/devices/iommu")
                acpi_device = MagicMock(sys_path="/sys/devices/acpi/MSFT0201")
                platform_device = MagicMock(
                    sys_path="/sys/devices/platform/MSFT0201",
                    attributes={"iommu": MagicMock()},
                )
                self.mock_pyudev.list_devices.side_effect = [
                    [iommu_device],
                    [acpi_device],
                    [platform_device],
                ]
                result = self.validator.check_iommu()
                self.assertTrue(result)
                self.mock_db.record_prereq.assert_called_with(
                    "IOMMU properly configured", "✅"
                )

    @patch(
        "amd_debug.prereq.amd_platform.open",
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
        "amd_debug.prereq.amd_platform.open",
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
        "amd_debug.prereq.amd_platform.open",
        new_callable=unittest.mock.mock_open,
        read_data=b"\x00" * 36 + b"\xff" * 4,
    )
    @patch("amd_debug.prereq.amd_platform.os.path.exists", return_value=True)
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

    @patch("amd_debug.prereq.amd_platform.read_file")
    @patch("amd_debug.prereq.amd_platform.os.path.exists", return_value=True)
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

    @patch("builtins.open", new_callable=mock_open)
    @patch("amd_debug.prereq.amd_platform.read_file")
    @patch("amd_debug.prereq.amd_platform.os.path.exists")
    def test_check_cpu_limited_cores_single_ccd(
        self, mock_path_exists, mock_read_file, mock_file_open
    ):
        """Test check_cpu with artificially limited CPUs on single-CCD system"""
        self.validator.cpu_family = 0x19
        self.validator.cpu_model = 0x74
        mock_read_file.return_value = "7"  # kernel_max = 7 (8 cores)
        mock_path_exists.return_value = True
        # Simulate finding socket level at subleaf 1
        # First call: subleaf 0, level_type = 1 (not socket)
        # Second call: subleaf 1, level_type = 4 (socket level)
        # Third call: read cpu_count from subleaf 1
        mock_file_open.return_value.read.side_effect = [
            struct.pack("4I", 0, 0, 0x100, 0),  # subleaf 0: level_type = 1 (thread)
            struct.pack(
                "4I", 0, 0, 0x400, 0
            ),  # subleaf 1: level_type = 4 (socket) - FOUND
            struct.pack("4I", 0, 16, 0, 0),  # subleaf 1: cpu_count = 16
        ]
        result = self.validator.check_cpu()
        self.assertFalse(result)
        self.assertTrue(
            any(isinstance(f, LimitedCores) for f in self.validator.failures)
        )
        self.mock_db.record_prereq.assert_called_with(
            "The kernel has been limited to 8 CPU cores, but the system has 16 cores",
            "❌",
        )

    @patch("builtins.open", new_callable=mock_open)
    @patch("amd_debug.prereq.amd_platform.read_file")
    @patch("amd_debug.prereq.amd_platform.os.path.exists")
    def test_check_cpu_limited_cores_multi_ccd(
        self, mock_path_exists, mock_read_file, mock_file_open
    ):
        """Test check_cpu with multi-CCD system (tests socket-level counting)"""
        self.validator.cpu_family = 0x19
        self.validator.cpu_model = 0x74
        mock_read_file.return_value = "15"  # kernel_max = 15 (16 cores)
        mock_path_exists.return_value = True
        # Simulate multi-CCD: iterate through levels to find socket
        # subleaf 0: level_type = 1 (thread)
        # subleaf 1: level_type = 2 (core)
        # subleaf 2: level_type = 3 (complex/CCD)
        # subleaf 3: level_type = 4 (socket) - FOUND
        mock_file_open.return_value.read.side_effect = [
            struct.pack("4I", 0, 0, 0x100, 0),  # subleaf 0: level_type = 1 (thread)
            struct.pack("4I", 0, 0, 0x200, 0),  # subleaf 1: level_type = 2 (core)
            struct.pack(
                "4I", 0, 0, 0x300, 0
            ),  # subleaf 2: level_type = 3 (complex/CCD)
            struct.pack(
                "4I", 0, 0, 0x400, 0
            ),  # subleaf 3: level_type = 4 (socket) - FOUND
            struct.pack("4I", 0, 32, 0, 0),  # subleaf 3: cpu_count = 32
        ]
        result = self.validator.check_cpu()
        self.assertFalse(result)
        self.assertTrue(
            any(isinstance(f, LimitedCores) for f in self.validator.failures)
        )
        self.mock_db.record_prereq.assert_called_with(
            "The kernel has been limited to 16 CPU cores, but the system has 32 cores",
            "❌",
        )

    @patch("builtins.open", new_callable=mock_open)
    @patch("amd_debug.prereq.amd_platform.read_file")
    @patch("amd_debug.prereq.amd_platform.os.path.exists")
    def test_check_cpu_not_limited(
        self, mock_path_exists, mock_read_file, mock_file_open
    ):
        """Test check_cpu when CPUs are not artificially limited"""
        self.validator.cpu_family = 0x19
        self.validator.cpu_model = 0x74
        mock_read_file.return_value = "31"  # kernel_max = 31 (32 cores)
        mock_path_exists.return_value = True
        # Simulate finding socket level
        mock_file_open.return_value.read.side_effect = [
            struct.pack("4I", 0, 0, 0x100, 0),  # subleaf 0: level_type = 1
            struct.pack("4I", 0, 0, 0x400, 0),  # subleaf 1: level_type = 4 (socket)
            struct.pack("4I", 0, 16, 0, 0),  # subleaf 1: cpu_count = 16
        ]
        result = self.validator.check_cpu()
        self.assertTrue(result)
        self.mock_db.record_debug.assert_called_with("CPU core count: 16 max: 32")

    @patch("builtins.open", new_callable=mock_open)
    @patch("amd_debug.prereq.amd_platform.read_file")
    @patch("amd_debug.prereq.amd_platform.os.path.exists")
    def test_check_cpu_socket_level_at_boundary(
        self, mock_path_exists, mock_read_file, mock_file_open
    ):
        """Test check_cpu when socket level is found at the last checked subleaf"""
        self.validator.cpu_family = 0x19
        self.validator.cpu_model = 0x74
        mock_read_file.return_value = "15"  # kernel_max = 15 (16 cores)
        mock_path_exists.return_value = True
        # Socket level found at subleaf 4 (last iteration)
        mock_file_open.return_value.read.side_effect = [
            struct.pack("4I", 0, 0, 0x100, 0),  # subleaf 0: level_type = 1
            struct.pack("4I", 0, 0, 0x200, 0),  # subleaf 1: level_type = 2
            struct.pack("4I", 0, 0, 0x300, 0),  # subleaf 2: level_type = 3
            struct.pack("4I", 0, 0, 0x000, 0),  # subleaf 3: level_type = 0
            struct.pack("4I", 0, 0, 0x400, 0),  # subleaf 4: level_type = 4 (socket)
            struct.pack("4I", 0, 16, 0, 0),  # subleaf 4: cpu_count = 16
        ]
        result = self.validator.check_cpu()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_called_with(
            "Unable to discover CPU topology, didn't find socket level", "🚦"
        )

    @patch("builtins.open", new_callable=mock_open)
    @patch("amd_debug.prereq.amd_platform.read_file")
    @patch("amd_debug.prereq.amd_platform.os.path.exists")
    def test_check_cpu_socket_level_first_subleaf(
        self, mock_path_exists, mock_read_file, mock_file_open
    ):
        """Test check_cpu when socket level is found at first subleaf"""
        self.validator.cpu_family = 0x19
        self.validator.cpu_model = 0x74
        mock_read_file.return_value = "7"  # kernel_max = 7 (8 cores)
        mock_path_exists.return_value = True
        # Socket level found immediately at subleaf 0
        mock_file_open.return_value.read.side_effect = [
            struct.pack(
                "4I", 0, 0, 0x400, 0
            ),  # subleaf 0: level_type = 4 (socket) - FOUND
            struct.pack("4I", 0, 8, 0, 0),  # subleaf 0: cpu_count = 8
        ]
        result = self.validator.check_cpu()
        self.assertTrue(result)
        self.mock_db.record_debug.assert_called_with("CPU core count: 8 max: 8")

    @patch("builtins.open", side_effect=FileNotFoundError)
    @patch("amd_debug.prereq.amd_platform.read_file")
    @patch("amd_debug.prereq.amd_platform.os.path.exists")
    def test_check_cpu_cpuid_file_not_found(
        self, mock_path_exists, mock_read_file, mock_file_open
    ):
        """Test check_cpu when cpuid kernel module is not loaded"""
        self.validator.cpu_family = 0x19
        self.validator.cpu_model = 0x74
        mock_read_file.return_value = "7"
        mock_path_exists.return_value = False
        result = self.validator.check_cpu()
        self.assertFalse(result)
        self.mock_db.record_prereq.assert_called_with(
            "Unable to check CPU topology: cpuid kernel module not loaded", "❌"
        )

    @patch("amd_debug.prereq.amd_platform.subprocess.run")
    @patch("builtins.open", new_callable=mock_open)
    @patch("amd_debug.prereq.amd_platform.read_file")
    @patch("amd_debug.prereq.amd_platform.os.path.exists")
    def test_check_cpu_loads_cpuid_module(
        self, mock_path_exists, mock_read_file, mock_file_open, mock_run
    ):
        """Test read_cpuid loads the cpuid module via an absolute path and no shell"""
        self.validator.cpu_family = 0x19
        self.validator.cpu_model = 0x74
        mock_read_file.return_value = "31"  # kernel_max = 31 (32 cores)
        # cpuid device node missing so the module load path is exercised
        mock_path_exists.return_value = False
        mock_file_open.return_value.read.side_effect = [
            struct.pack("4I", 0, 0, 0x100, 0),  # subleaf 0: level_type = 1
            struct.pack("4I", 0, 0, 0x400, 0),  # subleaf 1: level_type = 4 (socket)
            struct.pack("4I", 0, 16, 0, 0),  # subleaf 1: cpu_count = 16
        ]
        result = self.validator.check_cpu()
        self.assertTrue(result)
        mock_run.assert_any_call(["/sbin/modprobe", "cpuid"], check=False)
        # ensure the module load never went through a shell
        for _, kwargs in mock_run.call_args_list:
            self.assertNotIn("shell", kwargs)

    @patch("builtins.open", side_effect=PermissionError)
    @patch("amd_debug.prereq.amd_platform.read_file")
    @patch("amd_debug.prereq.amd_platform.os.path.exists")
    def test_check_cpu_cpuid_permission_error(
        self, mock_path_exists, mock_read_file, mock_file_open
    ):
        """Test check_cpu when there is a permission error accessing cpuid"""
        self.validator.cpu_family = 0x19
        self.validator.cpu_model = 0x74
        mock_read_file.return_value = "7"
        mock_path_exists.return_value = True
        result = self.validator.check_cpu()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_called_with("CPUID checks unavailable", "🚦")

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

    @patch("amd_debug.prereq.amd_gpu.os.path.exists")
    @patch(
        "amd_debug.prereq.amd_gpu.open",
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

    @patch("amd_debug.prereq.amd_gpu.os.path.exists")
    @patch(
        "amd_debug.prereq.amd_gpu.open",
        new_callable=unittest.mock.mock_open,
        read_data="(null)",
    )
    def test_capture_disabled_pins_with_null_values(self, _mock_open, mock_path_exists):
        mock_path_exists.side_effect = (
            lambda path: "ignore_wake" in path or "ignore_interrupt" in path
        )
        self.validator.capture_disabled_pins()
        self.mock_db.record_debug.assert_not_called()

    @patch("amd_debug.prereq.amd_gpu.os.path.exists", return_value=False)
    def test_capture_disabled_pins_no_parameters(self, _mock_path_exists):
        """Test capture_disabled_pins when parameters are not present"""
        self.validator.capture_disabled_pins()
        self.mock_db.record_debug.assert_not_called()

    @patch("amd_debug.prereq.amd_gpu.read_file")
    @patch("amd_debug.prereq.amd_gpu.os.path.exists", return_value=True)
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

    @patch("amd_debug.prereq.amd_gpu.read_file")
    @patch("amd_debug.prereq.amd_gpu.os.path.exists", return_value=True)
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

    @patch("amd_debug.prereq.amd_gpu.read_file")
    @patch("amd_debug.prereq.amd_gpu.os.path.exists", return_value=True)
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

    @patch("amd_debug.prereq.amd_gpu.read_file")
    @patch("amd_debug.prereq.amd_gpu.os.path.exists", return_value=True)
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

    @patch("amd_debug.prereq.amd_gpu.os.path.exists")
    @patch("amd_debug.prereq.amd_gpu.read_file")
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

    @patch("amd_debug.prereq.amd_gpu.os.path.exists")
    @patch("amd_debug.prereq.amd_gpu.read_file")
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

    @patch("amd_debug.prereq.amd_gpu.os.path.exists")
    @patch("amd_debug.prereq.amd_gpu.read_file")
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

    @patch("amd_debug.prereq.amd_gpu.os.path.exists")
    @patch("amd_debug.prereq.amd_gpu.read_file")
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

    @patch("amd_debug.prereq.amd_gpu.os.path.exists")
    @patch("amd_debug.prereq.amd_gpu.read_file")
    def test_check_asus_rog_ally_no_devices(self, _mock_read_file, mock_path_exists):
        """Test check_asus_rog_ally when no devices are found"""
        mock_path_exists.return_value = False
        self.mock_pyudev.list_devices.side_effect = [[], []]

        result = self.validator.check_asus_rog_ally()
        self.assertTrue(result)

    @patch("amd_debug.prereq.amd_platform.version.parse")
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

    @patch("amd_debug.prereq.amd_platform.version.parse")
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

    @patch("amd_debug.prereq.amd_platform.version.parse")
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

    @patch("amd_debug.prereq.amd_platform.version.parse")
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

    @patch("amd_debug.prereq.amd_gpu.os.path.exists")
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

    @patch("amd_debug.prereq.amd_gpu.os.path.exists")
    def test_capture_linux_firmware_debug_files_missing(self, mock_path_exists):
        """Test capture_linux_firmware when debug files are missing"""
        mock_path_exists.return_value = False

        self.validator.distro = "ubuntu"
        self.validator.capture_linux_firmware()

        self.mock_db.record_debug_file.assert_not_called()

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
        with patch(
            "amd_debug.prereq.amd_platform.os.path.exists", return_value=True
        ), patch(
            "amd_debug.prereq.amd_platform.read_file",
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
        with patch(
            "amd_debug.prereq.amd_platform.os.path.exists", return_value=True
        ), patch("amd_debug.prereq.amd_platform.read_file", side_effect=TimeoutError):
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
        with patch("amd_debug.prereq.amd_platform.os.path.exists", return_value=False):
            result = self.validator.check_amd_pmc()
            self.assertTrue(result)
            self.mock_db.record_prereq.assert_called_with(
                "PMC driver `amd_pmc` loaded", "✅"
            )

    @patch("amd_debug.prereq.amd_storage.minimum_kernel", return_value=True)
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

    @patch("amd_debug.prereq.amd_gpu.find_ip_version", return_value=True)
    @patch("amd_debug.prereq.amd_gpu.os.path.exists")
    @patch("amd_debug.prereq.amd_gpu.read_file")
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

    @patch("amd_debug.prereq.amd_gpu.find_ip_version", return_value=True)
    @patch("amd_debug.prereq.amd_gpu.os.path.exists", return_value=True)
    @patch("amd_debug.prereq.amd_gpu.read_file", return_value="0x90001B01")
    @patch("amd_debug.prereq.amd_platform.version.parse")
    def test_check_dpia_pg_dmcub_dmcub_fw_version_new_enough(
        self, mock_version_parse, mock_read_file, mock_path_exists, mock_find_ip_version
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

    @patch("amd_debug.prereq.amd_gpu.find_ip_version", return_value=True)
    @patch("amd_debug.prereq.amd_gpu.os.path.exists", return_value=True)
    @patch("amd_debug.prereq.amd_gpu.read_file", return_value="0x8001B00")
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

    @patch("amd_debug.prereq.amd_gpu.find_ip_version", return_value=True)
    @patch("amd_debug.prereq.amd_gpu.os.path.exists", return_value=False)
    @patch(
        "amd_debug.prereq.amd_gpu.read_file",
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

    @patch("amd_debug.prereq.amd_gpu.find_ip_version", return_value=True)
    @patch("amd_debug.prereq.amd_gpu.os.path.exists", return_value=False)
    @patch(
        "amd_debug.prereq.amd_gpu.read_file",
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

    @patch("amd_debug.prereq.amd_gpu.find_ip_version", return_value=False)
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

    @patch("amd_debug.prereq.amd_gpu.read_file")
    def test_check_pinctrl_amd_driver_loaded_with_missing_file_error(
        self, mock_read_file
    ):
        """Test check_pinctrl_amd when the driver is loaded but debug file is missing"""
        mock_read_file.side_effect = FileNotFoundError
        self.mock_pyudev.list_devices.return_value = [
            MagicMock(properties={"DRIVER": "amd_gpio"})
        ]

        result = self.validator.check_pinctrl_amd()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_called_with(
            "GPIO debugfs not available", "👀"
        )

    def test_check_amdgpu_no_devices(self):
        """Test check_amdgpu when no PCI devices are found"""
        self.mock_pyudev.list_devices.return_value = []
        result = self.validator.check_amdgpu()
        self.assertFalse(result)
        self.mock_db.record_prereq.assert_called_with("Integrated GPU not found", "❌")
        self.assertTrue(any(isinstance(f, MissingGpu) for f in self.validator.failures))

    def test_check_amdgpu_non_amd_devices(self):
        """Test check_amdgpu when PCI devices are present but not AMD GPUs"""
        self.mock_pyudev.list_devices.return_value = [
            MagicMock(
                properties={
                    "PCI_CLASS": "30000",
                    "PCI_ID": "8086abcd",
                    "DRIVER": "i915",
                }
            ),
        ]
        result = self.validator.check_amdgpu()
        self.assertFalse(result)
        self.mock_db.record_prereq.assert_called_with("Integrated GPU not found", "❌")
        self.assertTrue(any(isinstance(f, MissingGpu) for f in self.validator.failures))

    def test_check_amdgpu_driver_not_loaded(self):
        """Test check_amdgpu when AMD GPU is present but driver is not loaded"""
        self.mock_pyudev.list_devices.return_value = [
            MagicMock(
                properties={"PCI_CLASS": "20000", "PCI_ID": "1111abcd", "DRIVER": None}
            ),
            MagicMock(
                properties={"PCI_CLASS": "30000", "PCI_ID": "1002abcd", "DRIVER": None}
            ),
        ]
        result = self.validator.check_amdgpu()
        self.assertFalse(result)
        self.mock_db.record_prereq.assert_called_with(
            "GPU driver `amdgpu` not loaded", "❌"
        )
        self.assertTrue(
            any(isinstance(f, MissingAmdgpu) for f in self.validator.failures)
        )

    def test_check_amdgpu_driver_loaded(self):
        """Test check_amdgpu when AMD GPU is present and driver is loaded"""
        self.mock_pyudev.list_devices.return_value = [
            MagicMock(
                properties={
                    "PCI_CLASS": "30000",
                    "PCI_ID": "1002abcd",
                    "DRIVER": "amdgpu",
                    "PCI_SLOT_NAME": "0000:01:00.0",
                }
            ),
        ]
        result = self.validator.check_amdgpu()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_called_with(
            "GPU driver `amdgpu` bound to 0000:01:00.0", "✅"
        )

    def test_check_amdgpu_multiple_devices_mixed(self):
        """Test check_amdgpu with multiple devices, one with driver loaded, one without"""
        self.mock_pyudev.list_devices.return_value = [
            MagicMock(
                properties={
                    "PCI_CLASS": "30000",
                    "PCI_ID": "1002abcd",
                    "DRIVER": "amdgpu",
                    "PCI_SLOT_NAME": "0000:01:00.0",
                }
            ),
            MagicMock(
                properties={"PCI_CLASS": "30000", "PCI_ID": "1002abcd", "DRIVER": None}
            ),
        ]
        result = self.validator.check_amdgpu()
        self.assertFalse(result)
        self.mock_db.record_prereq.assert_any_call(
            "GPU driver `amdgpu` bound to 0000:01:00.0", "✅"
        )
        self.mock_db.record_prereq.assert_any_call(
            "GPU driver `amdgpu` not loaded", "❌"
        )
        self.assertTrue(
            any(isinstance(f, MissingAmdgpu) for f in self.validator.failures)
        )

    @patch("amd_debug.prereq.amd_gpu.os.path.exists")
    @patch("amd_debug.prereq.amd_gpu.os.readlink")
    def test_check_isp4_no_devices(self, _mock_readlink, _mock_path_exists):
        """Test check_isp4 when no ISP4 camera devices are found"""
        self.mock_pyudev.list_devices.return_value = []
        result = self.validator.check_isp4()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_not_called()

    @patch("amd_debug.prereq.amd_gpu.os.path.exists")
    @patch("amd_debug.prereq.amd_gpu.os.readlink")
    def test_check_isp4_device_without_path(self, _mock_readlink, mock_path_exists):
        """Test check_isp4 when ACPI device exists but path file is missing"""
        mock_path_exists.return_value = False
        self.mock_pyudev.list_devices.return_value = [
            MagicMock(sys_path="/sys/devices/acpi/OMNI5C10:00", sys_name="OMNI5C10:00")
        ]
        result = self.validator.check_isp4()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_not_called()

    @patch("amd_debug.prereq.amd_gpu.os.path.exists")
    @patch("amd_debug.prereq.amd_gpu.os.readlink")
    def test_check_isp4_driver_not_bound(self, _mock_readlink, mock_path_exists):
        """Test check_isp4 when ISP4 driver is not bound to the device"""
        mock_path_exists.side_effect = lambda p: "path" in p
        self.mock_pyudev.list_devices.return_value = [
            MagicMock(sys_path="/sys/devices/acpi/OMNI5C10:00", sys_name="OMNI5C10:00")
        ]
        result = self.validator.check_isp4()
        self.assertFalse(result)
        self.mock_db.record_prereq.assert_called_with(
            "ISP4 platform camera driver 'amd-isp4' not bound to OMNI5C10:00", "❌"
        )
        self.assertTrue(
            any(
                isinstance(f, MissingIsp4PlatformDriver)
                for f in self.validator.failures
            )
        )

    @patch("amd_debug.prereq.amd_gpu.os.path.exists")
    @patch(
        "amd_debug.prereq.amd_gpu.os.readlink",
        return_value="/sys/devices/platform/drivers/amd-isp4",
    )
    def test_check_isp4_driver_bound_but_module_not_loaded(
        self, _mock_readlink, mock_path_exists
    ):
        """Test check_isp4 when driver is bound but amd_capture or amd_isp4_capture modules are not loaded"""

        def exists_side_effect(path):
            if "path" in path or "driver" in path:
                return True
            if "amd_capture" in path or "amd_isp4_capture" in path:
                return False
            return True

        mock_path_exists.side_effect = exists_side_effect
        self.mock_pyudev.list_devices.return_value = [
            MagicMock(sys_path="/sys/devices/acpi/OMNI5C10:00", sys_name="OMNI5C10:00")
        ]
        result = self.validator.check_isp4()
        self.assertFalse(result)
        self.mock_db.record_prereq.assert_any_call(
            "ISP4 platform camera driver 'amd-isp4' bound to OMNI5C10:00", "✅"
        )
        self.mock_db.record_prereq.assert_any_call(
            "Camera driver module 'amd_capture'/'amd_isp4_capture' not loaded", "❌"
        )
        self.assertTrue(
            any(isinstance(f, MissingAmdCaptureModule) for f in self.validator.failures)
        )

    @patch("amd_debug.prereq.amd_gpu.os.path.exists")
    @patch(
        "amd_debug.prereq.amd_gpu.os.readlink",
        return_value="/sys/devices/platform/drivers/amd-isp4",
    )
    def test_check_isp4_fully_configured(self, _mock_readlink, mock_path_exists):
        """Test check_isp4 when ISP4 is fully configured with driver and module"""
        mock_path_exists.return_value = True
        self.mock_pyudev.list_devices.return_value = [
            MagicMock(sys_path="/sys/devices/acpi/OMNI5C10:00", sys_name="OMNI5C10:00")
        ]
        result = self.validator.check_isp4()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_any_call(
            "ISP4 platform camera driver 'amd-isp4' bound to OMNI5C10:00", "✅"
        )
        self.mock_db.record_prereq.assert_any_call(
            "Camera driver module 'amd_capture'/'amd_isp4_capture' loaded", "✅"
        )

    @patch("amd_debug.prereq.amd_gpu.os.path.exists")
    @patch(
        "amd_debug.prereq.amd_gpu.os.readlink",
        return_value="/sys/devices/platform/drivers/other-driver",
    )
    def test_check_isp4_wrong_driver(self, _mock_readlink, mock_path_exists):
        """Test check_isp4 when wrong driver is bound to the device"""
        mock_path_exists.side_effect = lambda p: "path" in p or "driver" in p
        self.mock_pyudev.list_devices.return_value = [
            MagicMock(sys_path="/sys/devices/acpi/OMNI5C10:00", sys_name="OMNI5C10:00")
        ]
        result = self.validator.check_isp4()
        self.assertFalse(result)
        self.mock_db.record_prereq.assert_called_with(
            "ISP4 platform camera driver 'amd-isp4' not bound to OMNI5C10:00", "❌"
        )
        self.assertTrue(
            any(
                isinstance(f, MissingIsp4PlatformDriver)
                for f in self.validator.failures
            )
        )

    @patch("amd_debug.prereq.amd_gpu.os.path.exists")
    @patch(
        "amd_debug.prereq.amd_gpu.os.readlink",
        return_value="/sys/devices/platform/drivers/amd-isp4",
    )
    def test_check_isp4_multiple_devices(self, _mock_readlink, mock_path_exists):
        """Test check_isp4 with multiple ISP4 camera devices"""
        mock_path_exists.return_value = True
        self.mock_pyudev.list_devices.return_value = [
            MagicMock(sys_path="/sys/devices/acpi/OMNI5C10:00", sys_name="OMNI5C10:00"),
            MagicMock(sys_path="/sys/devices/acpi/OMNI5C10:01", sys_name="OMNI5C10:01"),
        ]
        result = self.validator.check_isp4()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_any_call(
            "ISP4 platform camera driver 'amd-isp4' bound to OMNI5C10:00", "✅"
        )
        self.mock_db.record_prereq.assert_any_call(
            "ISP4 platform camera driver 'amd-isp4' bound to OMNI5C10:01", "✅"
        )

    @patch("amd_debug.prereq.amd_gpu.os.path.exists")
    def test_check_isp4_device_not_starting_with_omni5c10(self, mock_path_exists):
        """Test check_isp4 when ACPI devices don't match OMNI5C10 pattern"""
        mock_path_exists.return_value = True
        self.mock_pyudev.list_devices.return_value = [
            MagicMock(sys_path="/sys/devices/acpi/OTHER:00", sys_name="OTHER:00")
        ]
        result = self.validator.check_isp4()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_not_called()


if __name__ == "__main__":
    unittest.main()

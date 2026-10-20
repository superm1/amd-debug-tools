# SPDX-License-Identifier: MIT

"""
This module contains the AMD specific prerequisites for s2idle.
"""

from amd_debug.prereq.base import PrerequisiteValidator
from amd_debug.prereq.amd_gpu import AmdGpuChecks
from amd_debug.prereq.amd_storage import AmdStorageChecks
from amd_debug.prereq.amd_platform import AmdPlatformChecks


class AmdPrerequisiteValidator(
    AmdGpuChecks, AmdStorageChecks, AmdPlatformChecks, PrerequisiteValidator
):
    """Class to validate the prerequisites for s2idle on AMD platforms"""

    def vendor_info(self) -> list:
        """Return the list of vendor specific information to capture"""
        return [
            self.capture_disabled_pins,
            self.capture_linux_firmware,
        ]

    def vendor_checks(self) -> list:
        """Return the list of vendor specific checks to run"""
        return [
            self.check_aspm,
            self.check_i2c_hid,
            self.check_pinctrl_amd,
            self.check_amd_hsmp,
            self.check_amd_xdna,
            self.check_amd_pmc,
            self.check_amd_cpu_hpet_wa,
            self.check_port_pm_override,
            self.check_pcie_hotplug,
            self.check_usb3,
            self.check_usb4,
            self.check_sleep_mode,
            self.check_storage,
            self.check_wcn6855_bug,
            self.check_amdgpu,
            self.check_amdgpu_parameters,
            self.check_cpu,
            self.check_smt,
            self.check_iommu,
            self.check_asus_rog_ally,
            self.check_dpia_pg_dmcub,
            self.check_isp4,
        ]

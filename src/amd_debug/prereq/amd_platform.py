# SPDX-License-Identifier: MIT

"""
This module contains the AMD SoC and CPU specific checks for the s2idle
prerequisite validator.
"""

import os
import platform
import struct
import subprocess

from packaging import version

from amd_debug.common import minimum_kernel, read_file
from amd_debug.failures import (
    AmdHsmpBug,
    DMArNotEnabled,
    LimitedCores,
    MissingAmdPmc,
    MissingDriver,
    MissingIommuACPI,
    MissingIommuPolicy,
    NpuIommu,
    UnsupportedModel,
)


class AmdPlatformChecks:
    """Mixin providing the AMD SoC and CPU related prerequisite checks"""

    def check_amd_hsmp(self):
        """Check for AMD HSMP driver"""
        # not needed to check in newer kernels
        # see https://github.com/torvalds/linux/commit/77f1972bdcf7513293e8bbe376b9fe837310ee9c
        if minimum_kernel(6, 10):
            return True
        f = os.path.join("/", "boot", f"config-{platform.uname().release}")
        if os.path.exists(f):
            kconfig = read_file(f)
            if "CONFIG_AMD_HSMP=y" in kconfig:
                self.db.record_prereq(
                    "HSMP driver `amd_hsmp` driver may conflict with amd_pmc",
                    "❌",
                )
                self.failures += [AmdHsmpBug()]
                return False

        cmdline = read_file(os.path.join("/proc", "cmdline"))
        blocked = "initcall_blacklist=hsmp_plt_init" in cmdline

        p = os.path.join("/", "sys", "module", "amd_hsmp")
        if os.path.exists(p) and not blocked:
            self.db.record_prereq("`amd_hsmp` driver may conflict with amd_pmc", "❌")
            self.failures += [AmdHsmpBug()]
            return False

        self.db.record_prereq(
            f"HSMP driver `amd_hsmp` not detected (blocked: {blocked})",
            "✅",
        )
        return True

    def check_amd_pmc(self):
        """Check if the amd_pmc driver is loaded"""
        for device in self.pyudev.list_devices(subsystem="platform", DRIVER="amd_pmc"):
            message = "PMC driver `amd_pmc` loaded"
            p = os.path.join(device.sys_path, "smu_program")
            v = os.path.join(device.sys_path, "smu_fw_version")
            if os.path.exists(v):
                try:
                    self.smu_version = read_file(v)
                    self.smu_program = read_file(p)
                except TimeoutError:
                    self.db.record_prereq(
                        "failed to communicate using `amd_pmc` driver", "❌"
                    )
                    return False
                message += f" (Program {self.smu_program} Firmware {self.smu_version})"
            self.db.record_prereq(message, "✅")
            return True
        self.failures += [MissingAmdPmc()]
        self.db.record_prereq(
            "PMC driver `amd_pmc` did not bind to any ACPI device", "❌"
        )
        return False

    def check_amd_xdna(self):
        """Check for AMD XDNA driver"""
        amdxdna_path = os.path.join("/", "sys", "module", "amdxdna")
        driver_loaded = os.path.exists(amdxdna_path)
        # No driver loaded means HW should be power gated, should be OK.
        if not driver_loaded:
            return True

        # IOMMU disabled can cause problems with the NPU
        found_iommu = False
        for _dev in self.pyudev.list_devices(subsystem="iommu"):
            found_iommu = True
            break
        for device in self.pyudev.list_devices(subsystem="pci", PCI_CLASS="118000"):
            slot = device.properties["PCI_SLOT_NAME"]
            driver = device.properties.get("DRIVER")
            pci_id = device.properties.get("PCI_ID")
            if not pci_id.startswith("1022"):
                continue
            p = os.path.join(device.sys_path, "fw_version")
            if os.path.exists(p):
                xdna_fw_version = read_file(p)
                self.db.record_prereq(
                    f"NPU loaded with firmware {xdna_fw_version}", "✅"
                )
            if not found_iommu and driver:
                self.db.record_prereq("NPU is not supported with IOMMU disabled", "❌")
                self.failures += [NpuIommu()]
                return False
            if not driver:
                self.db.record_prereq(
                    f"NPU device in {slot} didn't bind a driver", "🚦"
                )
                self.failures += [MissingDriver(slot)]

        return True

    def check_amd_cpu_hpet_wa(self):
        """Check if the CPU offers the HPET workaround"""
        show_warning = False
        if self.cpu_family == 0x17:
            if self.cpu_model in [0x68, 0x60]:
                show_warning = True
        elif self.cpu_family == 0x19:
            if self.cpu_model == 0x50:
                if self.smu_version:
                    show_warning = version.parse(self.smu_version) < version.parse(
                        "64.53.0"
                    )
        if show_warning:
            self.db.record_prereq(
                "Timer based wakeup doesn't work properly for your "
                "ASIC/firmware, please manually wake the system",
                "🚦",
            )
        return True

    def check_port_pm_override(self):
        """Check for PCIe port power management override"""
        if self.cpu_family != 0x19:
            return True
        if self.cpu_model not in [0x74, 0x78]:
            return True
        if not self.smu_version:
            return True
        if version.parse(self.smu_version) > version.parse("76.60.0"):
            return True
        if version.parse(self.smu_version) < version.parse("76.18.0"):
            return True
        cmdline = read_file(os.path.join("/proc", "cmdline"))
        if "pcie_port_pm=off" in cmdline:
            return True
        self.db.record_prereq(
            "Platform may hang resuming.  "
            "Upgrade your firmware or add pcie_port_pm=off to kernel command "
            "line if you have problems.",
            "🚦",
        )
        return False

    def check_cpu(self):
        """Check if the CPU is supported"""

        def read_cpuid(cpu, leaf, subleaf):
            """Read CPUID using kernel userspace interface"""
            p = os.path.join("/", "dev", "cpu", f"{cpu}", "cpuid")
            if not os.path.exists(p):
                subprocess.run(["/sbin/modprobe", "cpuid"], check=False)
            with open(p, "rb") as f:
                position = (subleaf << 32) | leaf
                f.seek(position)
                data = f.read(16)
                return struct.unpack("4I", data)

        valid = True

        # check for supported models
        if self.cpu_family == 0x17:
            if self.cpu_model in range(0x30, 0x3F):
                valid = False
        if self.cpu_family == 0x19:
            if self.cpu_model in [0x08, 0x18]:
                valid = False

        if not valid:
            self.failures += [UnsupportedModel()]
            self.db.record_prereq(
                "This CPU model does not support hardware sleep over s2idle",
                "❌",
            )
            return False

        # check for artificially limited CPUs
        p = os.path.join("/", "sys", "devices", "system", "cpu", "kernel_max")
        max_cpus = int(read_file(p)) + 1  # 0 indexed
        # https://docs.amd.com/v/u/en-US/40332-PUB_4.08
        # E.4.24 Function 8000_0026—Extended CPU Topology
        try:
            # Need to discover the socket level to look at all CCDs in the socket
            for level in range(0, 5):
                _, _, ecx, _ = read_cpuid(0, 0x80000026, level)
                level_type = (ecx >> 8) & 0xFF
                if level_type == 0:
                    self.db.record_prereq(
                        "Unable to discover CPU topology, didn't find socket level",
                        "🚦",
                    )
                    return True
                if level_type == 4:
                    break
            _, cpu_count, _, _ = read_cpuid(0, 0x80000026, level)
            if cpu_count > max_cpus:
                self.db.record_prereq(
                    f"The kernel has been limited to {max_cpus} CPU cores, "
                    f"but the system has {cpu_count} cores",
                    "❌",
                )
                self.failures += [LimitedCores(cpu_count, max_cpus)]
                return False
            self.db.record_debug(f"CPU core count: {cpu_count} max: {max_cpus}")
        except FileNotFoundError:
            self.db.record_prereq(
                "Unable to check CPU topology: cpuid kernel module not loaded", "❌"
            )
            return False
        except PermissionError:
            self.db.record_prereq("CPUID checks unavailable", "🚦")

        return True

    def check_iommu(self):
        """Check IOMMU configuration"""
        affected_1a = (
            list(range(0x20, 0x2F)) + list(range(0x60, 0x6F)) + list(range(0x70, 0x7F))
        )
        debug_str = ""
        if self.cpu_family == 0x1A and self.cpu_model in affected_1a:
            found_iommu = False
            found_acpi = False
            for dev in self.pyudev.list_devices(subsystem="iommu"):
                found_iommu = True
                debug_str += f"Found IOMMU {dev.sys_path}\n"
                break

            # User turned off IOMMU, no problems
            if not found_iommu:
                self.db.record_prereq("IOMMU disabled", "✅")
                return True

            # Look for MSFT0201 in DSDT/SSDT
            for dev in self.pyudev.list_devices(subsystem="acpi"):
                if "MSFT0201" in dev.sys_path:
                    found_acpi = True
            if not found_acpi:
                self.db.record_prereq(
                    "IOMMU is misconfigured: missing MSFT0201 ACPI device", "❌"
                )
                self.failures += [MissingIommuACPI("MSFT0201")]
                return False

            # Check that policy is bound to it
            for dev in self.pyudev.list_devices(subsystem="platform"):
                if "MSFT0201" in dev.sys_path:
                    p = os.path.join(dev.sys_path, "iommu")
                    if not os.path.exists(p):
                        self.failures += [MissingIommuPolicy("MSFT0201")]
                        return False

            # Check pre-boot DMA
            p = os.path.join("/", "sys", "firmware", "acpi", "tables", "IVRS")
            with open(p, "rb") as f:
                data = f.read()
            if len(data) < 40:
                raise ValueError(
                    "IVRS table appears too small to contain virtualization info."
                )
            virt_info = struct.unpack_from("I", data, 36)[0]
            debug_str += f"IVRS: Virtualization info: 0x{virt_info:x}\n"
            found_ivrs_dmar = (virt_info & 0x2) != 0

            # check for MSFT0201 in IVRS (alternative to pre-boot DMA)
            target_bytes = "MSFT0201".encode("utf-8")
            found_ivrs_msft0201 = data.find(target_bytes) != -1
            debug_str += f"IVRS: Found MSFT0201: {found_ivrs_msft0201}"

            self.db.record_debug(debug_str)

            if found_ivrs_dmar:
                self.db.record_prereq("IOMMU properly configured", "✅")
                return True

            if not found_ivrs_msft0201:
                self.db.record_prereq(
                    "IOMMU is misconfigured: Pre-boot DMA protection not enabled", "❌"
                )
                self.failures += [DMArNotEnabled()]
                return False

            # DMA protection disabled but MSFT0201 in IVRS - verify it has a
            # valid memory mapping. Parse the IVRS table to find the device ID
            # for MSFT0201 and check for a covering IVMD entry.
            from amd_debug.ivrs import IvrsParser

            try:
                parser = IvrsParser(data)
            except ValueError as e:
                debug_str += f"IVRS: Failed to parse table: {e}\n"
                self.db.record_debug(debug_str)
                self.db.record_prereq(
                    "IOMMU is misconfigured: Unable to parse IVRS table", "❌"
                )
                self.failures += [DMArNotEnabled()]
                return False

            msft_devid = parser.find_msft0201_device_id()
            if msft_devid is None:
                debug_str += "IVRS: MSFT0201 not found in IVHD device entries\n"
                self.db.record_debug(debug_str)
                self.db.record_prereq(
                    "IOMMU is misconfigured: MSFT0201 not found in IVRS IVHD entries",
                    "❌",
                )
                self.failures += [DMArNotEnabled()]
                return False

            has_mapping = parser.has_valid_msft0201_mapping(msft_devid)
            debug_str += (
                f"IVRS: MSFT0201 device ID: 0x{msft_devid:04x}, "
                f"has_mapping: {has_mapping}\n"
            )
            self.db.record_debug(debug_str)

            if not has_mapping:
                self.db.record_prereq(
                    "IOMMU is misconfigured: MSFT0201 declared in IVRS but no DMA mapping",
                    "❌",
                )
                self.failures += [DMArNotEnabled()]
                return False

            self.db.record_prereq("IOMMU properly configured", "✅")
            return True
        return True

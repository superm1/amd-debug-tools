#!/usr/bin/python3
# SPDX-License-Identifier: MIT

"""
This module contains the s0i3 prerequisite validator for amd-debug-tools.
"""

import configparser
import logging
import os
import platform
import re
import shutil
import subprocess
import tempfile
import struct
from datetime import datetime
from packaging import version

import pyudev

from amd_debug.wake import WakeIRQ
from amd_debug.display import Display
from amd_debug.kernel import get_kernel_log, SystemdLogger, CySystemdLogger, DmesgLogger
from amd_debug.common import (
    apply_prefix_wrapper,
    BIT,
    clear_temporary_message,
    find_ip_version,
    get_distro,
    get_pretty_distro,
    get_property_pyudev,
    is_root,
    minimum_kernel,
    print_color,
    print_temporary_message,
    read_file,
    read_msr,
    AmdTool,
)
from amd_debug.battery import Batteries
from amd_debug.database import SleepDatabase
from amd_debug.failures import (
    AcpiNvmeStorageD3Enable,
    AmdHsmpBug,
    AmdgpuPpFeatureMask,
    ASpmWrong,
    DeepSleep,
    DevSlpDiskIssue,
    DevSlpHostIssue,
    DMArNotEnabled,
    DmcubTooOld,
    DmiNotSetup,
    FadtWrong,
    I2CHidBug,
    KernelRingBufferWrapped,
    LimitedCores,
    MissingAmdgpu,
    MissingAmdgpuFirmware,
    MissingAmdPmc,
    MissingDriver,
    MissingIommuACPI,
    MissingIommuPolicy,
    MissingThunderbolt,
    MissingXhciHcd,
    MSRFailure,
    RogAllyMcuPowerSave,
    RogAllyOldMcu,
    SleepModeWrong,
    SMTNotEnabled,
    TaintedKernel,
    UnservicedGpio,
    UnsupportedModel,
    WCN6855Bug,
)

# test if fwupd can report device firmware versions
try:
    import gi
    from gi.repository import GLib as _

    gi.require_version("Fwupd", "2.0")
    from gi.repository import Fwupd  # pylint: disable=wrong-import-position

    FWUPD = True
except ImportError:
    FWUPD = False
except ValueError:
    FWUPD = False


class Headers:
    """Headers for the script"""

    NvmeSimpleSuspend = "platform quirk: setting simple suspend"
    RootError = "Must be executed by root user"
    BrokenPrerequisites = "Your system does not meet s2idle prerequisites!"
    ExplanationReport = "Explanations for your system"


class PrerequisiteValidator(AmdTool):
    """Class to validate the prerequisites for s2idle"""

    def __init__(self, tool_debug):
        log_prefix = "s2idle" if tool_debug else None
        super().__init__(log_prefix)

        self.kernel_log = get_kernel_log()
        if not is_root():
            raise PermissionError("not root user")
        self.cpu_family = None
        self.cpu_model = None
        self.cpu_model_string = None
        self.pyudev = pyudev.Context()
        self.failures = []
        self.db = SleepDatabase()
        self.db.start_cycle(datetime.now())
        self.debug = tool_debug
        self.distro = get_distro()
        self.cmdline = read_file(os.path.join("/proc", "cmdline"))
        self.irqs = []
        self.smu_version = ""
        self.smu_program = ""
        self.display = Display()

    def capture_once(self):
        """Capture the prerequisites once"""
        if not self.db.get_last_prereq_ts():
            self.run()

    def capture_nvidia(self):
        """Capture the NVIDIA GPU state"""
        p = os.path.join("/", "proc", "driver", "nvidia", "version")
        if not os.path.exists(p):
            return True
        try:
            self.db.record_debug_file(p)
        except PermissionError:
            self.db.record_prereq("NVIDIA GPU version not readable", "👀")
            return True
        p = os.path.join("/", "proc", "driver", "nvidia", "gpus")
        if not os.path.exists(p):
            return True
        for root, _dirs, files in os.walk(p, topdown=False):
            for f in files:
                try:
                    self.db.record_debug(f"NVIDIA {f}")
                    self.db.record_debug_file(os.path.join(root, f))
                except PermissionError:
                    self.db.record_prereq("NVIDIA GPU {f} not readable", "👀")
        return True

    def capture_edid(self):
        """Capture and decode the EDID data"""
        edids = self.display.get_edid()
        if len(edids) == 0:
            self.db.record_debug("No EDID data found")
            return True
        for name, p in edids.items():
            output = None
            for tool in ["di-edid-decode", "edid-decode"]:
                try:
                    cmd = [tool, p]
                    output = subprocess.check_output(
                        cmd, stderr=subprocess.DEVNULL
                    ).decode("utf-8", errors="ignore")
                    break
                except FileNotFoundError:
                    self.db.record_debug(f"{cmd} not installed")
                except subprocess.CalledProcessError as e:
                    pass
            if not output:
                self.db.record_prereq("Failed to capture EDID table", "👀")
            else:
                self.db.record_debug(apply_prefix_wrapper(f"EDID for {name}:", output))
        return True

    def check_amdgpu(self):
        """Check for the AMDGPU driver"""
        for device in self.pyudev.list_devices(subsystem="pci"):
            klass = device.properties.get("PCI_CLASS")
            if klass not in ["30000", "38000"]:
                continue
            pci_id = device.properties.get("PCI_ID")
            if not pci_id.startswith("1002"):
                continue
            if device.properties.get("DRIVER") != "amdgpu":
                self.db.record_prereq("GPU driver `amdgpu` not loaded", "❌")
                self.failures += [MissingAmdgpu()]
                return False
            slot = device.properties.get("PCI_SLOT_NAME")

            self.db.record_prereq(f"GPU driver `amdgpu` bound to {slot}", "✅")
        return True

    def check_amdgpu_parameters(self):
        """Check for AMDGPU parameters"""
        p = os.path.join("/", "sys", "module", "amdgpu", "parameters", "ppfeaturemask")
        if os.path.exists(p):
            v = read_file(p)
            if v != "0xfff7bfff":
                self.db.record_prereq(f"AMDGPU ppfeaturemask overridden to {v}", "❌")
                self.failures += [AmdgpuPpFeatureMask()]
                return False
        if not self.kernel_log:
            message = "Unable to test for amdgpu from kernel log"
            self.db.record_prereq(message, "🚦")
            return True
        self.kernel_log.seek()
        match = self.kernel_log.match_pattern("Direct firmware load for amdgpu.*failed")
        if match and not "amdgpu/isp" in match:
            self.db.record_prereq("GPU firmware missing", "❌")
            self.failures += [MissingAmdgpuFirmware([match])]
            return False
        return True

    def check_wcn6855_bug(self):
        """Check if WCN6855 WLAN is affected by a bug that causes spurious wakeups"""
        if not self.kernel_log:
            message = "Unable to test for wcn6855 bug from kernel log"
            self.db.record_prereq(message, "🚦")
            return True
        wcn6855 = False
        self.kernel_log.seek()
        if self.kernel_log.match_pattern("ath11k_pci.*wcn6855"):
            match = self.kernel_log.match_pattern("ath11k_pci.*fw_version")
            if match:
                self.db.record_debug(f"WCN6855 version string: {match}")
                objects = match.split()
                for i, obj in enumerate(objects):
                    if obj == "fw_build_id":
                        wcn6855 = objects[i + 1]

        if wcn6855:
            components = wcn6855.split(".")
            if int(components[-1]) >= 37 or int(components[-1]) == 23:
                self.db.record_prereq(
                    f"WCN6855 WLAN (fw build id {wcn6855})",
                    "✅",
                )
            else:
                self.db.record_prereq(
                    f"WCN6855 WLAN may cause spurious wakeups (fw version {wcn6855})",
                    "❌",
                )
                self.failures += [WCN6855Bug()]

        return True

    def check_storage(self):
        """Check if storage devices are supported"""
        has_sata = False
        has_ahci = False
        valid_nvme = {}
        invalid_nvme = {}
        valid_sata = False
        valid_ahci = False

        if not self.kernel_log:
            message = "Unable to test storage from kernel log"
            self.db.record_prereq(message, "🚦")
            return True

        for dev in self.pyudev.list_devices(subsystem="pci", DRIVER="nvme"):
            # https://git.kernel.org/torvalds/c/e79a10652bbd3
            if minimum_kernel(6, 10):
                break
            pci_slot_name = dev.properties["PCI_SLOT_NAME"]
            vendor = dev.properties.get("ID_VENDOR_FROM_DATABASE", "")
            model = dev.properties.get("ID_MODEL_FROM_DATABASE", "")
            message = f"{vendor} {model}"
            self.kernel_log.seek()
            pattern = f"{pci_slot_name}.*{Headers.NvmeSimpleSuspend}"
            if self.kernel_log.match_pattern(pattern):
                valid_nvme[pci_slot_name] = message
            if pci_slot_name not in valid_nvme:
                invalid_nvme[pci_slot_name] = message

        for dev in self.pyudev.list_devices(subsystem="pci", DRIVER="ahci"):
            has_ahci = True
            break

        for dev in self.pyudev.list_devices(subsystem="block", ID_BUS="ata"):
            has_sata = True
            break

        # Test AHCI
        if has_ahci:
            self.kernel_log.seek()
            pattern = "ahci.*flags.*sadm.*sds"
            if self.kernel_log.match_pattern(pattern):
                valid_ahci = True
        # Test SATA
        if has_sata:
            self.kernel_log.seek()
            pattern = "ata.*Features.*Dev-Sleep"
            if self.kernel_log.match_pattern(pattern):
                valid_sata = True

        if invalid_nvme:
            for disk, _name in invalid_nvme.items():
                message = f"NVME {invalid_nvme[disk].strip()} is not configured for s2idle in BIOS"
                self.db.record_prereq(message, "❌")
                num = len(invalid_nvme) + len(valid_nvme)
                self.failures += [AcpiNvmeStorageD3Enable(invalid_nvme[disk], num)]
        if valid_nvme:
            for disk, _name in valid_nvme.items():
                message = (
                    f"NVME {valid_nvme[disk].strip()} is configured for s2idle in BIOS"
                )
                self.db.record_prereq(message, "✅")
        if has_sata:
            if valid_sata:
                message = "SATA supports DevSlp feature"
                self.db.record_prereq(message, "✅")
            else:
                message = "SATA does not support DevSlp feature"
                self.db.record_prereq(message, "❌")
                self.failures += [DevSlpDiskIssue()]
        if has_ahci:
            if valid_ahci:
                message = "AHCI is configured for DevSlp in BIOS"
                self.db.record_prereq(message, "✅")
            else:
                message = "AHCI is not configured for DevSlp in BIOS"
                self.db.record_prereq(message, "🚦")
                self.failures += [DevSlpHostIssue()]

        return (
            (len(invalid_nvme) == 0)
            and (valid_sata or not has_sata)
            and (valid_ahci or not has_sata)
        )

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

    def check_wlan(self):
        """Checks for WLAN device"""
        for device in self.pyudev.list_devices(subsystem="pci", PCI_CLASS="28000"):
            slot = device.properties["PCI_SLOT_NAME"]
            driver = device.properties.get("DRIVER")
            if not driver:
                self.db.record_prereq(f"WLAN device in {slot} missing driver", "🚦")
                self.failures += [MissingDriver(slot)]
                return False
            self.db.record_prereq(f"WLAN driver `{driver}` bound to {slot}", "✅")
        return True

    def check_usb3(self):
        """Check for the USB4 controller"""
        slots = []
        for device in self.pyudev.list_devices(subsystem="pci", PCI_CLASS="C0330"):
            slot = device.properties["PCI_SLOT_NAME"]
            if device.properties.get("DRIVER") != "xhci_hcd":
                self.db.record_prereq(
                    f"USB3 controller for {slot} not using `xhci_hcd` driver", "❌"
                )
                self.failures += [MissingXhciHcd()]
                return False
            slots += [slot]
        if slots:
            self.db.record_prereq(
                f"USB3 driver `xhci_hcd` bound to {', '.join(slots)}", "✅"
            )
        return True

    def check_dpia_pg_dmcub(self):
        """Check if DMUB is new enough to PG DPIA when no USB4 present"""
        usb4_found = False
        for device in self.pyudev.list_devices(subsystem="pci", PCI_CLASS="C0340"):
            usb4_found = True
            break
        if usb4_found:
            self.db.record_debug("USB4 routers found, no need to check DMCUB version")
            return True
        # Check if matching DCN present
        for device in self.pyudev.list_devices(subsystem="pci"):
            current = None
            klass = device.properties.get("PCI_CLASS")
            if klass not in ["30000", "38000"]:
                continue
            pci_id = device.properties.get("PCI_ID")
            if not pci_id.startswith("1002"):
                continue
            hw_ver = {"major": 3, "minor": 5, "revision": 0}
            if not find_ip_version(device.sys_path, "DMU", hw_ver):
                continue

            # DCN was found, lookup version from sysfs
            p = os.path.join(device.sys_path, "fw_version", "dmcub_fw_version")
            if os.path.exists(p):
                current = int(read_file(p), 16)

            # no sysfs, try to look for version from debugfs
            if not current:
                slot = device.properties["PCI_SLOT_NAME"]
                p = os.path.join(
                    "/", "sys", "kernel", "debug", "dri", slot, "amdgpu_firmware_info"
                )
                contents = read_file(p)
                for line in contents.split("\n"):
                    if not line.startswith("DMCUB"):
                        continue
                    current = int(line.split()[-1], 16)
            if current:
                expected = 0x09001B00
                if current >= expected:
                    return True
                self.db.record_prereq("DMCUB Firmware is outdated", "❌")
                self.failures += [DmcubTooOld(current, expected)]
                return False
        return True

    def check_usb4(self):
        """Check if the thunderbolt driver is loaded"""
        slots = []
        for device in self.pyudev.list_devices(subsystem="pci", PCI_CLASS="C0340"):
            slot = device.properties["PCI_SLOT_NAME"]
            if device.properties.get("DRIVER") != "thunderbolt":
                self.db.record_prereq("USB4 driver `thunderbolt` missing", "❌")
                self.failures += [MissingThunderbolt()]
                return False
            slots += [slot]
        if slots:
            self.db.record_prereq(
                f"USB4 driver `thunderbolt` bound to {', '.join(slots)}", "✅"
            )
        return True

    def check_sleep_mode(self):
        """Check if the system is configured for s2idle"""
        fn = os.path.join("/", "sys", "power", "mem_sleep")
        if not os.path.exists(fn):
            self.db.record_prereq("Kernel doesn't support sleep", "❌")
            return False

        cmdline = read_file(os.path.join("/proc", "cmdline"))
        if "mem_sleep_default=deep" in cmdline:
            self.db.record_prereq(
                "Kernel command line is configured for 'deep' sleep", "❌"
            )
            self.failures += [DeepSleep()]
            return False
        if "[s2idle]" not in read_file(fn):
            self.failures += [SleepModeWrong()]
            self.db.record_prereq(
                "System isn't configured for s2idle in firmware setup", "❌"
            )
            return False
        self.db.record_prereq("System is configured for s2idle", "✅")
        return True

    def capture_smbios(self):
        """Capture the SMBIOS (DMI) information"""
        p = os.path.join("/", "sys", "class", "dmi", "id")
        if not os.path.exists(p):
            self.db.record_prereq("DMI data was not setup", "🚦")
            self.failures += [DmiNotSetup()]
            return False
        else:
            keys = {}
            filtered = [
                "product_serial",
                "board_serial",
                "board_asset_tag",
                "chassis_asset_tag",
                "chassis_serial",
                "modalias",
                "uevent",
                "product_uuid",
            ]
            for root, _dirs, files in os.walk(p, topdown=False):
                files.sort()
                for fname in files:
                    if "power" in root:
                        continue
                    if fname in filtered:
                        continue
                    contents = read_file(os.path.join(root, fname))
                    keys[fname] = contents
            if (
                "sys_vendor" not in keys
                or "product_name" not in keys
                or "product_family" not in keys
            ):
                self.db.record_prereq("DMI data not found", "❌")
                self.failures += [DmiNotSetup()]
                return False
            self.db.record_prereq(
                f"{keys['sys_vendor']} {keys['product_name']} ({keys['product_family']})",
                "💻",
            )
            debug_str = "DMI|value\n"
            for key, value in keys.items():
                if (
                    "product_name" in key
                    or "sys_vendor" in key
                    or "product_family" in key
                ):
                    continue
                debug_str += f"{key}| {value}\n"
            self.db.record_debug(debug_str)
        return True

    def check_lps0(self):
        """Check if LPS0 is enabled"""
        for m in ["acpi", "acpi_x86"]:
            p = os.path.join("/", "sys", "module", m, "parameters", "sleep_no_lps0")
            if not os.path.exists(p):
                continue
            fail = read_file(p) == "Y"
            if fail:
                self.db.record_prereq("LPS0 _DSM disabled", "❌")
            else:
                self.db.record_prereq("LPS0 _DSM enabled", "✅")
            return not fail
        self.db.record_prereq("LPS0 _DSM not found", "👀")
        return False

    def get_cpu_vendor(self) -> str:
        """Fetch information about the CPU vendor"""
        p = os.path.join("/", "proc", "cpuinfo")
        vendor = ""
        cpu = read_file(p)
        for line in cpu.split("\n"):
            if "vendor_id" in line:
                vendor = line.split()[-1]
                continue
            elif "cpu family" in line:
                self.cpu_family = int(line.split()[-1])
                continue
            elif "model name" in line:
                self.cpu_model_string = line.split(":")[-1].strip()
                continue
            elif "model" in line:
                self.cpu_model = int(line.split()[-1])
                continue
            if self.cpu_family and self.cpu_model and self.cpu_model_string:
                self.db.record_prereq(
                    f"{self.cpu_model_string} "
                    f"(family {self.cpu_family:x} model {self.cpu_model:x})",
                    "💻",
                )
                break
        return vendor

    # See https://github.com/torvalds/linux/commit/ec6c0503190417abf8b8f8e3e955ae583a4e50d4
    def check_fadt(self):
        """Check the kernel emitted a message indicating FADT had a bit set."""
        found = False
        if not self.kernel_log:
            message = "Unable to test FADT from kernel log"
            self.db.record_prereq(message, "🚦")
        else:
            self.kernel_log.seek()
            matches = ["Low-power S0 idle used by default for system suspend"]
            found = self.kernel_log.match_line(matches)
        # try to look at FACP directly if not found (older kernel compat)
        if not found:
            self.db.record_debug("Fetching low power idle bit directly from FADT")
            target = os.path.join("/", "sys", "firmware", "acpi", "tables", "FACP")
            try:
                with open(target, "rb") as r:
                    r.seek(0x70)
                    found = struct.unpack("<I", r.read(4))[0] & BIT(21)
            except FileNotFoundError:
                self.db.record_prereq("FADT check unavailable", "🚦")
                return True
            except PermissionError:
                self.db.record_prereq("FADT check unavailable", "🚦")
                return True
        if found:
            message = "ACPI FADT supports Low-power S0 idle"
            self.db.record_prereq(message, "✅")
        else:
            message = "ACPI FADT doesn't support Low-power S0 idle"
            self.db.record_prereq(message, "❌")
            self.failures += [FadtWrong()]
        return found

    def capture_kernel_version(self):
        """Log the kernel version used"""
        self.db.record_prereq(f"{get_pretty_distro()}", "🐧")
        self.db.record_prereq(f"Kernel {platform.uname().release}", "🐧")

    def capture_irq(self):
        """Capture the IRQs to the log"""
        p = os.path.join("/sys", "kernel", "irq")
        for directory in os.listdir(p):
            if os.path.isdir(os.path.join(p, directory)):
                wake = WakeIRQ(directory, self.pyudev)
                self.irqs.append([int(directory), str(wake)])
        self.irqs.sort()
        self.db.record_debug("Interrupts")
        for irq in self.irqs:
            # set prefix if last IRQ
            prefix = "│ " if irq != self.irqs[-1] else "└─"
            self.db.record_debug(f"{prefix}{irq[0]}: {irq[1]}")
        return True

    def capture_disabled_pins(self):
        """Capture disabled pins from pinctrl-amd"""
        base = os.path.join("/", "sys", "module", "gpiolib_acpi", "parameters")
        debug_str = ""
        for parameter in ["ignore_wake", "ignore_interrupt"]:
            f = os.path.join(base, parameter)
            if not os.path.exists(f):
                continue
            with open(f, "r", encoding="utf-8") as r:
                d = r.read().rstrip()
                if d != "(null)":
                    debug_str += f"{f} is configured to {d}\n"
        if debug_str:
            debug_str = "Disabled pins:\n" + debug_str
            self.db.record_debug(debug_str)

    def check_logger(self):
        """Check the source for kernel logs"""
        if isinstance(self.kernel_log, SystemdLogger):
            self.db.record_prereq("Logs are provided via systemd", "✅")
        elif isinstance(self.kernel_log, CySystemdLogger):
            self.db.record_prereq("Logs are provided via cysystemd", "✅")
        elif isinstance(self.kernel_log, DmesgLogger):
            self.db.record_prereq(
                "Logs are provided via dmesg, timestamps may not be accurate over multiple cycles",
                "🚦",
            )
            header = self.kernel_log.capture_header()
            if not re.search(r"Linux version .*", header):
                self.db.record_prereq(
                    "Kernel ring buffer has wrapped, unable to accurately validate pre-requisites",
                    "❌",
                )
                self.failures += [KernelRingBufferWrapped()]
                return False
        return True

    def check_permissions(self):
        """Check if the user has permissions to write to /sys/power/state"""
        p = os.path.join("/", "sys", "power", "state")
        try:
            with open(p, "w", encoding="utf-8") as _w:
                pass
        except PermissionError:
            self.db.record_prereq(f"{Headers.RootError}", "👀")
            return False
        except FileNotFoundError:
            self.db.record_prereq("Kernel doesn't support power management", "❌")
            return False
        return True

    def capture_linux_firmware(self):
        """Capture the linux-firmware package version"""
        for num in range(0, 2):
            p = os.path.join(
                "/", "sys", "kernel", "debug", "dri", f"{num}", "amdgpu_firmware_info"
            )
            if os.path.exists(p):
                self.db.record_debug_file(p)

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

    def check_pinctrl_amd(self):
        """Check if the pinctrl_amd driver is loaded"""
        debug_str = ""
        for _device in self.pyudev.list_devices(
            subsystem="platform", DRIVER="amd_gpio"
        ):
            self.db.record_prereq("GPIO driver `pinctrl_amd` available", "✅")
            p = os.path.join("/", "sys", "kernel", "debug", "gpio")
            try:
                contents = read_file(p)
            except PermissionError:
                self.db.record_debug(f"Unable to capture {p}")
                contents = None
            header = False
            if contents:
                for line in contents.split("\n"):
                    if "WAKE_INT_MASTER_REG:" in line:
                        val = "en" if int(line.split()[1], 16) & BIT(15) else "dis"
                        self.db.record_debug(f"Windows GPIO 0 debounce: {val}abled")
                        continue
                    if not header and re.search("trigger", line):
                        debug_str += line + "\n"
                        header = True
                    if re.search("edge", line) or re.search("level", line):
                        debug_str += line + "\n"
                    if "🔥" in line:
                        self.failures += [UnservicedGpio()]
                        return False

            if debug_str:
                self.db.record_debug(debug_str)
            return True
        self.db.record_prereq("GPIO driver `pinctrl_amd` not loaded", "❌")
        return False

    def check_network(self):
        """Check network devices for s2idle support"""
        for device in self.pyudev.list_devices(subsystem="net", ID_NET_DRIVER="r8169"):
            interface = device.properties.get("INTERFACE")
            cmd = ["ethtool", interface]
            wol_supported = False
            try:
                output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode(
                    "utf-8"
                )
            except FileNotFoundError:
                self.db.record_prereq(f"ethtool is missing", "👀")
                return True
            for line in output.split("\n"):
                if "Supports Wake-on" in line:
                    val = line.split(":")[1].strip()
                    if "g" in val:
                        self.db.record_debug(f"{interface} supports WoL")
                        wol_supported = True
                    else:
                        self.db.record_debug(f"{interface} doesn't support WoL ({val})")
                elif "Wake-on" in line and wol_supported:
                    val = line.split(":")[1].strip()
                    if "g" in val:
                        self.db.record_prereq(f"{interface} has WoL enabled", "✅")
                    else:
                        self.db.record_prereq(
                            "Platform may have low hardware sleep residency "
                            "with Wake-on-lan disabled. Run `ethtool -s "
                            f"{interface} wol g` to enable it if necessary.",
                            "🚦",
                        )
        return True

    def check_asus_rog_ally(self):
        """Check for MCU version on ASUS ROG Ally devices"""
        for dev in self.pyudev.list_devices(subsystem="hid", DRIVER="asus_rog_ally"):
            p = os.path.join(dev.sys_path, "mcu_version")
            if not os.path.exists(p):
                continue
            v = int(read_file(p))
            hid_id = get_property_pyudev(dev.properties, "HID_ID", "")
            if "1ABE" in hid_id:
                minv = 319
            elif "1B4C" in hid_id:
                minv = 313
            else:
                minv = None
            if minv and v < minv:
                self.db.record_prereq("ROG Ally MCU firmware too old", "❌")
                self.failures += [RogAllyOldMcu(minv, v)]
                return False
            else:
                self.db.record_debug("ASUS ROG MCU found with MCU version %d", v)
        for dev in self.pyudev.list_devices(subsystem="firmware-attributes"):
            p = os.path.join(
                dev.sys_path, "attributes", "mcu_powersave", "current_value"
            )
            if not os.path.exists(p):
                continue
            v = int(read_file(p))
            if v < 1:
                self.db.record_prereq(
                    "Rog Ally doesn't have MCU powersave enabled", "❌"
                )
                self.failures += [RogAllyMcuPowerSave()]
                return False

        return True

    def check_device_firmware(self):
        """Check for device firmware issues"""
        if not FWUPD:
            self.db.record_debug(
                "Device firmware checks unavailable without gobject introspection"
            )
            return True

        client = Fwupd.Client()
        devices = client.get_devices()
        for device in devices:
            # Dictionary of instance id to firmware version mappings that
            # have been "reported" to be problematic
            device_map = {
                # https://gitlab.freedesktop.org/drm/amd/-/issues/3443
                "8c36f7ee-cc11-4a36-b090-6363f54ecac2": "0.1.26",
            }
            interesting_plugins = ["nvme", "tpm", "uefi_capsule"]
            if device.get_plugin() in interesting_plugins:
                logging.debug(
                    "%s %s firmware version: '%s'",
                    device.get_vendor(),
                    device.get_name(),
                    device.get_version(),
                )
                logging.debug("| %s", device.get_guids())
                logging.debug("└─%s", device.get_instance_ids())
            for item, ver in device_map.items():
                if (
                    item in device.get_guids() or item in device.get_instance_ids()
                ) and ver in device.get_version():
                    self.db.record_prereq(
                        "Platform may have problems resuming.  Upgrade the "
                        f"firmware for '{device.get_name()}' if you have problems.",
                        "🚦",
                    )
        return True

    def check_aspm(self):
        """Check if ASPM has been overridden"""
        p = os.path.join("/", "sys", "module", "pcie_aspm", "parameters", "policy")
        contents = read_file(p)
        policy = ""
        for word in contents.split(" "):
            if word.startswith("["):
                policy = word
                break
        if policy != "[default]":
            self.db.record_prereq(f"ASPM policy set to {policy}", "❌")
            self.failures += [ASpmWrong()]
            return False
        self.db.record_prereq("ASPM policy set to 'default'", "✅")
        return True

    def check_i2c_hid(self):
        """Check for I2C HID devices"""
        devices = []
        for dev in self.pyudev.list_devices(subsystem="input"):
            if "NAME" not in dev.properties:
                continue
            parent = dev.find_parent(subsystem="i2c")
            if parent is None:
                continue
            devices.append(dev)
        if not devices:
            return True
        ret = True
        debug_str = "I2C HID devices:\n"
        for dev in devices:
            name = dev.properties["NAME"]
            parent = dev.find_parent(subsystem="i2c")
            p = os.path.join(parent.sys_path, "firmware_node", "path")
            if os.path.exists(p):
                acpi_path = read_file(p)
            else:
                acpi_path = ""
            p = os.path.join(parent.sys_path, "firmware_node", "hid")
            if os.path.exists(p):
                acpi_hid = read_file(p)
            else:
                acpi_hid = ""
            # set prefix if last device
            prefix = "│ " if dev != devices[-1] else "└─"
            debug_str += f"{prefix}{name} [{acpi_hid}] : {acpi_path}\n"
            if "IDEA5002" in name:
                remediation = (
                    f"echo {parent.sys_path.split('/')[-1]} | "
                    f"sudo tee /sys/bus/i2c/drivers/{parent.driver}/unbind"
                )

                self.db.record_prereq(f"{name} may cause spurious wakeups", "❌")
                self.failures += [I2CHidBug(name, remediation)]
                ret = False
        self.db.record_debug(debug_str)
        return ret

    def capture_pci_acpi(self):
        """Map ACPI to PCI devices"""
        devices = []
        for dev in self.pyudev.list_devices(subsystem="pci"):
            devices.append(dev)
        debug_str = "PCI Slot | Vendor | Class | ID | ACPI path\n"
        for dev in devices:
            pci_id = dev.properties["PCI_ID"].lower()
            pci_slot_name = dev.properties["PCI_SLOT_NAME"]
            database_class = get_property_pyudev(
                dev.properties, "ID_PCI_SUBCLASS_FROM_DATABASE", ""
            )
            database_vendor = get_property_pyudev(
                dev.properties, "ID_VENDOR_FROM_DATABASE", ""
            )
            if dev.parent.subsystem != "pci":
                if dev == devices[-1]:
                    prefix = "└─"
                else:
                    prefix = "│ "
            else:
                if dev == devices[-1]:
                    prefix = "└─"
                else:
                    prefix = "├─ "
            p = os.path.join(dev.sys_path, "firmware_node", "path")
            if os.path.exists(p):
                acpi = read_file(p)
            else:
                acpi = ""
            debug_str += (
                f"{prefix}{pci_slot_name} | "
                f"{database_vendor} | {database_class} | {pci_id} | {acpi}\n"
            )
        if debug_str:
            self.db.record_debug(debug_str)

    def map_acpi_path(self):
        """Map of ACPI devices to ACPI paths"""
        devices = []
        for dev in self.pyudev.list_devices(subsystem="acpi"):
            p = os.path.join(dev.sys_path, "path")
            if not os.path.exists(p):
                continue
            p = os.path.join(dev.sys_path, "status")
            if os.path.exists(p):
                status = int(read_file(p))
                if status == 0:
                    continue
            devices.append(dev)
        debug_str = "ACPI name | ACPI path | Kernel driver\n"
        for dev in devices:
            p = os.path.join(dev.sys_path, "path")
            pth = read_file(p)
            p = os.path.join(dev.sys_path, "physical_node", "driver")
            if os.path.exists(p):
                driver = os.path.basename(os.readlink(p))
            else:
                driver = None
            debug_str += f"{dev.sys_name} | {pth} | {driver}\n"
        if debug_str:
            self.db.record_debug(debug_str)
        return True

    def capture_acpi(self):
        """Capture ACPI tables"""
        base = os.path.join("/", "sys", "firmware", "acpi", "tables")
        for root, _dirs, files in os.walk(base, topdown=False):
            for fname in files:
                target = os.path.join(root, fname)
                if "SSDT" in fname:
                    with open(target, "rb") as f:
                        s = f.read()
                        if s.find(b"_AEI") < 0:
                            continue
                elif "IVRS" in fname:
                    pass
                else:
                    continue
                try:
                    tmpd = tempfile.mkdtemp()
                    prefix = os.path.join(tmpd, "acpi")
                    subprocess.check_call(
                        ["iasl", "-p", prefix, "-d", target],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    self.db.record_debug_file(f"{prefix}.dsl")
                except FileNotFoundError as e:
                    self.db.record_prereq(f"Failed to capture ACPI table: {e}", "👀")
                except subprocess.CalledProcessError as e:
                    self.db.record_prereq(
                        f"Failed to capture ACPI table: {e.output}", "👀"
                    )
                finally:
                    shutil.rmtree(tmpd)
        return True

    def capture_cstates(self):
        """Capture ACPI C state information for the first CPU (assumes the same for all CPUs)"""
        base = os.path.join("/", "sys", "bus", "cpu", "devices", "cpu0", "cpuidle")
        paths = {}
        for root, _dirs, files in os.walk(base, topdown=False):
            for fname in files:
                target = os.path.join(root, fname)
                with open(target, "rb") as f:
                    paths[target] = f.read()
        debug_str = "ACPI C-state information\n"
        for path, data in paths.items():
            prefix = "│ " if path != list(paths.keys())[-1] else "└─"
            debug_str += f"{prefix}{path}: {data.decode('utf-8', 'ignore')}"
        self.db.record_debug(debug_str)

    def capture_battery(self):
        """Capture battery information"""
        obj = Batteries()
        for bat in obj.get_batteries():
            desc = obj.get_description_string(bat)
            self.db.record_prereq(desc, "🔋")

    def capture_logind(self):
        """Capture logind.conf settings"""
        base = os.path.join("/", "etc", "systemd", "logind.conf")
        if not os.path.exists(base):
            return True

        config = configparser.ConfigParser()
        config.read(base)
        section = config["Login"]
        if not section.keys():
            self.db.record_debug("LOGIND: no configuration changes")
            return True
        self.db.record_debug("LOGIND: configuration changes:")
        for key in section.keys():
            self.db.record_debug(f"\t{key}: {section[key]}")

    def check_cpu(self):
        """Check if the CPU is supported"""

        def read_cpuid(cpu, leaf, subleaf):
            """Read CPUID using kernel userspace interface"""
            p = os.path.join("/", "dev", "cpu", f"{cpu}", "cpuid")
            if not os.path.exists(p):
                os.system("modprobe cpuid")
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
        # https://www.amd.com/content/dam/amd/en/documents/processor-tech-docs/programmer-references/24594.pdf
        # Extended Topology Enumeration (NumLogCores)
        # CPUID 0x80000026 subleaf 1
        try:
            _, cpu_count, _, _ = read_cpuid(0, 0x80000026, 1)
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

    def check_msr(self):
        """Check if PC6 or CC6 has been disabled"""

        def check_bits(value, mask):
            return value & mask

        expect = {
            0xC0010292: BIT(32),  # PC6
            0xC0010296: (BIT(22) | BIT(14) | BIT(6)),  # CC6
        }
        try:
            for reg, expect_val in expect.items():
                val = read_msr(reg, 0)
                if not check_bits(val, expect_val):
                    self.failures += [MSRFailure()]
                    return False
            self.db.record_prereq("PC6 and CC6 enabled", "✅")
        except FileNotFoundError:
            self.db.record_prereq(
                "Unable to check MSRs: MSR kernel module not loaded", "❌"
            )
            return False
        except PermissionError:
            self.db.record_prereq("MSR checks unavailable", "🚦")
        return True

    def check_smt(self):
        """Check if SMT is enabled"""
        p = os.path.join("/", "sys", "devices", "system", "cpu", "smt", "control")
        v = read_file(p)
        self.db.record_debug(f"SMT control: {v}")
        if v == "notsupported":
            return True
        p = os.path.join("/", "sys", "devices", "system", "cpu", "smt", "active")
        v = read_file(p)
        if v == "0":
            self.failures += [SMTNotEnabled()]
            self.db.record_prereq("SMT is not enabled", "❌")
            return False
        self.db.record_prereq("SMT enabled", "✅")
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
            found_dmar = False
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
            if not found_ivrs_dmar and not found_ivrs_msft0201:
                self.db.record_prereq(
                    "IOMMU is misconfigured: Pre-boot DMA protection not enabled", "❌"
                )
                self.failures += [DMArNotEnabled()]
                return False
            self.db.record_prereq("IOMMU properly configured", "✅")
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

    def check_taint(self):
        """Check if the kernel is tainted"""
        fn = os.path.join("/", "proc", "sys", "kernel", "tainted")
        taint = int(read_file(fn))
        # ignore kernel warnings
        taint &= ~BIT(9)
        if taint != 0:
            self.db.record_prereq(f"Kernel is tainted: {taint}", "🚦")
            self.failures += [TaintedKernel()]
        return True

    def run(self):
        """Run the prerequisites check"""
        msg = "Checking prerequisites, please wait"
        print_temporary_message(msg)
        info = [
            self.capture_smbios,
            self.capture_kernel_version,
            self.capture_battery,
            self.capture_linux_firmware,
            self.capture_logind,
            self.capture_pci_acpi,
            self.capture_edid,
            self.capture_nvidia,
            self.capture_cstates,
        ]
        checks = []

        vendor = self.get_cpu_vendor()
        if vendor == "AuthenticAMD":
            info += [
                self.capture_disabled_pins,
            ]
            checks += [
                self.check_aspm,
                self.check_i2c_hid,
                self.check_pinctrl_amd,
                self.check_amd_hsmp,
                self.check_amd_pmc,
                self.check_amd_cpu_hpet_wa,
                self.check_port_pm_override,
                self.check_usb3,
                self.check_usb4,
                self.check_sleep_mode,
                self.check_storage,
                self.check_wcn6855_bug,
                self.check_amdgpu,
                self.check_amdgpu_parameters,
                self.check_cpu,
                self.check_msr,
                self.check_smt,
                self.check_iommu,
                self.check_asus_rog_ally,
                self.check_dpia_pg_dmcub,
            ]

        checks += [
            self.check_fadt,
            self.check_logger,
            self.check_lps0,
            self.check_permissions,
            self.check_wlan,
            self.check_taint,
            self.capture_acpi,
            self.map_acpi_path,
            self.check_device_firmware,
            self.check_network,
        ]

        for i in info:
            i()

        result = True
        for check in checks:
            if not check():
                result = False
        if not result:
            self.db.record_prereq(Headers.BrokenPrerequisites, "🚫")
        self.db.sync()
        clear_temporary_message(len(msg))
        return result

    def report(self) -> None:
        """Print a report of the results of the checks."""
        ts = self.db.get_last_prereq_ts()
        t0 = datetime.strptime(str(ts), "%Y%m%d%H%M%S")
        for row in self.db.report_prereq(t0):
            print_color(row[2], row[3])
        for row in self.db.report_debug(t0):
            for line in row[0].split("\n"):
                if self.debug:
                    print_color(line, "🦟")
                else:
                    logging.debug(line)

        if len(self.failures) == 0:
            return True
        print_color(Headers.ExplanationReport, "🗣️")
        for item in self.failures:
            item.get_failure()

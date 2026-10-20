# SPDX-License-Identifier: MIT

"""
This module contains the AMD GPU and platform specific checks for the s2idle
prerequisite validator.
"""

import os
import re

from amd_debug.common import (
    find_ip_version,
    get_property_pyudev,
    read_file,
    BIT,
)
from amd_debug.failures import (
    AmdgpuPpFeatureMask,
    DmcubTooOld,
    MissingAmdCaptureModule,
    MissingAmdgpu,
    MissingAmdgpuFirmware,
    MissingGpu,
    MissingIsp4PlatformDriver,
    RogAllyMcuPowerSave,
    RogAllyOldMcu,
    UnservicedGpio,
)


class AmdGpuChecks:
    """Mixin providing the AMD GPU related prerequisite checks"""

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

    def capture_linux_firmware(self):
        """Capture the linux-firmware package version"""
        for num in range(0, 2):
            p = os.path.join(
                "/", "sys", "kernel", "debug", "dri", f"{num}", "amdgpu_firmware_info"
            )
            if os.path.exists(p):
                self.db.record_debug_file(p)

    def check_amdgpu(self):
        """Check for the AMDGPU driver"""
        count = 0
        for device in self.pyudev.list_devices(subsystem="pci"):
            klass = device.properties.get("PCI_CLASS")
            if klass not in ["30000", "38000"]:
                continue
            pci_id = device.properties.get("PCI_ID")
            if not pci_id.startswith("1002"):
                continue
            count += 1
            if device.properties.get("DRIVER") != "amdgpu":
                self.db.record_prereq("GPU driver `amdgpu` not loaded", "❌")
                self.failures += [MissingAmdgpu()]
                return False
            slot = device.properties.get("PCI_SLOT_NAME")

            self.db.record_prereq(f"GPU driver `amdgpu` bound to {slot}", "✅")
        if count == 0:
            self.db.record_prereq("Integrated GPU not found", "❌")
            self.failures += [MissingGpu()]
            return False
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

    def check_isp4(self):
        """Check if camera supported by ISP is present and set up properly"""
        devices = []
        for dev in self.pyudev.list_devices(subsystem="acpi"):
            # look for ACPI device for camera (OMNI5C10:00 is seen today)
            if not dev.sys_name.startswith("OMNI5C10"):
                continue
            p = os.path.join(dev.sys_path, "path")
            if not os.path.exists(p):
                continue
            devices.append(dev)
        for dev in devices:
            p = os.path.join(dev.sys_path, "physical_node", "driver")
            if os.path.exists(p):
                driver = os.path.basename(os.readlink(p))
            else:
                driver = None
            if driver != "amd-isp4":
                self.db.record_prereq(
                    f"ISP4 platform camera driver 'amd-isp4' not bound to {dev.sys_name}",
                    "❌",
                )
                self.failures += [MissingIsp4PlatformDriver()]
                return False
            self.db.record_prereq(
                f"ISP4 platform camera driver 'amd-isp4' bound to {dev.sys_name}", "✅"
            )
            # check if `amd_capture` or `amd_isp4_capture` modules are loaded
            p1 = os.path.join("/", "sys", "module", "amd_capture")
            p2 = os.path.join("/", "sys", "module", "amd_isp4_capture")
            if not os.path.exists(p1) and not os.path.exists(p2):
                self.db.record_prereq(
                    "Camera driver module 'amd_capture'/'amd_isp4_capture' not loaded",
                    "❌",
                )
                self.failures += [MissingAmdCaptureModule()]
                return False
            self.db.record_prereq(
                "Camera driver module 'amd_capture'/'amd_isp4_capture' loaded", "✅"
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
            except FileNotFoundError:
                self.db.record_prereq("GPIO debugfs not available", "👀")
                contents = None
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

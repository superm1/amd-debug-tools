# SPDX-License-Identifier: MIT

"""
This module contains the device and hardware related checks for the s2idle
prerequisite validator.
"""

import logging
import os
import subprocess

from amd_debug.common import (
    apply_prefix_wrapper,
    get_property_pyudev,
    read_file,
)
from amd_debug.failures import (
    ASpmWrong,
    I2CHidBug,
    MissingDriver,
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


class DeviceChecks:
    """Mixin providing the device related prerequisite checks"""

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

    def check_aspm(self):
        """Check if ASPM has been overridden"""
        # pcie_aspm=off disables ASPM entirely but leaves the reported
        # policy at [default], so the sysfs check below can't catch it
        if "pcie_aspm=off" in self.cmdline.split():
            self.db.record_prereq(
                "ASPM disabled on kernel command line (pcie_aspm=off)", "❌"
            )
            self.failures += [ASpmWrong()]
            return False
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

    def capture_edid(self):
        """Capture and decode the EDID data"""
        edids = self.display.get_edid()
        if len(edids) == 0:
            self.db.record_debug("No EDID data found")
            return True
        for p in edids:
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
                except subprocess.CalledProcessError as _e:
                    pass
            if not output:
                self.db.record_prereq("Failed to capture EDID table", "👀")
            else:
                self.db.record_debug(apply_prefix_wrapper(f"EDID for {p}:", output))
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

# SPDX-License-Identifier: MIT

"""
This module contains the system level checks for the s2idle prerequisite
validator.
"""

import configparser
import os
import platform
import re
import subprocess

from amd_debug.battery import Batteries
from amd_debug.common import (
    get_pretty_distro,
    read_file,
    BIT,
)
from amd_debug.failures import (
    DeepSleep,
    DmiNotSetup,
    KernelRingBufferWrapped,
    SleepModeWrong,
    SMTNotEnabled,
    TaintedKernel,
)
from amd_debug.kernel import (
    CySystemdLogger,
    DmesgLogger,
    SystemdLogger,
)
from amd_debug.prereq.base_headers import Headers


class SystemChecks:
    """Mixin providing the system level prerequisite checks"""

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

    def capture_kernel_version(self):
        """Log the kernel version used"""
        self.db.record_prereq(f"{get_pretty_distro()}", "🐧")
        self.db.record_prereq(f"Kernel {platform.uname().release}", "🐧")

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
                self.db.record_prereq("ethtool is missing", "👀")
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

        config = configparser.ConfigParser(interpolation=None)
        config.read(base)
        section = config["Login"]
        if not section.keys():
            self.db.record_debug("LOGIND: no configuration changes")
            return True
        self.db.record_debug("LOGIND: configuration changes:")
        for key in section.keys():
            self.db.record_debug(f"\t{key}: {section[key]}")
        return True

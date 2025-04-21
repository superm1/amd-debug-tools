#!/usr/bin/python3
# SPDX-License-Identifier: MIT

import glob
import math
import os
import re
import random
import subprocess
import time
from datetime import timedelta, datetime
from packaging import version

from amd_debug.sleep_report import SleepReport
from amd_debug.database import SleepDatabase
from amd_debug.battery import Batteries
from amd_debug.kernel_log import get_kernel_log
from amd_debug.common import (
    print_color,
    read_file,
    check_lockdown,
    Colors,
    run_countdown,
    BIT,
    AmdTool,
)
from amd_debug.failures import (
    AcpiBiosError,
    Irq1Workaround,
    LowHardwareSleepResidency,
    SpuriousWakeup,
    RtcAlarmWrong,
    IommuPageFault,
)


class Headers:
    """Header strings for the debug output"""

    Irq1Workaround = "Disabling IRQ1 wakeup source to avoid platform firmware bug"
    WokeFromIrq = "Woke up from IRQ"
    LastCycleResults = "Results from last s2idle cycle"
    CycleCount = "Suspend cycle"
    SuspendDuration = "Suspend timer programmed for"


def soc_needs_irq1_wa(family, model, smu_version):
    """Check if the SoC needs the IRQ1 workaround"""
    if family == 0x17:
        if model in [0x68, 0x60]:
            return True
    elif family == 0x19:
        if model == 0x50:
            return version.parse(smu_version) < version.parse("64.66.0")
    return False


def pm_debugging(func):
    """Decorator to enable pm_debug_messages"""

    def runner(*args, **kwargs):
        # enable PM debugging
        pm_debug_messages = os.path.join("/", "sys", "power", "pm_debug_messages")
        with open(pm_debug_messages, "w", encoding="utf-8") as w:
            w.write("1")

        # enable ACPI debugging
        old_debug_level = None
        old_debug_layer = None
        old_trace_state = None
        acpi_base = os.path.join("/", "sys", "module", "acpi")
        acpi_debug_layer = os.path.join(acpi_base, "parameters", "trace_debug_layer")
        acpi_debug_level = os.path.join(acpi_base, "parameters", "trace_debug_level")
        acpi_trace_state = os.path.join(acpi_base, "parameters", "trace_state")
        if (
            os.path.exists(acpi_debug_level)
            and os.path.exists(acpi_debug_layer)
            and os.path.exists(acpi_trace_state)
        ):
            # backup old settings
            old_debug_level = read_file(acpi_debug_level)
            old_debug_layer = read_file(acpi_debug_layer)
            old_trace_state = read_file(acpi_trace_state)

            # enable ACPI_LV_INFO
            with open(acpi_debug_level, "w", encoding="utf-8") as w:
                w.write("0x00000004")

            # enable ACPI_EVENTS
            with open(acpi_debug_layer, "w", encoding="utf-8") as w:
                w.write("0x00000004")
            with open(acpi_trace_state, "w", encoding="utf-8") as w:
                w.write("enable")

        # getting the returned value
        ret = func(*args, **kwargs)

        # disable PM debugging
        with open(pm_debug_messages, "w", encoding="utf-8") as w:
            w.write("0")

        # disable ACPI debugging
        if old_debug_level:
            with open(acpi_debug_level, "w", encoding="utf-8") as w:
                w.write(old_debug_level)
        if old_debug_layer:
            with open(acpi_debug_layer, "w", encoding="utf-8") as w:
                w.write(old_debug_layer)
        if old_trace_state:
            with open(acpi_trace_state, "w", encoding="utf-8") as w:
                w.write("disable")
        return ret

    return runner


class SleepValidator(AmdTool):
    """Class to validate the sleep state"""

    def __init__(self, log_file, debug):
        super().__init__("amd-s2idle", log_file)

        from pyudev import Context

        self.pyudev = Context()

        self.kernel_log = get_kernel_log()
        self.db = SleepDatabase()
        self.batteries = Batteries()
        self.cpu_family = ""
        self.cpu_model = ""
        self.cpu_model_string = ""
        self.smu_version = ""
        self.smu_program = ""
        self.last_suspend = datetime.now()
        self.requested_duration = 0
        self.userspace_duration = 0
        self.kernel_duration = 0
        self.hw_sleep_duration = 0
        self.failures = []
        self.gpes = {}
        self.display_debug = debug
        self.lockdown = check_lockdown()
        self.logind = False
        self.upep = False
        self.cycle_count = 0
        self.upep = False
        self.upep_microsoft = False
        self.wakeup_irqs = []
        self.idle_masks = []
        self.acpi_errors = []
        self.active_gpios = []
        self.irq1_workaround = False
        self.thermal = {}
        self.wakeup_count = {}
        self.page_faults = []
        self.notify_devices = []

    def capture_running_compositors(self):
        """Capture information about known compositor processes found"""

        known_compositors = [
            "kwin_wayland",
            "gnome-shell",
            "cosmic-session",
            "hyprland",
        ]

        # Get a list of all process directories in /proc
        process_dirs = glob.glob("/proc/[0-9]*")

        # Extract and print the process names
        for proc_dir in process_dirs:
            p = os.path.join(proc_dir, "exe")
            if not os.path.exists(p):
                continue
            exe = os.path.basename(os.readlink(p)).split()[0]
            if exe in known_compositors:
                self.db.record_debug(f"{exe} compositor is running")

    def capture_power_profile(self):
        """Capture power profile information"""
        cmd = ["/usr/bin/powerprofilesctl"]
        if os.path.exists(cmd[0]):
            try:
                output = subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode(
                    "utf-8"
                )
                self.db.record_debug("Power Profiles:\n")
                for line in output.split("\n"):
                    self.db.record_debug(line)
            except subprocess.CalledProcessError as e:
                self.db.record_debug("Failed to run powerprofilesctl: %s", e.output)

    def capture_battery(self):
        """Capture battery energy levels"""
        for name in self.batteries.get_batteries():
            unit = self.batteries.get_energy_unit(name)
            energy = self.batteries.get_energy(name)
            full = self.batteries.get_energy_full(name)
            self.db.record_debug(f"{name} energy level is {energy} {unit}")
            report_unit = "W" if unit == "µWh" else "A"
            self.db.record_battery_energy(name, energy, full, report_unit)

    def check_rtc_cmos(self):
        """Check if the RTC is configured to use ACPI alarm"""
        p = os.path.join(
            "/", "sys", "module", "rtc_cmos", "parameters", "use_acpi_alarm"
        )
        val = read_file(p)
        if val == "N":
            self.db.record_cycle_data(
                "`rtc_cmos` not configured to use ACPI alarm", "🚦"
            )
            self.failures += [RtcAlarmWrong()]

    def check_gpes(self):
        """Capture general purpose event count"""
        base = os.path.join("/", "sys", "firmware", "acpi", "interrupts")
        for root, _dirs, files in os.walk(base, topdown=False):
            for fname in files:
                if not fname.startswith("gpe") or fname == "gpe_all":
                    continue
                target = os.path.join(root, fname)
                val = 0
                with open(target, "r") as r:
                    val = int(r.read().split()[0])
                if fname in self.gpes and self.gpes[fname] != val:
                    self.db.record_debug(
                        f"{fname} increased from {self.gpes[fname]} to {val}",
                    )
                self.gpes[fname] = val

    def capture_wake_sources(self):
        """Capture possible wakeup sources"""

        def get_input_sibling_name(pyudev, parent):
            """Get the name of the input sibling"""
            for input in pyudev.list_devices(subsystem="input", parent=parent):
                if not "NAME" in input.properties:
                    continue
                return input.properties["NAME"]
            return ""

        devices = []
        for wake_dev in self.pyudev.list_devices(subsystem="wakeup"):
            p = os.path.join(wake_dev.sys_path, "device", "power", "wakeup")
            if not os.path.exists(p):
                continue
            wake_en = read_file(p)
            name = ""
            sys_name = wake_dev.sys_path
            # determine the type of device it hangs off of
            acpi = wake_dev.find_parent(subsystem="acpi")
            serio = wake_dev.find_parent(subsystem="serio")
            rtc = wake_dev.find_parent(subsystem="rtc")
            pci = wake_dev.find_parent(subsystem="pci")
            mhi = wake_dev.find_parent(subsystem="mhi")
            pnp = wake_dev.find_parent(subsystem="pnp")
            hid = wake_dev.find_parent(subsystem="hid")
            thunderbolt_device = wake_dev.find_parent(
                subsystem="thunderbolt", device_type="thunderbolt_device"
            )
            thunderbolt_domain = wake_dev.find_parent(
                subsystem="thunderbolt", device_type="thunderbolt_domain"
            )
            i2c = wake_dev.find_parent(subsystem="i2c")
            if i2c is not None:
                sys_name = i2c.sys_name
                name = get_input_sibling_name(self.pyudev, i2c)
            elif thunderbolt_device is not None:
                if "USB4_TYPE" in thunderbolt_device.properties:
                    name = (
                        f'USB4 {thunderbolt_device.properties["USB4_TYPE"]} controller'
                    )
                sys_name = thunderbolt_device.sys_name
            elif thunderbolt_domain is not None:
                name = "Thunderbolt domain"
                sys_name = thunderbolt_domain.sys_name
            elif serio is not None:
                sys_name = serio.sys_name
                name = get_input_sibling_name(self.pyudev, serio)
            elif rtc is not None:
                sys_name = rtc.sys_name
                for _parent in self.pyudev.list_devices(
                    subsystem="platform", parent=rtc, DRIVER="alarmtimer"
                ):
                    name = "Real Time Clock alarm timer"
                    break
            elif mhi is not None:
                sys_name = mhi.sys_name
                name = "Mobile Broadband host interface"
            elif hid is not None:
                name = hid.properties["HID_NAME"]
                sys_name = hid.sys_name
            elif pci is not None:
                sys_name = pci.sys_name
                if (
                    "ID_PCI_SUBCLASS_FROM_DATABASE" in pci.properties
                    and "ID_VENDOR_FROM_DATABASE" in pci.properties
                ):
                    name = f'{pci.properties["ID_VENDOR_FROM_DATABASE"]} {pci.properties["ID_PCI_SUBCLASS_FROM_DATABASE"]}'
                else:
                    name = f"PCI {pci.properties['PCI_CLASS']}"
            elif acpi is not None:
                sys_name = acpi.sys_name
                if acpi.driver == "button":
                    for inp in self.pyudev.list_devices(subsystem="input", parent=acpi):
                        if not "NAME" in inp.properties:
                            continue
                        name = f"ACPI {inp.properties['NAME']}"
                        break
                elif acpi.driver in ["battery", "ac"]:
                    for ps in self.pyudev.list_devices(
                        subsystem="power_supply", parent=acpi
                    ):
                        if not "POWER_SUPPLY_NAME" in ps.properties:
                            continue
                        name = f"ACPI {ps.properties['POWER_SUPPLY_TYPE']}"
            elif pnp is not None:
                name = "Plug-n-play"
                if pnp.driver == "rtc_cmos":
                    name = f"{name} Real Time Clock"
                sys_name = pnp.sys_name

            name = name.replace('"', "")
            devices.append(f"{name} [{sys_name}]: {wake_en}")
        devices.sort()
        self.db.record_debug("Possible wakeup sources:")
        for dev in devices:
            # set prefix if last device
            prefix = "| " if dev != devices[-1] else "└─"
            self.db.record_debug(f"{prefix}{dev}")

    def capture_lid(self) -> None:
        """Capture lid state"""
        p = os.path.join("/", "proc", "acpi", "button", "lid")
        for root, _dirs, files in os.walk(p):
            for fname in files:
                p = os.path.join(root, fname)
                state = read_file(p).split(":")[1].strip()
                self.db.record_debug(f"ACPI Lid ({p}): {state}")

    def capture_wakeup_irq_data(self) -> bool:
        """Capture the wakeup IRQ to the log"""
        p = os.path.join("/", "sys", "power", "pm_wakeup_irq")
        try:
            n = read_file(p)
            p = os.path.join("/", "sys", "kernel", "irq", n)
            chip_name = read_file(os.path.join(p, "chip_name"))
            name = read_file(os.path.join(p, "name"))
            hw = read_file(os.path.join(p, "hwirq"))
            actions = read_file(os.path.join(p, "actions"))
            message = f"{Headers.WokeFromIrq} {n} ({chip_name} {hw}-{name} {actions})"
            self.db.record_debug(message)
        except OSError:
            pass
        return True

    def capture_amdgpu_ips_status(self):
        """Capture the AMDGPU IPS status"""
        for device in self.pyudev.list_devices(subsystem="pci", PCI_CLASS="38000"):
            pci_id = device.properties.get("PCI_ID")
            if not pci_id.startswith("1002"):
                continue
            slot = device.properties.get("PCI_SLOT_NAME")
            p = os.path.join(
                "/", "sys", "kernel", "debug", "dri", slot, "amdgpu_dm_ips_status"
            )
            if not os.path.exists(p):
                continue
            self.db.record_debug("IPS status\n")
            try:
                lines = read_file(p).split("\n")
                for line in lines:
                    prefix = "│ " if line != lines[-1] else "└─"
                    self.db.record_debug(f"{prefix}{line}")
            except PermissionError:
                if self.lockdown:
                    self.db.record_debug(
                        "Unable to gather IPS state data due to kernel lockdown."
                    )
                else:
                    self.db.record_debug("Failed to read IPS state data")

    def capture_thermal(self):
        """Capture thermal zone information"""
        devs = []
        for dev in self.pyudev.list_devices(subsystem="acpi", DRIVER="thermal"):
            devs.append(dev)
        if not devs:
            return

        self.db.record_debug("Thermal zones\n")
        for dev in devs:
            prefix = "├─ " if dev != devs[-1] else "└─"
            detail_prefix = "│ \t" if dev != devs[-1] else "  \t"
            name = os.path.basename(dev.device_path)
            p = os.path.join(dev.sys_path, "thermal_zone")
            temp = int(read_file(os.path.join(p, "temp"))) / 1000

            self.db.record_debug(f"{prefix}{name}\n")
            if name not in self.thermal:
                self.db.record_debug(f"{detail_prefix} temp: {temp}°C\n")
            else:
                self.db.record_debug(
                    f"{detail_prefix} {self.thermal[name]}°C -> {temp}°C\n"
                )

            # handle all trip points
            trip_count = 0
            for f in os.listdir(p):
                if "trip_point" not in f:
                    continue
                if "temp" not in f:
                    continue
                trip_count = trip_count + 1

            for i in range(0, trip_count):
                f = os.path.join(p, f"trip_point_{i}_type")
                trip_type = read_file(f)
                f = os.path.join(p, f"trip_point_{i}_temp")
                trip = int(read_file(f)) / 1000

                if name not in self.thermal:
                    self.db.record_debug(
                        f"{detail_prefix} {trip_type} trip: {trip}°C\n"
                    )

                if temp > trip:
                    self.db.record_prereq(
                        f"Thermal zone {name} past trip point {trip_type}: {trip}°C",
                        "🌡️",
                    )
                    return False
            self.thermal[name] = temp

    def capture_input_wakeup_count(self):
        """Capture wakeup count for input related devices"""

        def get_wakeup_count(device):
            """Get the wakeup count for a device"""
            p = os.path.join(device.sys_path, "power", "wakeup")
            if not os.path.exists(p):
                return None
            p = os.path.join(device.sys_path, "power", "wakeup_count")
            if not os.path.exists(p):
                return None
            return read_file(p)

        wakeup_count = {}
        for device in self.pyudev.list_devices(subsystem="input"):
            count = get_wakeup_count(device)
            if count is not None:
                wakeup_count[device.sys_path] = count
                continue
            # iterate parents until finding one with a wakeup count
            # or no more parents
            parent = device.parent
            while parent is not None:
                count = get_wakeup_count(parent)
                if count is not None:
                    wakeup_count[parent.sys_path] = count
                    break
                parent = parent.parent

        # diff the count
        for device, count in wakeup_count.items():
            if device not in self.wakeup_count:
                continue
            if self.wakeup_count[device] == count:
                continue
            self.db.record_debug(
                f"Woke up from input source {device} ({self.wakeup_count[device]}->{count})",
                "💤",
            )
        self.wakeup_count = wakeup_count

    def capture_hw_sleep(self) -> bool:
        """Check for hardware sleep state"""
        # try from kernel 6.4's suspend stats interface first because it works
        # even with kernel lockdown
        if not self.hw_sleep_duration:
            p = os.path.join("/", "sys", "power", "suspend_stats", "last_hw_sleep")
            if os.path.exists(p):
                self.hw_sleep_duration = int(read_file(p)) / 10**6
        if not self.hw_sleep_duration:
            p = os.path.join("/", "sys", "kernel", "debug", "amd_pmc", "smu_fw_info")
            try:
                val = read_file(p)
                for line in val.split("\n"):
                    if "Last S0i3 Status" in line:
                        if "Success" in line:
                            result = True
                        continue
                    if "Time (in us) in S0i3" in line:
                        self.hw_sleep_duration = int(line.split(":")[1]) / 10**6
            except PermissionError:
                if self.lockdown:
                    self.db.record_cycle_data(
                        "Unable to gather hardware sleep data with lockdown engaged",
                        "🚦",
                    )
                else:
                    self.db.record_cycle_data(
                        "Failed to read hardware sleep data", "🚦"
                    )
                return False
            except FileNotFoundError:
                self.db.record_cycle_data("HW sleep statistics file missing", "❌")
                return False
        if not self.hw_sleep_duration:
            self.db.record_cycle_data("Did not reach hardware sleep state", "❌")

        return self.hw_sleep_duration is not None

    def capture_command_line(self):
        """Capture the kernel command line to debug"""
        cmdline = read_file(os.path.join("/proc", "cmdline"))
        # borrowed from https://github.com/fwupd/fwupd/blob/1.9.5/libfwupdplugin/fu-common-linux.c#L95
        filtered = [
            "apparmor",
            "audit",
            "auto",
            "boot",
            "BOOT_IMAGE",
            "console",
            "crashkernel",
            "cryptdevice",
            "cryptkey",
            "dm",
            "earlycon",
            "earlyprintk",
            "ether",
            "initrd",
            "ip",
            "LANG",
            "loglevel",
            "luks.key",
            "luks.name",
            "luks.options",
            "luks.uuid",
            "mitigations",
            "mount.usr",
            "mount.usrflags",
            "mount.usrfstype",
            "netdev",
            "netroot",
            "nfsaddrs",
            "nfs.nfs4_unique_id",
            "nfsroot",
            "noplymouth",
            "ostree",
            "quiet",
            "rd.dm.uuid",
            "rd.luks.allow-discards",
            "rd.luks.key",
            "rd.luks.name",
            "rd.luks.options",
            "rd.luks.uuid",
            "rd.lvm.lv",
            "rd.lvm.vg",
            "rd.md.uuid",
            "rd.systemd.mask",
            "rd.systemd.wants",
            "resume",
            "resumeflags",
            "rhgb",
            "ro",
            "root",
            "rootflags",
            "roothash",
            "rw",
            "security",
            "showopts",
            "splash",
            "swap",
            "systemd.mask",
            "systemd.show_status",
            "systemd.unit",
            "systemd.verity_root_data",
            "systemd.verity_root_hash",
            "systemd.wants",
            "udev.log_priority",
            "verbose",
            "vt.handoff",
            "zfs",
        ]
        # remove anything that starts with something in filtered from cmdline
        cmdline = " ".join(
            [x for x in cmdline.split() if not x.startswith(tuple(filtered))]
        )
        self.db.record_debug(f"/proc/cmdline: {cmdline}")

    def _analyze_kernel_log_line(self, line, priority):
        if "Timekeeping suspended for" in line:
            self.cycle_count += 1
            for f in line.split():
                try:
                    self.kernel_duration += float(f)
                except ValueError:
                    pass
        elif "Successfully transitioned to state" in line:
            self.upep = True
            if "Successfully transitioned to state lps0 ms entry" in line:
                self.upep_microsoft = True
        elif "_DSM function" in line:
            self.upep = True
            if "_DSM function 7" in line:
                self.upep_microsoft = True
        elif "Last suspend in deepest state for" in line:
            for f in line.split():
                if not f.endswith("us"):
                    continue
                try:
                    self.hw_sleep_duration += float(f.strip("us")) / 10**6
                except ValueError:
                    pass
        elif "Triggering wakeup from IRQ" in line:
            irq = int(line.split()[-1])
            if irq and irq not in self.wakeup_irqs:
                self.wakeup_irqs += [irq]
        elif "SMU idlemask s0i3" in line:
            self.idle_masks += [line.split()[-1]]
        elif "ACPI BIOS Error" in line or "ACPI Error" in line:
            self.acpi_errors += [line]
        elif re.search("GPIO.*is active", line):
            self.active_gpios += re.findall(
                r"\d+", re.search("GPIO.*is active", line).group()
            )
        elif Headers.Irq1Workaround in line:
            self.irq1_workaround = True
        # evmisc-0132 ev_queue_notify_reques: Dispatching Notify on [UBTC] (Device) Value 0x80 (Status Change) Node 0000000080144eee
        elif "Dispatching Notify on" in line:
            # add device without the [] to notify_devices if it's not already there
            device = re.search(r"\[(.*?)\]", line)
            if device:
                device = device.group(1)
                if device not in self.notify_devices:
                    self.notify_devices += [device]
        # AMD-Vi: Event logged [IO_PAGE_FAULT device=0000:00:0c.0 domain=0x0000 address=0x7e800000 flags=0x0050]
        elif "Event logged [IO_PAGE_FAULT" in line:
            # get the device from string
            device = re.search(r"device=(.*?) domain", line)
            if device:
                device = device.group(1)
                if device not in self.page_faults:
                    self.page_faults += [device]
        self.db.record_debug(line, priority)

    def analyze_kernel_log(self):
        """Analyze one of the lines from the kernel log"""
        self.cycle_count = 0
        self.upep = False
        self.upep_microsoft = False
        self.wakeup_irqs = []
        self.idle_masks = []
        self.acpi_errors = []
        self.active_gpios = []
        self.notify_devices = []
        self.page_faults = []
        self.irq1_workaround = False
        self.kernel_log.process_callback(self._analyze_kernel_log_line)

        if self.cycle_count:
            self.db.record_cycle_data(
                f"Hardware sleep cycle count: {self.cycle_count}",
                "💤",
            )
        if self.wakeup_irqs:
            if 1 in self.wakeup_irqs and soc_needs_irq1_wa(
                self.cpu_family, self.cpu_model, self.smu_version
            ):
                if self.irq1_workaround:
                    self.db.record_cycle_data(
                        "Kernel workaround for IRQ1 issue utilized", "○"
                    )
                else:
                    self.db.record_cycle_data("IRQ1 found during wakeup", "🚦")
                    self.failures += [Irq1Workaround()]
        if self.idle_masks:
            bit_changed = 0
            for i, mask_i in enumerate(self.idle_masks):
                for _j, mask_j in enumerate(self.idle_masks[i:], start=i):
                    if mask_i != mask_j:
                        bit_changed = bit_changed | (int(mask_i, 16) & ~int(mask_j, 16))
            if bit_changed:
                for bit in range(0, 31):
                    if bit_changed & BIT(bit):
                        self.db.record_debug(
                            f"Idle mask bit {bit} (0x{BIT(bit):x}) changed during suspend",
                            "○",
                        )
        if self.upep:
            if self.upep_microsoft:
                self.db.record_debug("Used Microsoft uPEP GUID in LPS0 _DSM")
            else:
                self.db.record_debug("Used AMD uPEP GUID in LPS0 _DSM")
        if self.acpi_errors:
            self.db.record_cycle_data("ACPI BIOS errors found", "❌")
            self.failures += [AcpiBiosError(self.acpi_errors)]
        if self.page_faults:
            self.db.record_cycle_data("Page faults found", "❌")
            self.failures += [IommuPageFault(self.page_faults)]
        if self.notify_devices:
            self.db.record_cycle_data(
                f"Notify devices {self.notify_devices} found during suspend", "💤"
            )

    def analyze_masks(self):
        """Analyze the idle masks for the CPU"""
        try:
            from amd_debug.common import add_model_checks

            func = add_model_checks(self.cpu_model, self.cpu_family)
            for mask in self.idle_masks:
                func(mask)
        except ImportError:
            pass

    def analyze_duration(self, t0, t1, requested, kernel, hw):
        """Analyze the duration of the last cycle"""
        userspace_duration = t1 - t0
        min_suspend_duration = timedelta(seconds=requested * 0.9)
        expected_wake_time = t0 + min_suspend_duration
        if t1 > expected_wake_time:
            print_color(
                f"Userspace suspended for {userspace_duration}",
                "✅",
            )
        else:
            print_color(
                f"Userspace suspended for {userspace_duration} (< minimum expected {min_suspend_duration})",
                "❌",
            )
            self.failures += [SpuriousWakeup(requested, userspace_duration)]
        percent = float(kernel) / userspace_duration.total_seconds()
        print_color(
            f"Kernel suspended for total of {timedelta(seconds=kernel)} ({percent:.2%})",
            "✅",
        )

        percent = float(hw / userspace_duration.total_seconds())
        if userspace_duration.total_seconds() >= 60:
            if percent > 0.9:
                symbol = "✅"
            else:
                symbol = "❌"
                self.failures += [
                    LowHardwareSleepResidency(userspace_duration, percent)
                ]
        else:
            symbol = "✅"
        print_color(
            "In a hardware sleep state for {time} {percent_msg}".format(
                time=timedelta(seconds=hw),
                percent_msg="" if not percent else "({:.2%})".format(percent),
            ),
            symbol,
        )

    def post(self):
        checks = [
            self.analyze_kernel_log,
            self.capture_wakeup_irq_data,
            self.check_gpes,
            self.capture_lid,
            self.check_rtc_cmos,
            self.capture_hw_sleep,
            self.capture_battery,
            self.capture_amdgpu_ips_status,
            self.capture_thermal,
            self.capture_input_wakeup_count,
        ]
        for check in checks:
            check()
        self.db.record_cycle(
            self.requested_duration,
            self.active_gpios,
            self.wakeup_irqs,
            self.kernel_duration,
            self.hw_sleep_duration,
        )

    def prep(self):
        self.last_suspend = datetime.now()
        self.kernel_log.seek_tail(self.last_suspend)
        self.db.start_cycle(self.last_suspend)
        self.kernel_duration = 0
        self.hw_sleep_duration = 0
        self.capture_battery()
        self.check_gpes()
        self.capture_lid()
        self.capture_command_line()
        self.capture_wake_sources()
        self.capture_running_compositors()
        self.capture_power_profile()
        self.capture_amdgpu_ips_status()
        self.capture_thermal()
        self.capture_input_wakeup_count()
        self.db.record_cycle()

    def program_wakealarm(self):
        """Program the RTC wakealarm to wake the system after the requested duration"""
        wakealarm = None
        for device in self.pyudev.list_devices(subsystem="rtc"):
            wakealarm = os.path.join(device.sys_path, "wakealarm")
        if wakealarm:
            with open(wakealarm, "w") as w:
                w.write("0")
            with open(wakealarm, "w") as w:
                w.write("+%s\n" % self.requested_duration)
        else:
            print_color("No RTC device found, please manually wake system", "🚦")

    @pm_debugging
    def suspend_system(self):
        """Suspend the system using the dbus or sysfs interface"""
        if self.logind:
            try:
                import dbus

                bus = dbus.SystemBus()
                obj = bus.get_object(
                    "org.freedesktop.login1", "/org/freedesktop/login1"
                )
                intf = dbus.Interface(obj, "org.freedesktop.login1.Manager")
                propf = dbus.Interface(obj, "org.freedesktop.DBus.Properties")
                if intf.CanSuspend() != "yes":
                    self.db.record_cycle_data("Unable to suspend", "❌")
                    return False
                intf.Suspend(True)
                while propf.Get("org.freedesktop.login1.Manager", "PreparingForSleep"):
                    time.sleep(1)
                return True
            except dbus.exceptions.DBusException as e:
                self.db.record_cycle_data(
                    f"Unable to communicate with logind: {e}", "❌"
                )
                return False
            except ImportError:
                self.db.record_cycle_data("Missing dbus", "❌")
                return False
        else:
            p = os.path.join("/", "sys", "power", "wakeup_count")
            f = read_file(p)
            try:
                with open(p, "w", encoding="utf-8") as w:
                    w.write(str(int(f)))
            except OSError as e:
                self.db.record_cycle_data(f"Failed to set wakeup count: {e}", "❌")
                return False
            p = os.path.join("/", "sys", "power", "state")
            with open(p, "w", encoding="utf-8") as w:
                w.write("mem")
            return True

    def unlock_session(self):
        """Unlock the session using logind"""
        if self.logind:
            try:
                import dbus

                bus = dbus.SystemBus()
                obj = bus.get_object(
                    "org.freedesktop.login1", "/org/freedesktop/login1"
                )
                intf = dbus.Interface(obj, "org.freedesktop.login1.Manager")
                intf.UnlockSessions()
            except dbus.exceptions.DBusException as e:
                self.db.record_cycle_data(
                    f"Unable to communicate with logind: {e}", "❌"
                )
                return False
        return True

    def run(self, duration, count, wait, rand, logind):
        """Run the suspend test"""
        if not count:
            return True

        if logind:
            self.logind = True

        if rand:
            print_color(
                f"Running {count} cycle random test with max duration of {duration}s and a max wait of {wait}s",
                Colors.HEADER,
            )
        elif count > 1:
            length = timedelta(seconds=(duration + wait) * count)
            print_color(
                f"Running {count} cycles (Test finish expected @ {datetime.now() + length})".format(),
                Colors.HEADER,
            )
        for i in range(1, count + 1):
            if rand:
                self.requested_duration = random.randint(1, duration)
                requested_wait = random.randint(1, wait)
            else:
                self.requested_duration = duration
                requested_wait = wait
            run_countdown("Suspending system", math.ceil(requested_wait / 2))
            self.prep()
            self.db.record_debug(
                f"{Headers.SuspendDuration} {timedelta(seconds=self.requested_duration)}",
            )
            if count > 1:
                header = f"{Headers.CycleCount} {i}: "
            else:
                header = ""
            print_color(
                f"{header}Started at {self.last_suspend} (cycle finish expected @ {datetime.now() + timedelta(seconds=self.requested_duration + requested_wait)})",
                Colors.HEADER,
            )
            self.program_wakealarm()
            if not self.suspend_system():
                return False
            run_countdown("Collecting data", math.ceil(requested_wait / 2))
            self.post()
            self.db.sync()
            self.report_cycle()
        self.unlock_session()
        return True

    def systemd_pre_hook(self):
        """Called before suspend"""
        self.prep()
        self.db.sync()

    def systemd_post_hook(self):
        """Called after resume"""
        t0 = self.db.get_last_cycle()
        self.last_suspend = datetime.strptime(str(t0[0]), "%Y%m%d%H%M%S")
        self.db.start_cycle(self.last_suspend)
        self.post()
        self.db.sync()

    def report_cycle(self):
        """Report the results of the last cycle"""
        print_color(Headers.LastCycleResults, Colors.HEADER)

        app = SleepReport(
            since=self.last_suspend,
            until=self.last_suspend,
            fname=None,
            fmt="stdout",
            debug=self.display_debug,
            log_file=self.log,
        )
        app.run(inc_prereq=False)
        return

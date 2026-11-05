# SPDX-License-Identifier: MIT

"""
This module contains the data capture helpers for the sleep validator.

These are the functions that collect the state of the system before the
system suspends and after it resumes.
"""

import glob
import os
import re
import subprocess
import time

from amd_debug.validator_headers import Headers
from amd_debug.common import read_file
from amd_debug.kernel import get_kernel_command_line
from amd_debug.failures import RtcAlarmWrong


def _cpuidle_state_index(name):
    """Sort key that orders cpuidle states by their numeric index

    A lexical sort would put state10 before state2.
    """
    try:
        return int(name[len("state"):])
    except ValueError:
        return -1


class CaptureHelpers:
    """Mixin providing the data capture helpers for the sleep validator"""

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
                self.db.record_debug("Power Profiles:")
                lines = output.split("\n")
                lines = [line for line in lines if line.strip()]
                for line in lines:
                    prefix = "│ " if line != lines[-1] else "└─"
                    self.db.record_debug(f"{prefix}{line.strip()}")
            except subprocess.CalledProcessError as e:
                self.db.record_debug("Failed to run powerprofilesctl: %s", e.output)

    def capture_battery(self):
        """Capture battery energy levels"""
        for name in self.batteries.get_batteries():
            energy = self.batteries.get_energy(name)
            full = self.batteries.get_energy_full(name)
            self.db.record_debug(f"{name} energy level is {energy} µWh")
            self.db.record_battery_energy(name, energy, full, "W")

    def capture_power_rails(self):
        """Capture power rail energy levels"""
        if not self.power_rails.rails:
            return  # No IIO power rails detected

        for rail in self.power_rails.rails:
            try:
                energy = rail.read_energy_raw()
                self.db.record_power_rail_energy(rail.label, energy, rail.energy_scale)
            except OSError as e:
                self.db.record_debug(f"Failed to read {rail.label}: {e}", priority=1)

    def check_rtc_cmos(self):
        """Check if the RTC is configured to use ACPI alarm"""
        p = os.path.join(
            "/", "sys", "module", "rtc_cmos", "parameters", "use_acpi_alarm"
        )
        if not os.path.exists(p):
            return
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
                with open(target, "r", encoding="utf-8") as r:
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
            for inp in pyudev.list_devices(subsystem="input", parent=parent):
                if not "NAME" in inp.properties:
                    continue
                return inp.properties["NAME"]
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
            devices.append(f"{name}|{sys_name}|{wake_en}")
        devices.sort()
        debug_str = "Wakeup Source|Linux Device|Status\n"
        for dev in devices:
            debug_str += f"{dev}\n"
        self.db.record_debug(debug_str)

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
            irq = int(n)
            if irq and irq not in self.wakeup_irqs:
                self.wakeup_irqs += [irq]
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
            self.db.record_debug("IPS status")
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

        self.db.record_debug("Thermal zones")
        for dev in devs:
            prefix = "├─ " if dev != devs[-1] else "└─"
            detail_prefix = "│ \t" if dev != devs[-1] else "  \t"
            name = os.path.basename(dev.device_path)
            p = os.path.join(dev.sys_path, "thermal_zone")
            temp = int(read_file(os.path.join(p, "temp"))) / 1000

            self.db.record_debug(f"{prefix}{name}")
            if name not in self.thermal:
                self.db.record_debug(f"{detail_prefix} temp: {temp}°C")
            else:
                self.db.record_debug(
                    f"{detail_prefix} {self.thermal[name]}°C -> {temp}°C"
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
                    self.db.record_debug(f"{detail_prefix} {trip_type} trip: {trip}°C")

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
            )
        self.wakeup_count = wakeup_count

    def _read_cpuidle_states(self):
        """Read the cpuidle state counters of every CPU

        When the kernel exposes the suspend specific s2idle counters
        inside each state directory, those are used, since they only
        track the time spent in each state while the system is
        suspended.  Older kernels fall back to the regular counters,
        which accumulate across runtime and suspend alike.

        The counters are per CPU, so the time and the number of entries
        of each state are summed across all the CPUs of the system.  The
        states are ordered by their cpuidle index, which the idle drivers
        sort by increasing exit latency, i.e. from shallowest to deepest.
        """
        states = {}
        s2idle_counters = False
        for cpu in sorted(glob.glob("/sys/devices/system/cpu/cpu[0-9]*")):
            cpuidle = os.path.join(cpu, "cpuidle")
            if not os.path.isdir(cpuidle):
                continue
            for state in sorted(os.listdir(cpuidle), key=_cpuidle_state_index):
                if not state.startswith("state"):
                    continue
                p = os.path.join(cpuidle, state, "name")
                if not os.path.exists(p):
                    continue
                name = read_file(p)
                time_us = 0
                usage = 0
                s2idle_dir = os.path.join(cpuidle, state, "s2idle")
                if os.path.isdir(s2idle_dir):
                    s2idle_counters = True
                    time_path = os.path.join(s2idle_dir, "time")
                    usage_path = os.path.join(s2idle_dir, "usage")
                else:
                    time_path = os.path.join(cpuidle, state, "time")
                    usage_path = os.path.join(cpuidle, state, "usage")
                if os.path.exists(time_path):
                    try:
                        time_us = int(read_file(time_path))
                    except ValueError:
                        pass
                if os.path.exists(usage_path):
                    try:
                        usage = int(read_file(usage_path))
                    except ValueError:
                        pass
                totals = states.setdefault(state, [name, 0, 0])
                totals[1] += time_us
                totals[2] += usage
        self.cpu_cstates_s2idle = s2idle_counters
        return states

    def capture_cpu_cstates(self):
        """Capture the C-state residency of the CPUs

        The counters are read before the system suspends so that the
        time spent in each C-state during the sleep cycle can be worked
        out from the difference.
        """
        self.cpu_cstates = self._read_cpuidle_states()
        source = "suspend" if self.cpu_cstates_s2idle else "runtime"
        debug_str = f"C-state ({source} counters)|Name|Time (us)|Entries\n"
        for state in sorted(self.cpu_cstates, key=_cpuidle_state_index):
            name, time_us, usage = self.cpu_cstates[state]
            debug_str += f"{state}|{name}|{time_us}|{usage}\n"
        self.db.record_debug(debug_str)

    def capture_cpu_cstates_delta(self):
        """Report the C-states the CPUs spent the sleep cycle in"""
        before = getattr(self, "cpu_cstates", None)
        if not before:
            return
        after = self._read_cpuidle_states()
        deepest = None
        debug_str = "C-state residency during the cycle\n"
        for state in sorted(after, key=_cpuidle_state_index):
            name, time_us, usage = after[state]
            _name, old_time, old_usage = before.get(state, (name, 0, 0))
            delta_time = time_us - old_time
            delta_usage = usage - old_usage
            if delta_time <= 0 and delta_usage <= 0:
                continue
            debug_str += (
                f"│ {name}: {delta_time / 10**6:.2f}s "
                f"({delta_usage} entries)\n"
            )
            deepest = name
        if deepest is None:
            self.db.record_debug(
                "No C-state residency change during the cycle"
            )
        else:
            self.db.record_debug(debug_str)
            self.db.record_cycle_data(
                f"Deepest C-state entered: {deepest}", "💤"
            )
        self.cpu_cstates = after

    def _read_pci_power_states(self):
        """Read the power state of all PCI devices"""
        states = {}
        for device in self.pyudev.list_devices(subsystem="pci"):
            slot = device.properties.get("PCI_SLOT_NAME")
            if not slot:
                continue
            p = os.path.join(device.sys_path, "power", "runtime_status")
            runtime_status = read_file(p) if os.path.exists(p) else ""
            p = os.path.join(device.sys_path, "d3cold_allowed")
            d3cold_allowed = read_file(p) if os.path.exists(p) else ""
            driver = device.properties.get("DRIVER", "")
            states[slot] = (driver, runtime_status, d3cold_allowed)
        return states

    def capture_pci_power_state(self):
        """Capture the power state of PCI devices

        Devices that are runtime suspended with D3cold allowed will be put
        into D3cold during s2idle.  Some device firmware is unable to
        resume from that state, so note which devices will spend the sleep
        cycle in D3cold.
        """
        states = self._read_pci_power_states()
        debug_str = "PCI Slot|Driver|Runtime status|D3cold allowed\n"
        for slot in sorted(states):
            driver, runtime_status, d3cold_allowed = states[slot]
            debug_str += f"{slot}|{driver}|{runtime_status}|{d3cold_allowed}\n"
        self.db.record_debug(debug_str)
        self.db.record_pci_power_state(states)
        for slot in sorted(states):
            driver, runtime_status, d3cold_allowed = states[slot]
            if (
                driver
                and runtime_status == "suspended"
                and d3cold_allowed == "1"
            ):
                self.db.record_cycle_data(
                    f"{slot} ({driver}) is runtime suspended with D3cold "
                    "allowed and will enter D3cold during s2idle",
                    "💤",
                )
        self.pci_power_state = states

    def capture_pci_power_state_change(self):
        """Compare the PCI device power states after the resume

        The pre-suspend states come from memory, or from the database when
        this runs in a different process, e.g. from the systemd sleep
        hook.
        """
        before = self.pci_power_state
        if not before:
            before = self.db.get_pci_power_state()
        if not before:
            return
        states = self._read_pci_power_states()
        debug_str = "PCI Slot|Driver|Runtime status|D3cold allowed\n"
        for slot in sorted(states):
            driver, runtime_status, d3cold_allowed = states[slot]
            debug_str += f"{slot}|{driver}|{runtime_status}|{d3cold_allowed}\n"
        self.db.record_debug(debug_str)
        for slot in sorted(states):
            driver, runtime_status, d3cold_allowed = states[slot]
            if slot not in before:
                continue
            _old_driver, old_status, old_d3cold = before[slot]
            if old_status != runtime_status:
                self.db.record_debug(
                    f"{slot} runtime status changed: "
                    f"{old_status} -> {runtime_status}"
                )
            # devices that were runtime suspended before the suspend spend
            # the cycle in D3cold.  They are not expected to be active
            # again right after the resume, so only note that they made
            # the round trip.
            if old_status == "suspended" and old_d3cold == "1":
                self.db.record_cycle_data(
                    f"{slot} ({driver}) entered D3cold during s2idle",
                    "💤",
                )
        self.pci_power_state = states

    def capture_command_line(self):
        """Capture the kernel command line to debug"""
        self.db.record_debug(f"/proc/cmdline: {get_kernel_command_line()}")

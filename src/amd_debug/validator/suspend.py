# SPDX-License-Identifier: MIT

"""
This module contains the suspend control helpers for the sleep validator.

These are the functions that put the system to sleep and wake it back up.
"""

import math
import os
import random
import time
from datetime import datetime, timedelta

from amd_debug.validator_headers import Headers
from amd_debug.common import print_color, run_countdown


class SuspendHelpers:
    """Mixin providing the suspend control helpers for the sleep validator"""

    def program_wakealarm(self):
        """Program the RTC wakealarm to wake the system after the requested duration"""
        wakealarm = None
        for device in self.pyudev.list_devices(subsystem="rtc"):
            target = os.path.join(device.sys_path, "wakealarm")
            if os.path.exists(target):
                wakealarm = target
                break
        if wakealarm:
            with open(wakealarm, "w", encoding="utf-8") as w:
                w.write("0")
            with open(wakealarm, "w", encoding="utf-8") as w:
                w.write("+%s\n" % self.requested_duration)
        else:
            print_color("No RTC device found, please manually wake system", "🚦")

    def toggle_nvidia(self, value):
        """Write to the NVIDIA suspend interface

        The NVIDIA systemd units notify the driver of the suspend and
        resume events themselves, so if they are enabled the tool must not
        do it as well or the driver will be told about the event twice.
        """
        p = os.path.join("/", "proc", "driver", "nvidia", "suspend")
        if not os.path.exists(p):
            return True
        fd = os.open(p, os.O_WRONLY | os.O_SYNC)
        try:
            os.write(fd, value)
        except OSError as e:
            self.db.record_cycle_data(f"Failed to set {value} in NVIDIA {e}", "❌")
            return False
        finally:
            os.close(fd)
        self.db.record_debug(f"Wrote {value} to NVIDIA driver")
        return True

    def suspend_system(self):
        """Suspend the system using the dbus or sysfs interface"""

        def get_wakeup_count():
            """Get the wakeup count"""
            p = os.path.join("/", "sys", "power", "wakeup_count")
            if not os.path.exists(p):
                return 0
            try:
                with open(p, "r", encoding="utf-8") as r:
                    return int(r.read())
            except OSError:
                return 0

        if self.logind:
            try:
                import dbus
            except ImportError:
                self.db.record_cycle_data("Missing dbus", "❌")
                return False
            try:
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
        else:
            if not self.toggle_nvidia(b"suspend"):
                return False
            old = get_wakeup_count()
            p = os.path.join("/", "sys", "power", "state")
            fd = os.open(p, os.O_WRONLY | os.O_SYNC)
            try:
                os.write(fd, b"mem")
            except OSError as e:
                new = get_wakeup_count()
                self.db.record_cycle_data(
                    f"Failed to set suspend state ({old} -> {new}): {e}", "❌"
                )
                return False
            finally:
                os.close(fd)
            if not self.toggle_nvidia(b"resume"):
                return False
            return True

    def unlock_session(self):
        """Unlock the session using logind"""
        if self.logind:
            try:
                import dbus
            except ImportError:
                self.db.record_cycle_data("Missing dbus", "❌")
                return False
            try:
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
        min_duration = 4
        if not count:
            return True

        if logind:
            self.logind = True

        if rand:
            if duration <= min_duration:
                print_color(f"Invalid max duration {duration}", "❌")
                self.db.sync()
                self.report_cycle()
                return False
            print_color(
                f"Running {count} cycle random test with min duration of {min_duration}s, max duration of {duration}s and a max wait of {wait}s",
                "🗣️",
            )
        elif count > 1:
            length = timedelta(seconds=(duration + wait) * count)
            print_color(
                f"Running {count} cycles (Test finish expected @ {datetime.now() + length})".format(),
                "🗣️",
            )
        for i in range(1, count + 1):
            if rand:
                self.requested_duration = random.randint(min_duration, duration)
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
                "🗣️",
            )
            self.program_wakealarm()
            if not self.suspend_system():
                self.db.sync()
                self.report_cycle()
                return False
            run_countdown("Collecting data", math.ceil(requested_wait / 2))
            self.post()
            self.db.sync()
            self.report_cycle()
        self.unlock_session()
        return True

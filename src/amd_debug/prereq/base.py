# SPDX-License-Identifier: MIT

"""
This module contains the base class for the s2idle prerequisite validator.

The checks that matter for s2idle debugging differ between CPU vendors, so
the validator is split into a vendor independent base class and vendor
specific subclasses.  The vendor independent checks are further split into
mixins based on the area of the system they examine.
"""

import logging
import os
from datetime import datetime

import pyudev

from amd_debug.wake import WakeIRQ
from amd_debug.display import Display
from amd_debug.kernel import get_kernel_log, redact_sensitive
from amd_debug.common import (
    clear_temporary_message,
    get_distro,
    is_root,
    print_color,
    print_temporary_message,
    read_file,
    AmdTool,
)
from amd_debug.database import SleepDatabase
from amd_debug.cpu import parse_cpuinfo, CpuInfo
from amd_debug.prereq.acpi import AcpiChecks
from amd_debug.prereq.devices import DeviceChecks
from amd_debug.prereq.system import SystemChecks
from amd_debug.prereq.nvidia import NvidiaChecks
from amd_debug.prereq.base_headers import Headers


class PrerequisiteValidator(
    AcpiChecks, DeviceChecks, SystemChecks, NvidiaChecks, AmdTool
):
    """Base class to validate the prerequisites for s2idle

    Subclasses provide the vendor specific checks.
    """

    def __init__(self, tool_debug):
        log_prefix = "s2idle" if tool_debug else None
        super().__init__(log_prefix)

        self.kernel_log = get_kernel_log()
        if not is_root():
            raise PermissionError("not root user")
        self.cpu_info = CpuInfo()
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

    def get_cpu_vendor(self) -> str:
        """Fetch information about the CPU vendor"""
        p = os.path.join("/", "proc", "cpuinfo")
        try:
            contents = read_file(p)
        except (FileNotFoundError, PermissionError):
            contents = ""
        self.cpu_info = parse_cpuinfo(contents)
        self.cpu_family = self.cpu_info.family
        self.cpu_model = self.cpu_info.model
        self.cpu_model_string = self.cpu_info.model_string or None
        if self.cpu_family and self.cpu_model and self.cpu_model_string:
            self.db.record_prereq(
                f"{self.cpu_model_string} "
                f"(family {self.cpu_family:x} model {self.cpu_model:x})",
                "💻",
            )
        return self.cpu_info.vendor

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
                    self.db.record_prereq(f"NVIDIA GPU {f} not readable", "👀")
        return True

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

    def vendor_checks(self) -> list:
        """Return the list of vendor specific checks to run"""
        return []

    def vendor_info(self) -> list:
        """Return the list of vendor specific information to capture"""
        return []

    def run(self):
        """Run the prerequisites check"""
        msg = "Checking prerequisites, please wait"
        print_temporary_message(msg)
        info = [
            self.capture_smbios,
            self.capture_kernel_version,
            self.capture_battery,
            self.capture_logind,
            self.capture_pci_acpi,
            self.capture_edid,
            self.capture_nvidia,
            self.capture_nvidia_power,
            self.capture_cstates,
        ]
        checks = []

        self.get_cpu_vendor()
        info += self.vendor_info()
        checks += self.vendor_checks()

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
            self.check_nvidia_s0ix,
            self.check_nvidia_video_memory,
            self.check_nvidia_suspend_units,
            self.check_nvidia_powerd,
        ]

        for i in info:
            i()

        result = True
        for check in checks:
            if not check():
                result = False
        if not result:
            self.db.record_prereq(Headers.BrokenPrerequisites, "🚫")
            self.db.record_debug(redact_sensitive(self.kernel_log.get_full_log()))
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
            return
        print_color(Headers.ExplanationReport, "🗣️")
        for item in self.failures:
            item.get_failure()

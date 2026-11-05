# SPDX-License-Identifier: MIT

"""
This module contains the sleep validator.

The validator captures the state of the system before it suspends and after
it resumes, and then analyses that data to work out what happened.
"""

import os
import re
from datetime import datetime

from packaging import version
from pyudev import Context

from amd_debug.sleep_report import SleepReport
from amd_debug.database import SleepDatabase
from amd_debug.battery import Batteries
from amd_debug.power_rails import PowerRails
from amd_debug.acpi import AcpicaTracer
from amd_debug.common import (
    read_file,
    check_lockdown,
    print_color,
    AmdTool,
)
from amd_debug.kernel import get_kernel_log
from amd_debug.failures import (
    IommuPageFault,
    RtcAlarmWrong,
)
from amd_debug.validator.capture import CaptureHelpers
from amd_debug.validator.analysis import AnalysisHelpers
from amd_debug.validator.suspend import SuspendHelpers
from amd_debug.validator.intel import IntelCaptureHelpers
from amd_debug.validator_headers import Headers


def soc_needs_irq1_wa(family, model, smu_version):
    """Check if the SoC needs the IRQ1 workaround"""
    if family == 0x17:
        if model in [0x68, 0x60]:
            return True
    elif family == 0x19:
        if model == 0x50:
            return version.parse(smu_version) < version.parse("64.66.0")
    return False


def toggle_pm_debug(enable):
    """Enable or disable pm_debug_messages"""
    pm_debug_messages = os.path.join("/", "sys", "power", "pm_debug_messages")
    with open(pm_debug_messages, "w", encoding="utf-8") as w:
        w.write("1" if enable else "0")


def pm_debugging(func):
    """Decorator to enable pm_debug_messages"""

    def runner(*args, **kwargs):
        toggle_pm_debug(True)
        ret = func(*args, **kwargs)
        toggle_pm_debug(False)

        return ret

    return runner


class SleepValidator(
    CaptureHelpers, AnalysisHelpers, SuspendHelpers, IntelCaptureHelpers, AmdTool
):
    """Class to validate the sleep state"""

    def __init__(self, tool_debug, bios_debug):
        log_prefix = "s2idle" if tool_debug else None
        super().__init__(log_prefix)

        self.pyudev = Context()

        self.kernel_log = get_kernel_log()
        self.db = SleepDatabase()
        self.batteries = Batteries()
        self.power_rails = PowerRails()
        self.acpica = AcpicaTracer()
        self.bios_debug = bios_debug
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
        self.display_debug = tool_debug
        self.lockdown = check_lockdown()
        self.logind = False
        self.upep = False
        self.cycle_count = 0
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
        self.pci_power_state = {}
        self.cpu_cstates = {}
        self.cpu_cstates_s2idle = False
        self.intel_cstates_before = None
        self.pmc_core = None
        self.s0ix_residency = 0
        self.s0ix_residency_before = None
        self.s0ix_substates_before = {}

    def needs_irq1_workaround(self) -> bool:
        """Check if the platform needs the IRQ1 workaround"""
        return soc_needs_irq1_wa(self.cpu_family, self.cpu_model, self.smu_version)

    def capture_hw_sleep(self) -> bool:
        """Check for hardware sleep state"""
        p = os.path.join("/", "sys", "power", "suspend_stats", "last_hw_sleep")
        if os.path.exists(p):
            self.hw_sleep_duration = int(read_file(p)) / 10**6

        smu_fw_info_path = os.path.join(
            "/", "sys", "kernel", "debug", "amd_pmc", "smu_fw_info"
        )
        if os.path.exists(smu_fw_info_path):
            self.db.record_debug_file(smu_fw_info_path)

        if not os.path.exists(p) and not self.hw_sleep_duration:
            try:
                val = read_file(p)
                for line in val.split("\n"):
                    if "Last S0i3 Status" in line:
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
                self.db.record_debug(
                    f"HW sleep statistics file {smu_fw_info_path} is missing"
                )
        if not self.hw_sleep_duration and self.s0ix_residency:
            # on Intel platforms the SLP_S0 residency counter tracks how
            # long the hardware spent in the low power state when the
            # suspend stats interface is unavailable
            self.hw_sleep_duration = self.s0ix_residency
            self.db.record_debug(
                "Using SLP_S0 residency as hardware sleep time: "
                f"{self.s0ix_residency}"
            )
        if not self.hw_sleep_duration:
            self.db.record_cycle_data("Did not reach hardware sleep state", "❌")
        return self.hw_sleep_duration > 0

    def post(self):
        """Post-process the suspend test results"""
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

        checks = [
            self.capture_wakeup_irq_data,
            self.analyze_kernel_log,
            self.check_gpes,
            self.capture_lid,
            self.check_rtc_cmos,
            self.capture_intel_s0ix_residency,
            self.capture_hw_sleep,
            self.capture_intel_substate_delta,
            self.capture_intel_s0ix_blockers,
            self.capture_intel_cstates_delta,
            self.capture_cpu_cstates_delta,
            self.capture_pci_power_state_change,
            self.capture_battery,
            self.capture_power_rails,
            self.capture_amdgpu_ips_status,
            self.capture_thermal,
            self.capture_input_wakeup_count,
            self.acpica.restore,
        ]
        for check in checks:
            check()
        self.db.record_cycle(
            self.requested_duration,
            ",".join(str(gpio) for gpio in self.active_gpios),
            ",".join(str(irq) for irq in self.wakeup_irqs),
            int(self.kernel_duration),
            int(self.hw_sleep_duration),
        )

    def prep(self):
        """Prepare the system for suspend testing"""
        self.last_suspend = datetime.now()
        self.kernel_log.seek_tail(self.last_suspend)
        self.db.start_cycle(self.last_suspend)
        self.kernel_duration = 0
        self.hw_sleep_duration = 0
        self.capture_battery()
        self.capture_power_rails()
        self.check_gpes()
        self.capture_lid()
        self.capture_command_line()
        self.capture_wake_sources()
        self.capture_running_compositors()
        self.capture_power_profile()
        self.capture_pci_power_state()
        self.capture_cpu_cstates()
        self.capture_intel_cstates()
        self.capture_amdgpu_ips_status()
        self.capture_thermal()
        self.capture_input_wakeup_count()
        self.capture_intel_s0ix()
        if self.bios_debug:
            self.acpica.trace_bios()
        else:
            self.acpica.trace_notify()
        self.db.record_cycle()

    def systemd_pre_hook(self):
        """Called before suspend"""
        self.prep()
        self.db.sync()
        toggle_pm_debug(True)

    def systemd_post_hook(self):
        """Called after resume"""
        toggle_pm_debug(False)
        t0 = self.db.get_last_cycle()
        self.last_suspend = datetime.strptime(str(t0[0]), "%Y%m%d%H%M%S")
        self.kernel_log.seek_tail(self.last_suspend)
        self.db.start_cycle(self.last_suspend)
        self.post()
        self.db.sync()

    def report_cycle(self):
        """Report the results of the last cycle"""
        print_color(Headers.LastCycleResults, "🗣️")

        self.analyze_duration(
            self.last_suspend,
            datetime.now(),
            self.requested_duration,
            self.kernel_duration,
            self.hw_sleep_duration,
        )

        app = SleepReport(
            since=self.last_suspend,
            until=self.last_suspend,
            fname=None,
            fmt="stdout",
            tool_debug=self.display_debug,
            report_debug=False,
        )
        app.run(inc_prereq=False)
        return

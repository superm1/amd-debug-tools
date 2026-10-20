# SPDX-License-Identifier: MIT

"""
This module contains the analysis helpers for the sleep validator.

These are the functions that examine the data captured during a sleep cycle
to work out what happened.
"""

import re
from datetime import timedelta

from amd_debug.validator_headers import Headers
from amd_debug.common import print_color, BIT
from amd_debug.kernel import sscanf_bios_args
from amd_debug.failures import (
    AcpiBiosError,
    IommuPageFault,
    Irq1Workaround,
    LowHardwareSleepResidency,
    SpuriousWakeup,
)


class AnalysisHelpers:
    """Mixin providing the analysis helpers for the sleep validator"""

    def _analyze_kernel_log_line(self, line, priority):
        bios_args = sscanf_bios_args(line)
        if bios_args:
            if isinstance(bios_args, str):
                line = bios_args
                priority = 7
            else:
                return
        elif "Timekeeping suspended for" in line:
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
        # AMD-Vi: Event logged [IO_PAGE_FAULT device=0000:00:0c.0 domain=0x0000 address=0x7e800000 flags=0x0050]
        elif "Event logged [IO_PAGE_FAULT" in line:
            # get the device from string
            device = re.search(r"device=(.*?) domain", line)
            if device:
                device = device.group(1)
                if device not in self.page_faults:
                    self.page_faults += [device]

        # evmisc-0132 ev_queue_notify_reques: Dispatching Notify on [UBTC] (Device) Value 0x80 (Status Change) Node 0000000080144eee
        if "Dispatching Notify on" in line:
            # add device without the [] to notify_devices if it's not already there
            device = re.search(r"\[(.*?)\]", line)
            if device:
                device = device.group(1)
                if device not in self.notify_devices:
                    self.notify_devices += [device]
            priority = 7

        self.db.record_debug(line, priority)

    def analyze_kernel_log(self):
        """Analyze one of the lines from the kernel log"""
        self.kernel_log.process_callback(self._analyze_kernel_log_line)

        if self.cycle_count:
            self.db.record_cycle_data(
                f"Hardware sleep cycle count: {self.cycle_count}",
                "💤",
            )
        if self.wakeup_irqs:
            if 1 in self.wakeup_irqs and self.needs_irq1_workaround():
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

    def needs_irq1_workaround(self) -> bool:
        """Check if the platform needs the IRQ1 workaround

        This is only relevant on AMD platforms, so the base
        implementation always returns False.
        """
        return False

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

# SPDX-License-Identifier: MIT

"""
This module contains the Intel specific prerequisites for s2idle.
"""

import os

from amd_debug.common import read_file
from amd_debug.intel import (
    get_dmc_firmware_status,
    get_intel_graphics_driver,
    get_lps0_disabled,
    intel_pmc_core_loaded,
    IntelPmcCore,
    parse_substate_requirements,
)
from amd_debug.prereq.base import PrerequisiteValidator
from amd_debug.failures import (
    IntelDmcFirmwareMissing,
    MissingIntelGraphics,
    MissingIntelPmcCore,
    S0ixNotReached,
)


class IntelPrerequisiteValidator(PrerequisiteValidator):
    """Class to validate the prerequisites for s2idle on Intel platforms"""

    def __init__(self, tool_debug):
        super().__init__(tool_debug)
        self.pmc_core = IntelPmcCore()

    def check_intel_pmc_core(self):
        """Check that the intel_pmc_core driver is loaded

        Without this driver the platform can't be put into the deeper
        S0ix substates, so it is required for low power s2idle.
        """
        if not intel_pmc_core_loaded():
            self.db.record_prereq(
                "Intel PMC core driver `intel_pmc_core` not loaded", "❌"
            )
            self.failures += [MissingIntelPmcCore()]
            return False
        self.db.record_prereq("Intel PMC core driver `intel_pmc_core` loaded", "✅")
        return True

    def check_intel_graphics(self):
        """Check that an Intel graphics driver is in use

        The integrated GPU is needed to power down the display, and the
        display firmware (DMC) is needed to enter the deeper power states.
        """
        driver = get_intel_graphics_driver()
        if not driver:
            self.db.record_prereq("Intel graphics driver not found", "❌")
            self.failures += [MissingIntelGraphics()]
            return False
        self.db.record_prereq(f"Intel graphics driver `{driver}` loaded", "✅")
        return True

    def check_intel_dmc(self):
        """Check that the Intel display firmware (DMC) is loaded

        The i915 driver always exposes the DMC status through debugfs,
        and the xe driver exposes the same interface since kernel 6.14
        when it is built with display support.
        """
        status = get_dmc_firmware_status()
        if not status:
            self.db.record_prereq(
                "Unable to determine Intel display firmware status", "🚦"
            )
            return True
        loaded = status.get("fw loaded", "")
        if loaded == "yes":
            # newer kernels report the version in the 'version' key,
            # older kernels put it in 'DMC firmware'
            firmware = status.get("DMC firmware", "") or status.get("version", "")
            message = "Intel display firmware loaded"
            if firmware:
                message += f" ({firmware})"
            self.db.record_prereq(message, "✅")
            return True
        self.db.record_prereq("Intel display firmware not loaded", "❌")
        self.failures += [IntelDmcFirmwareMissing(loaded)]
        return False

    def check_lps0_interface(self):
        """Check that the LPS0 device interface is in use

        The `sleep_no_lps0` module parameter disables the special LPS0
        device interface, which prevents the platform from entering the
        low power S0 idle state.
        """
        lps0_disabled = get_lps0_disabled()
        if lps0_disabled is None:
            self.db.record_prereq(
                "Unable to determine the LPS0 device interface status", "🚦"
            )
            return True
        if lps0_disabled:
            self.db.record_prereq(
                "LPS0 device interface disabled (sleep_no_lps0)", "❌"
            )
            self.failures += [S0ixNotReached("LPS0 device interface disabled")]
            return False
        self.db.record_prereq("LPS0 device interface enabled", "✅")
        return True

    def capture_pmc_core(self):
        """Capture the intel_pmc_core data"""
        if not self.pmc_core.available:
            self.db.record_debug("Intel PMC core debugfs is not available")
            return
        self.pmc_core.capture()
        if self.pmc_core.slp_s0_residency is not None:
            self.db.record_debug(
                f"SLP_S0 residency: {self.pmc_core.slp_s0_residency} usec"
            )
        if self.pmc_core.substate_residencies:
            debug_str = "S0ix substate residency\n"
            for name, value in self.pmc_core.substate_residencies.items():
                debug_str += f"│ {name}: {value}\n"
            self.db.record_debug(debug_str)
        if self.pmc_core.substate_requirements:
            blockers = parse_substate_requirements(self.pmc_core.substate_requirements)
            if blockers:
                debug_str = "S0ix substate blockers\n"
                for element, required in blockers:
                    debug_str += f"│ {element}: {', '.join(required)}\n"
                self.db.record_debug(debug_str)
        if self.pmc_core.substate_status_registers:
            self.db.record_debug(
                "S0ix substate status registers\n"
                + self.pmc_core.substate_status_registers
            )
        if self.pmc_core.substate_live_status_registers:
            self.db.record_debug(
                "S0ix substate live status registers\n"
                + self.pmc_core.substate_live_status_registers
            )

    def capture_intel_graphics_firmware(self):
        """Capture the Intel graphics firmware information"""
        status = get_dmc_firmware_status()
        if not status:
            return
        debug_str = "Intel graphics firmware\n"
        for key, value in status.items():
            debug_str += f"│ {key}: {value}\n"
        self.db.record_debug(debug_str)

    def capture_intel_cpuidle(self):
        """Capture the CPU idle states used by the platform"""
        base = os.path.join("/", "sys", "devices", "system", "cpu", "cpu0", "cpuidle")
        if not os.path.isdir(base):
            return
        debug_str = "CPU idle states\n"
        for state in sorted(os.listdir(base)):
            if not state.startswith("state"):
                continue
            name = ""
            latency = ""
            p = os.path.join(base, state, "name")
            if os.path.exists(p):
                name = read_file(p)
            p = os.path.join(base, state, "latency")
            if os.path.exists(p):
                latency = read_file(p)
            debug_str += f"│ {state}: {name} (latency {latency} usec)\n"
        self.db.record_debug(debug_str)

    def vendor_info(self) -> list:
        """Return the list of vendor specific information to capture"""
        return [
            self.capture_pmc_core,
            self.capture_intel_graphics_firmware,
            self.capture_intel_cpuidle,
        ]

    def vendor_checks(self) -> list:
        """Return the list of vendor specific checks to run"""
        return [
            self.check_intel_pmc_core,
            self.check_intel_graphics,
            self.check_intel_dmc,
            self.check_lps0_interface,
            self.check_sleep_mode,
            self.check_cpu,
        ]

    def check_cpu(self):
        """Check if the CPU is supported

        Intel platforms that support Low Power S0 Idle all use family 6,
        so there isn't a per-model list to check.
        """
        if self.cpu_family is None:
            self.db.record_prereq("Unable to determine CPU family", "🚦")
            return True
        if self.cpu_family != 6:
            self.db.record_prereq(
                f"CPU family {self.cpu_family:x} is not an Intel family", "🚦"
            )
            return True
        return True

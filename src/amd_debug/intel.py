# SPDX-License-Identifier: MIT

"""
This module contains support for Intel platforms.

Intel platforms implement the ACPI Low Power S0 Idle (LPS0) interface,
and the s2idle analysis relies on the following interfaces:

  * ``/sys/kernel/debug/pmc_core/`` - debugfs directory for the PMC core
    driver, which exposes the S0ix residency counters and the low power
    mode (substate) information.
  * ``/sys/kernel/debug/dri/<card>/i915_dmc_info`` - display firmware
    (DMC) status for Intel graphics.
  * ``/sys/module/intel_pmc_core/parameters/`` - module parameters.
  * ``/sys/module/acpi_x86/parameters/sleep_no_lps0`` - whether the kernel
    was told not to use the LPS0 device interface.
"""

import os
import re
from typing import Optional

from amd_debug.common import read_file

# The debugfs directory used by the intel_pmc_core driver
PMC_CORE_DEBUGFS = os.path.join("/", "sys", "kernel", "debug", "pmc_core")

# The name of the intel_pmc_core driver
PMC_CORE_DRIVER = "intel_pmc_core"

# The name of the module that provides the x86 ACPI LPS0 interface
ACPI_X86_MODULE = "acpi_x86"

# The name of the x86 ACPI module (for older kernels)
ACPI_MODULE = "acpi"

# The Intel graphics drivers that can be in use
INTEL_GRAPHICS_DRIVERS = ["i915", "xe"]

# The S0ix substate names used by the intel_pmc_core driver
S0IX_SUBSTATES = [
    "S0i2.0",
    "S0i2.1",
    "S0i2.2",
    "S0i3.0",
    "S0i3.1",
    "S0i3.2",
    "S0i3.3",
    "S0i3.4",
]

# The counter step used by the intel_pmc_core driver for the SLP_S0
# residency counter.  It is 122us for most platforms and 30.5us for
# Alder Lake PCH, which is handled by the driver itself.
PMC_CORE_SLP_S0_RESIDENCY_STEP_US = 122


class IntelPmcCore:
    """Interface to the intel_pmc_core driver"""

    def __init__(self):
        self.available = os.path.isdir(PMC_CORE_DEBUGFS)
        self.slp_s0_residency = None
        self.substate_residencies = {}
        self.substate_requirements = ""
        self.substate_status_registers = ""
        self.substate_live_status_registers = ""

    def _read(self, name):
        """Read a file from the pmc_core debugfs directory"""
        p = os.path.join(PMC_CORE_DEBUGFS, name)
        if not os.path.exists(p):
            return None
        try:
            return read_file(p)
        except (PermissionError, OSError):
            return None

    def read_slp_s0_residency(self):
        """Read the SLP_S0 (S0ix) residency counter

        The counter is reported in microseconds.
        """
        contents = self._read("slp_s0_residency_usec")
        if contents is None:
            return None
        try:
            return int(contents.strip())
        except ValueError:
            return None

    def read_substate_residencies(self):
        """Read the S0ix substate residency counters

        The file has the following format::

            pmc0        Substate     Residency
                   S0i2.0              0
                   S0i2.1              0
        """
        contents = self._read("substate_residencies")
        if contents is None:
            return {}
        return parse_substate_residencies(contents)

    def read_substate_requirements(self):
        """Read the S0ix substate requirements"""
        contents = self._read("substate_requirements")
        if contents is None:
            return ""
        return contents

    def read_substate_status_registers(self):
        """Read the S0ix substate status registers"""
        contents = self._read("substate_status_registers")
        if contents is None:
            return ""
        return contents

    def read_substate_live_status_registers(self):
        """Read the S0ix substate live status registers"""
        contents = self._read("substate_live_status_registers")
        if contents is None:
            return ""
        return contents

    def read_package_cstates(self):
        """Read the package C-state residency counters

        The file has the following format::

            Package C2 : 743538
            Package C3 : 1250

        The counters are cumulative and report microseconds.
        """
        contents = self._read("package_cstate_show")
        if contents is None:
            return {}
        return parse_counter_file(contents)

    def read_core_cstates(self):
        """Read the core C-state residency counters

        The counters are cumulative.  They are only exposed by older
        generations of the PMC.
        """
        contents = self._read("core_residency")
        if contents is None:
            return {}
        return parse_counter_file(contents)

    def read_die_c6_residency(self):
        """Read the die C6 residency counter in microseconds

        The die C6 state is the tile based successor of the package C6
        state, so this is what modern SoCs report instead of the
        package C6 counter.
        """
        contents = self._read("die_c6_us_show")
        if contents is None:
            return None
        try:
            return int(contents.strip())
        except ValueError:
            return None

    def capture(self):
        """Capture all of the available PMC core data"""
        self.slp_s0_residency = self.read_slp_s0_residency()
        self.substate_residencies = self.read_substate_residencies()
        self.substate_requirements = self.read_substate_requirements()
        self.substate_status_registers = self.read_substate_status_registers()
        self.substate_live_status_registers = self.read_substate_live_status_registers()


def parse_counter_file(contents: str) -> dict:
    """Parse a ``Name: value`` counter file into a dict"""
    counters = {}
    for line in contents.split("\n"):
        if ":" not in line:
            continue
        key, _sep, value = line.partition(":")
        try:
            counters[key.strip()] = int(value.strip())
        except ValueError:
            continue
    return counters


def parse_substate_requirements(contents: str) -> list:
    """Parse the S0ix substate requirements into a list of blockers

    Each line of the requirements file has the following format::

        pmc0:                    OPI                     |         |    Required

    The name of the element is followed by the substate columns and
    finally the status.  Elements that are not required for any of the
    enabled substates are not reported at all, so any element that shows
    up in the file is a potential blocker.
    """
    blockers = []
    for line in contents.split("\n"):
        if "|" not in line:
            continue
        if line.strip().startswith("Element"):
            continue
        parts = line.split("|")
        if len(parts) < 2:
            continue
        element = parts[0].strip()
        # strip the leading "pmcN: " prefix
        element = re.sub(r"^pmc\d+:\s*", "", element)
        if not element:
            continue
        # the requirement columns are the ones that say "Required"
        required = [p.strip() for p in parts[1:] if p.strip() == "Required"]
        if not required:
            continue
        blockers.append((element, required))
    return blockers


def parse_substate_residencies(contents: str) -> dict:
    """Parse the S0ix substate residency counters

    The file has the following format::

        pmc0        Substate     Residency
                   S0i2.0              0
                   S0i2.1              0
    """
    residencies = {}
    for line in contents.split("\n"):
        parts = line.split()
        if len(parts) != 2:
            continue
        name = parts[0]
        if name not in S0IX_SUBSTATES:
            continue
        try:
            residencies[name] = int(parts[1])
        except ValueError:
            continue
    return residencies


def get_intel_graphics_driver() -> str:
    """Get the name of the Intel graphics driver in use, if any"""
    for driver in INTEL_GRAPHICS_DRIVERS:
        if os.path.exists(os.path.join("/", "sys", "module", driver)):
            return driver
    return ""


def get_dmc_info_path() -> str:
    """Get the path to the i915 DMC info debugfs file

    The file is exposed by the i915 driver on the first card, and by
    the xe driver since kernel 6.14 when it is built with display
    support.
    """
    base = os.path.join("/", "sys", "kernel", "debug", "dri")
    if not os.path.isdir(base):
        return ""
    for card in sorted(os.listdir(base)):
        p = os.path.join(base, card, "i915_dmc_info")
        if os.path.exists(p):
            return p
    return ""


def get_dmc_firmware_status() -> dict:
    """Get the status of the Intel display firmware (DMC)

    The i915_dmc_info file has the following format::

        DMC state:                 0000
        DMC firmware:              4.11
        ...
        fw loaded:                 yes
    """
    status = {}
    p = get_dmc_info_path()
    if not p:
        return status
    try:
        contents = read_file(p)
    except (PermissionError, OSError):
        return status
    for line in contents.split("\n"):
        if ":" not in line:
            continue
        key, _sep, value = line.partition(":")
        status[key.strip()] = value.strip()
    return status


def get_lps0_disabled() -> Optional[bool]:
    """Check if the kernel was told not to use the LPS0 device interface

    Returns None when the status can't be determined, e.g. when the
    kernel doesn't expose the module parameter or it can't be read.
    """
    for module in [ACPI_X86_MODULE, ACPI_MODULE]:
        p = os.path.join("/", "sys", "module", module, "parameters", "sleep_no_lps0")
        if not os.path.exists(p):
            continue
        try:
            return read_file(p) == "Y"
        except (PermissionError, OSError):
            return None
    return None


def intel_pmc_core_loaded() -> bool:
    """Check if the intel_pmc_core driver is loaded"""
    return os.path.exists(os.path.join("/", "sys", "module", PMC_CORE_DRIVER))

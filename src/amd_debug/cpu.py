# SPDX-License-Identifier: MIT

"""
This module contains CPU platform detection helpers.

s2idle is implemented by both AMD and Intel platforms, and the checks
that are meaningful for it differ substantially between the two vendors.
This module provides the vendor detection that decides which set of
prerequisites the tool applies.
"""

import os

from amd_debug.common import read_file

VENDOR_AMD = "AuthenticAMD"
VENDOR_INTEL = "GenuineIntel"


class CpuInfo:
    """Parsed information about the CPU of the running system"""

    def __init__(self, vendor="", family=None, model=None, model_string=""):
        self.vendor = vendor
        self.family = family
        self.model = model
        self.model_string = model_string

    @property
    def is_amd(self) -> bool:
        """True if the CPU is an AMD CPU"""
        return self.vendor == VENDOR_AMD

    @property
    def is_intel(self) -> bool:
        """True if the CPU is an Intel CPU"""
        return self.vendor == VENDOR_INTEL

    def __str__(self) -> str:
        """Human readable description of the CPU"""
        if self.model_string:
            return self.model_string
        return f"{self.vendor} family {self.family} model {self.model}"


def parse_cpuinfo(contents: str) -> CpuInfo:
    """Parse the contents of /proc/cpuinfo into a CpuInfo object

    Only the first processor block is considered, which is enough to
    determine the vendor, family, model and model name of the platform.
    """
    info = CpuInfo()
    seen_processor = False
    for line in contents.split("\n"):
        if not line.strip():
            # end of the first processor block
            if info.vendor or info.family is not None or info.model is not None:
                break
            continue
        if line.startswith("processor"):
            if seen_processor:
                # start of the second processor block, we're done
                break
            seen_processor = True
            continue
        if "vendor_id" in line:
            info.vendor = line.split()[-1]
        elif "cpu family" in line:
            info.family = int(line.split()[-1])
        elif "model name" in line:
            info.model_string = line.split(":")[-1].strip()
        elif "model" in line:
            info.model = int(line.split()[-1])
    return info


def get_cpu_info() -> CpuInfo:
    """Get information about the CPU of the running system"""
    p = os.path.join("/", "proc", "cpuinfo")
    try:
        contents = read_file(p)
    except (FileNotFoundError, PermissionError):
        return CpuInfo()
    return parse_cpuinfo(contents)

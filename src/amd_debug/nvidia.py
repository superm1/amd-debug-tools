# SPDX-License-Identifier: MIT

"""
This module contains support for the NVIDIA proprietary driver.

The NVIDIA proprietary driver exposes a number of interfaces that are
relevant for s2idle debugging:

  * ``/proc/driver/nvidia/version`` - driver version
  * ``/proc/driver/nvidia/gpus/<BDF>/power`` - power management state,
    including the S0ix power management status of the GPU
  * ``/proc/driver/nvidia/params`` - the module parameters in use
  * ``/proc/driver/nvidia/suspend`` - the suspend/resume notification
    interface used by the ``nvidia-suspend``/``nvidia-resume`` systemd units

The format of the ``power`` file is::

    Runtime D3 status:          Enabled
    Tegra iGPU Rail-Gating:     Disabled
    Video Memory:               Active

    GPU Hardware Support:
     Video Memory Self Refresh: Supported
     Video Memory Off:          Supported

    S0ix Power Management:
     Platform Support:          Supported
     Status:                    Enabled

    Notebook Dynamic Boost:     Not Supported
"""

import os
import re
import subprocess

from amd_debug.common import read_file

# Module parameter that enables S0ix support in the NVIDIA driver.
# /proc/driver/nvidia/params reports the parameter without the NVreg_
# prefix that it is registered with on the kernel command line
S0IX_PARAM = "EnableS0ixPowerManagement"

# The command line registration name, kept for drivers that report the
# parameter with the prefix
S0IX_PARAM_COMMAND_LINE = "NVreg_EnableS0ixPowerManagement"

# Module parameter that controls the video memory threshold used during
# S0ix suspend
S0IX_THRESHOLD_PARAM = "NVreg_S0ixPowerManagementVideoMemoryThreshold"

# Module parameter that enables runtime D3 (RTD3) power management
DYNAMIC_PM_PARAM = "NVreg_DynamicPowerManagement"

# NOTE: the NVreg_PreserveVideoMemoryAllocations module parameter is
# deliberately not checked by this tool.  Setting it to 1 makes the driver
# save and restore all of the video memory allocations, but on some hardware
# that prevents the GPU from entering D3cold.  The default of 0 is the
# correct value, so this tool neither checks nor enforces it.

# Systemd units shipped with the NVIDIA driver
SUSPEND_UNITS = [
    "nvidia-suspend.service",
    "nvidia-resume.service",
    "nvidia-hibernate.service",
]

# The daemon used to configure the NVIDIA driver power state on laptops
POWERD_UNIT = "nvidia-powerd.service"

# Values that the NVIDIA driver reports for the S0ix status
S0IX_ENABLED = "Enabled"
S0IX_DISABLED = "Disabled"
S0IX_SUPPORTED = "Supported"
S0IX_NOT_SUPPORTED = "Not Supported"

# Values that the NVIDIA driver reports for the video memory self refresh
# hardware support
GC6_SUPPORTED = "Supported"
GC6_NOT_SUPPORTED = "Not Supported"


class NvidiaGpu:
    """Information about a single NVIDIA GPU

    Each attribute corresponds to an entry in the
    /proc/driver/nvidia/gpus/<BDF>/power file.
    """

    # pylint: disable=too-many-instance-attributes
    def __init__(self, bdf):
        self.bdf = bdf
        self.runtime_d3 = ""
        self.video_memory = ""
        self.video_memory_off = ""
        self.dynamic_boost = ""
        # The video memory self refresh support of the GPU
        self.video_memory_self_refresh = ""
        # The S0ix platform support and the status of the S0ix support
        self.s0ix_platform_support = ""
        self.s0ix_status = ""

    @property
    def s0ix_supported(self) -> bool:
        """True if the platform supports S0ix for this GPU"""
        return self.s0ix_platform_support == S0IX_SUPPORTED

    @property
    def s0ix_enabled(self) -> bool:
        """True if S0ix power management is enabled for this GPU"""
        return self.s0ix_status == S0IX_ENABLED

    def __str__(self) -> str:
        """Human readable description of the GPU"""
        return f"NVIDIA GPU {self.bdf}"


def parse_power_file(contents: str) -> NvidiaGpu:
    """Parse the contents of /proc/driver/nvidia/gpus/<BDF>/power

    The file uses a mixture of indented and non-indented keys, so both
    need to be handled.
    """
    gpu = NvidiaGpu("")
    for line in contents.split("\n"):
        if ":" not in line:
            continue
        key, _sep, value = line.partition(":")
        value = value.strip()
        key = key.strip()
        if key == "Runtime D3 status":
            gpu.runtime_d3 = value
        elif key == "Video Memory":
            gpu.video_memory = value
        elif key == "Video Memory Self Refresh":
            gpu.video_memory_self_refresh = value
        elif key == "Video Memory Off":
            gpu.video_memory_off = value
        elif key == "Platform Support":
            gpu.s0ix_platform_support = value
        elif key == "Status":
            gpu.s0ix_status = value
        elif key == "Notebook Dynamic Boost":
            gpu.dynamic_boost = value
    return gpu


def get_nvidia_gpus() -> list:
    """Get information about all NVIDIA GPUs present in the system"""
    gpus = []
    base = os.path.join("/", "proc", "driver", "nvidia", "gpus")
    if not os.path.isdir(base):
        return gpus
    for bdf in sorted(os.listdir(base)):
        p = os.path.join(base, bdf, "power")
        if not os.path.exists(p):
            continue
        try:
            contents = read_file(p)
        except (PermissionError, FileNotFoundError, OSError):
            continue
        gpu = parse_power_file(contents)
        gpu.bdf = bdf
        gpus.append(gpu)
    return gpus


def get_module_params() -> dict:
    """Get the NVIDIA kernel module parameters in use

    The parameters are exposed in /proc/driver/nvidia/params as a list of
    ``Name: value`` entries.
    """
    params = {}
    p = os.path.join("/", "proc", "driver", "nvidia", "params")
    if not os.path.exists(p):
        return params
    try:
        contents = read_file(p)
    except (PermissionError, OSError):
        return params
    for line in contents.split("\n"):
        if ":" not in line:
            continue
        key, _sep, value = line.partition(":")
        params[key.strip()] = value.strip()
    return params


def get_s0ix_param() -> str:
    """Get the value of the S0ix module parameter, if it is set"""
    params = get_module_params()
    return params.get(S0IX_PARAM) or params.get(S0IX_PARAM_COMMAND_LINE, "")


def s0ix_param_enabled() -> bool:
    """True if the NVIDIA driver has S0ix power management enabled"""
    return get_s0ix_param() == "1"


def parse_module_param_value(contents: str, name: str) -> str:
    """Find the value of a module parameter in the params file contents

    The NVIDIA params file lists each parameter along with a description.
    The value appears in the form ``Name: value``.
    """
    pattern = re.compile(rf"^\s*{re.escape(name)}\s*:\s*(\S+)\s*$", re.MULTILINE)
    match = pattern.search(contents)
    if not match:
        return ""
    return match.group(1)


def get_driver_version() -> str:
    """Get the version of the NVIDIA driver in use"""
    p = os.path.join("/", "proc", "driver", "nvidia", "version")
    if not os.path.exists(p):
        return ""
    try:
        return read_file(p)
    except (PermissionError, OSError):
        return ""


def systemd_unit_installed(unit: str) -> bool:
    """Check if a systemd unit file is installed"""
    for base in [
        os.path.join("/", "usr", "lib", "systemd", "system"),
        os.path.join("/", "lib", "systemd", "system"),
        os.path.join("/", "etc", "systemd", "system"),
    ]:
        if os.path.exists(os.path.join(base, unit)):
            return True
    return False


def systemd_unit_enabled(unit: str) -> bool:
    """Check if a systemd unit is enabled"""
    try:
        result = subprocess.run(
            ["systemctl", "is-enabled", unit],
            check=False,
            capture_output=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False
    return result.returncode == 0


def suspend_units_enabled() -> bool:
    """Check if any NVIDIA suspend/resume systemd unit is installed and enabled"""
    for unit in SUSPEND_UNITS:
        if not systemd_unit_installed(unit):
            continue
        if systemd_unit_enabled(unit):
            return True
    return False

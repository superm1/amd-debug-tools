# SPDX-License-Identifier: MIT

"""
This module contains the NVIDIA proprietary driver specific prerequisites
for s2idle.

The NVIDIA driver has to be configured properly for the system to reach
the S0ix state during s2idle:

  * The ``NVreg_EnableS0ixPowerManagement`` module parameter has to be set
    so that the driver puts the GPU into self refresh mode during s2idle.
  * The GPU has to support video memory self refresh, otherwise the driver
    cannot power the GPU down during s2idle.
  * The systemd units that notify the driver of suspend/resume events have
    to be enabled so that the driver can save and restore its state.
"""

import logging
import os
import subprocess

from amd_debug.nvidia import (
    get_module_params,
    get_nvidia_gpus,
    get_s0ix_param,
    systemd_unit_enabled,
    systemd_unit_installed,
    POWERD_UNIT,
    S0IX_DISABLED,
    S0IX_ENABLED,
    S0IX_NOT_SUPPORTED,
    S0IX_PARAM,
    S0IX_SUPPORTED,
    SUSPEND_UNITS,
)
from amd_debug.failures import (
    NvidiaS0ixDisabled,
    NvidiaS0ixUnsupported,
    NvidiaSuspendUnitsMissing,
)


class NvidiaChecks:
    """Mixin providing the NVIDIA driver related prerequisite checks"""

    def _systemd_unit_enabled(self, unit: str) -> bool:
        """Check if a systemd unit is enabled"""
        return systemd_unit_enabled(unit)

    def _systemd_unit_exists(self, unit: str) -> bool:
        """Check if a systemd unit file is installed"""
        return systemd_unit_installed(unit)

    def check_nvidia_s0ix(self):
        """Check that the NVIDIA driver is configured for S0ix

        This only applies if an NVIDIA GPU is present and the platform
        supports S0ix.
        """
        gpus = get_nvidia_gpus()
        if not gpus:
            # No NVIDIA GPU, nothing to check
            return True

        # The module parameter is only meaningful if the platform supports
        # S0ix, so only report problems if the GPU says it is supported.
        platform_supported = any(gpu.s0ix_supported for gpu in gpus)
        if not platform_supported:
            self.db.record_prereq(
                "NVIDIA GPU present, but the platform does not support S0ix", "🚦"
            )
            return True

        param = get_s0ix_param()
        if not param:
            self.db.record_prereq(
                f"NVIDIA module parameter `{S0IX_PARAM}` is not set", "❌"
            )
            self.failures += [NvidiaS0ixDisabled()]
            return False
        if param != "1":
            self.db.record_prereq(
                f"NVIDIA module parameter `{S0IX_PARAM}` is set to {param}, "
                "it should be set to 1",
                "❌",
            )
            self.failures += [NvidiaS0ixDisabled()]
            return False
        self.db.record_prereq(
            f"NVIDIA module parameter `{S0IX_PARAM}` is enabled", "✅"
        )

        ret = True
        for gpu in gpus:
            if not gpu.s0ix_supported:
                self.db.record_prereq(
                    f"NVIDIA GPU {gpu.bdf} does not support S0ix", "🚦"
                )
                continue
            if gpu.s0ix_status == S0IX_ENABLED:
                self.db.record_prereq(
                    f"NVIDIA GPU {gpu.bdf} has S0ix power management enabled", "✅"
                )
            elif gpu.s0ix_status == S0IX_DISABLED:
                self.db.record_prereq(
                    f"NVIDIA GPU {gpu.bdf} has S0ix power management disabled", "❌"
                )
                self.failures += [NvidiaS0ixDisabled()]
                ret = False
            else:
                self.db.record_prereq(
                    f"NVIDIA GPU {gpu.bdf} S0ix status is {gpu.s0ix_status}", "🚦"
                )
        return ret

    def check_nvidia_video_memory(self):
        """Check that the NVIDIA GPU supports video memory self refresh

        Without video memory self refresh the GPU cannot be powered down
        during s2idle, which prevents the platform from reaching the S0ix
        state.
        """
        gpus = get_nvidia_gpus()
        if not gpus:
            return True
        for gpu in gpus:
            if not gpu.s0ix_supported:
                continue
            support = gpu.video_memory_self_refresh
            if support == S0IX_SUPPORTED:
                self.db.record_prereq(
                    f"NVIDIA GPU {gpu.bdf} supports video memory self refresh", "✅"
                )
            elif support == S0IX_NOT_SUPPORTED:
                self.db.record_prereq(
                    f"NVIDIA GPU {gpu.bdf} does not support video memory self "
                    "refresh, the GPU will stay powered on during s2idle",
                    "❌",
                )
                self.failures += [NvidiaS0ixUnsupported()]
                return False
            else:
                self.db.record_debug(
                    f"NVIDIA GPU {gpu.bdf} video memory self refresh support "
                    f"is unknown ({support})"
                )
        return True

    def check_nvidia_suspend_units(self):
        """Check that the NVIDIA suspend/resume systemd units are enabled

        The units are what notify the NVIDIA driver of the suspend and
        resume events.  Without them the driver doesn't get the chance to
        save and restore its state, which can cause the system to fail to
        resume.

        The driver can also handle the notifications itself when the
        UseKernelSuspendNotifiers module parameter is set, in which case
        the units are not needed.
        """
        gpus = get_nvidia_gpus()
        if not gpus:
            return True
        if get_module_params().get("UseKernelSuspendNotifiers") == "1":
            self.db.record_debug(
                "NVIDIA driver kernel suspend notifiers are enabled, "
                "the systemd units are not needed"
            )
            return True
        missing = []
        for unit in SUSPEND_UNITS:
            if not self._systemd_unit_exists(unit):
                continue
            if not self._systemd_unit_enabled(unit):
                missing.append(unit)
        if missing:
            self.db.record_prereq(
                f"NVIDIA systemd units are not enabled: {', '.join(missing)}", "❌"
            )
            self.failures += [NvidiaSuspendUnitsMissing(missing)]
            return False
        self.db.record_prereq("NVIDIA systemd units are enabled", "✅")
        return True

    def check_nvidia_powerd(self):
        """Check that the NVIDIA power daemon is available

        The ``nvidia-powerd`` daemon manages Dynamic Boost on supported
        laptops, shifting power between the CPU and the GPU.  It is not
        required for s2idle; the tool only reports whether it is
        installed and enabled.
        """
        gpus = get_nvidia_gpus()
        if not gpus:
            return True
        if not self._systemd_unit_exists(POWERD_UNIT):
            self.db.record_debug(
                "The nvidia-powerd daemon is not installed, the NVIDIA GPU "
                "power state will not be managed automatically"
            )
            return True
        if not self._systemd_unit_enabled(POWERD_UNIT):
            self.db.record_prereq(
                "The nvidia-powerd daemon is installed but not enabled", "🚦"
            )
            return True
        self.db.record_prereq("The nvidia-powerd daemon is enabled", "✅")
        return True

    def capture_nvidia_power(self):
        """Capture the NVIDIA GPU power management state"""
        gpus = get_nvidia_gpus()
        if not gpus:
            return
        for gpu in gpus:
            debug_str = f"NVIDIA GPU {gpu.bdf} power state\n"
            debug_str += f"│ Runtime D3 status: {gpu.runtime_d3}\n"
            debug_str += f"│ Video Memory: {gpu.video_memory}\n"
            debug_str += (
                f"│ Video Memory Self Refresh: {gpu.video_memory_self_refresh}\n"
            )
            debug_str += f"│ Video Memory Off: {gpu.video_memory_off}\n"
            debug_str += f"│ S0ix Platform Support: {gpu.s0ix_platform_support}\n"
            debug_str += f"│ S0ix Status: {gpu.s0ix_status}\n"
            debug_str += f"│ Notebook Dynamic Boost: {gpu.dynamic_boost}\n"
            self.db.record_debug(debug_str)

#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Display analysis"""
import os
from pyudev import Context

from amd_debug.common import read_file


class Display:
    """Display analysis"""

    def __init__(self):
        self.pyudev = Context()
        self.edid = {}

        for dev in self.pyudev.list_devices(subsystem="drm"):
            if not "card" in dev.device_path:
                continue
            p = os.path.join(dev.sys_path, "status")
            if not os.path.exists(p):
                continue
            f = read_file(p)
            if f != "connected":
                continue
            p = os.path.join(dev.sys_path, "enabled")
            f = read_file(p)
            if f != "enabled":
                continue
            self.edid[dev.sys_name] = os.path.join(dev.sys_path, "edid")

    def get_edid(self) -> list:
        """Get the path for EDID data for all connected displays"""
        return self.edid

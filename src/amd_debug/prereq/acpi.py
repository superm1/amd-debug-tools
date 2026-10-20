# SPDX-License-Identifier: MIT

"""
This module contains the ACPI related checks for the s2idle prerequisite
validator.
"""

import os
import shutil
import struct
import subprocess
import tempfile

from amd_debug.common import read_file, BIT
from amd_debug.failures import FadtWrong


class AcpiChecks:
    """Mixin providing the ACPI related prerequisite checks"""

    def check_lps0(self):
        """Check if LPS0 is enabled"""
        for m in ["acpi", "acpi_x86"]:
            p = os.path.join("/", "sys", "module", m, "parameters", "sleep_no_lps0")
            if not os.path.exists(p):
                continue
            fail = read_file(p) == "Y"
            if fail:
                self.db.record_prereq("LPS0 _DSM disabled", "❌")
            else:
                self.db.record_prereq("LPS0 _DSM enabled", "✅")
            return not fail
        self.db.record_prereq("LPS0 _DSM not found", "👀")
        return False

    def check_fadt(self):
        """Check the kernel emitted a message indicating FADT had a bit set."""
        found = False
        if not self.kernel_log:
            message = "Unable to test FADT from kernel log"
            self.db.record_prereq(message, "🚦")
        else:
            self.kernel_log.seek()
            matches = ["Low-power S0 idle used by default for system suspend"]
            found = self.kernel_log.match_line(matches)
        # try to look at FACP directly if not found (older kernel compat)
        if not found:
            self.db.record_debug("Fetching low power idle bit directly from FADT")
            target = os.path.join("/", "sys", "firmware", "acpi", "tables", "FACP")
            try:
                with open(target, "rb") as r:
                    r.seek(0x70)
                    found = struct.unpack("<I", r.read(4))[0] & BIT(21)
            except FileNotFoundError:
                self.db.record_prereq("FADT check unavailable", "🚦")
                return True
            except PermissionError:
                self.db.record_prereq("FADT check unavailable", "🚦")
                return True
        if found:
            message = "ACPI FADT supports Low-power S0 idle"
            self.db.record_prereq(message, "✅")
        else:
            message = "ACPI FADT doesn't support Low-power S0 idle"
            self.db.record_prereq(message, "❌")
            self.failures += [FadtWrong()]
        return found

    def capture_acpi(self):
        """Capture ACPI tables"""
        base = os.path.join("/", "sys", "firmware", "acpi", "tables")
        for root, _dirs, files in os.walk(base, topdown=False):
            for fname in files:
                target = os.path.join(root, fname)
                if "SSDT" in fname:
                    with open(target, "rb") as f:
                        s = f.read()
                        if s.find(b"_AEI") < 0:
                            continue
                elif "IVRS" in fname:
                    pass
                else:
                    continue
                try:
                    tmpd = tempfile.mkdtemp()
                    prefix = os.path.join(tmpd, "acpi")
                    subprocess.check_call(
                        ["iasl", "-p", prefix, "-d", target],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    self.db.record_debug_file(f"{prefix}.dsl")
                except FileNotFoundError as e:
                    self.db.record_prereq(f"Failed to capture ACPI table: {e}", "👀")
                except subprocess.CalledProcessError as e:
                    self.db.record_prereq(
                        f"Failed to capture ACPI table: {e.output}", "👀"
                    )
                finally:
                    shutil.rmtree(tmpd)
        return True

    def map_acpi_path(self):
        """Map of ACPI devices to ACPI paths"""
        devices = []
        for dev in self.pyudev.list_devices(subsystem="acpi"):
            p = os.path.join(dev.sys_path, "path")
            if not os.path.exists(p):
                continue
            p = os.path.join(dev.sys_path, "status")
            if os.path.exists(p):
                status = int(read_file(p))
                if status == 0:
                    continue
            devices.append(dev)
        debug_str = "ACPI name | ACPI path | Kernel driver\n"
        for dev in devices:
            p = os.path.join(dev.sys_path, "path")
            pth = read_file(p)
            p = os.path.join(dev.sys_path, "physical_node", "driver")
            if os.path.exists(p):
                driver = os.path.basename(os.readlink(p))
            else:
                driver = None
            debug_str += f"{dev.sys_name} | {pth} | {driver}\n"
        if debug_str:
            self.db.record_debug(debug_str)
        return True

    def capture_cstates(self):
        """Capture ACPI C state information for the first CPU (assumes the same for all CPUs)"""
        base = os.path.join("/", "sys", "bus", "cpu", "devices", "cpu0", "cpuidle")
        paths = {}
        for root, _dirs, files in os.walk(base, topdown=False):
            for fname in files:
                target = os.path.join(root, fname)
                with open(target, "rb") as f:
                    paths[target] = f.read()
        debug_str = "ACPI C-state information\n"
        for path, data in paths.items():
            prefix = "│ " if path != list(paths.keys())[-1] else "└─"
            debug_str += f"{prefix}{path}: {data.decode('utf-8', 'ignore')}"
        self.db.record_debug(debug_str)

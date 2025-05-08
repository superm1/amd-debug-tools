#!/usr/bin/python3
# SPDX-License-Identifier: MIT
"""CPPC triage script for AMD systems"""

import os
import argparse
import re
import sys

import pandas as pd
from tabulate import tabulate
from pyudev import Context

from amd_debug.common import (
    AmdTool,
    get_pretty_distro,
    print_color,
    read_file,
    read_msr,
    relaunch_sudo,
    show_log_info,
    version,
)


class MSR:  # pylint: disable=too-few-public-methods
    """MSR addresses for CPPC"""

    MSR_AMD_CPPC_CAP1 = 0xC00102B0
    MSR_AMD_CPPC_ENABLE = 0xC00102B1
    MSR_AMD_CPPC_CAP2 = 0xC00102B2
    MSR_AMD_CPPC_REQ = 0xC00102B3
    MSR_AMD_CPPC_STATUS = 0xC00102B4


def amd_cppc_cap_lowest_perf(x):
    """Return the lowest performance value from the given input."""
    return x & 0xFF


def amd_cppc_cap_lownonlin_perf(x):
    """Return the lowest nonlinear performance value from the given input."""
    return (x >> 8) & 0xFF


def amd_cppc_cap_nominal_perf(x):
    """Return the nominal performance value from the given input."""
    return (x >> 16) & 0xFF


def amd_cppc_cap_highest_perf(x):
    """Return the highest performance value from the given input."""
    return (x >> 24) & 0xFF


def amd_cppc_max_perf(x):
    """Return the maximum performance value from the given input."""
    return x & 0xFF


def amd_cppc_min_perf(x):
    """Return the minimum performance value from the given input."""
    return (x >> 8) & 0xFF


def amd_cppc_des_perf(x):
    """Return the desired performance value from the given input."""
    return (x >> 16) & 0xFF


def amd_cppc_epp_perf(x):
    """Return the energy performance preference value from the given input."""
    return (x >> 24) & 0xFF


class AmdPstateTriage(AmdTool):
    """Class for handling the triage process"""

    def __init__(self, logging):
        log_prefix = "pstate" if logging else None
        super().__init__(log_prefix)
        relaunch_sudo()

        pretty = get_pretty_distro()
        print_color(f"{pretty}", "🐧")

        self.context = Context()

    def gather_amd_pstate_info(self):
        """Gather AMD Pstate global information"""
        for f in ("status", "prefcore"):
            p = os.path.join("/", "sys", "devices", "system", "cpu", "amd_pstate", f)
            if os.path.exists(p):
                print_color(f"'{f}':\t{read_file(p)}", "○")

    def gather_kernel_info(self):
        """Gather kernel information"""
        print_color(f"Kernel:\t{os.uname().release}", "🐧")

    def gather_scheduler_info(self):
        """Gather information about the scheduler"""
        procfs = os.path.join("/", "proc", "sys", "kernel", "sched_itmt_enabled")
        debugfs = os.path.join(
            "/", "sys", "kernel", "debug", "x86", "sched_itmt_enabled"
        )
        for p in [procfs, debugfs]:
            if os.path.exists(p):
                val = read_file(p)
                print_color(f"ITMT:\t{val}", "🐧")

    def gather_cpu_info(self):
        """Gather a dataframe of CPU information"""

        df = pd.DataFrame(
            columns=[
                "CPU #",
                "CPU Min Freq",
                "CPU Nonlinear Freq",
                "CPU Max Freq",
                "Scaling Min Freq",
                "Scaling Max Freq",
                "Energy Performance Preference",
                "Prefcore",
                "Boost",
            ]
        )

        for device in self.context.list_devices(subsystem="cpu"):
            p = os.path.join(device.sys_path, "cpufreq")
            if not os.path.exists(p):
                continue
            row = [
                int(re.findall(r"\d+", f"{device.sys_name}")[0]),
                read_file(os.path.join(p, "cpuinfo_min_freq")),
                read_file(os.path.join(p, "amd_pstate_lowest_nonlinear_freq")),
                read_file(os.path.join(p, "cpuinfo_max_freq")),
                read_file(os.path.join(p, "scaling_min_freq")),
                read_file(os.path.join(p, "scaling_max_freq")),
                read_file(os.path.join(p, "energy_performance_preference")),
                read_file(os.path.join(p, "amd_pstate_prefcore_ranking")),
                read_file(os.path.join(p, "boost")),
            ]
            df = pd.concat(
                [pd.DataFrame([row], columns=df.columns), df], ignore_index=True
            )

        cpuinfo = read_file("/proc/cpuinfo")
        model = re.findall(r"model name\s+:\s+(.*)", cpuinfo)[0]
        print_color(f"CPU:\t\t{model}", "💻")

        df = df.sort_values(by="CPU #")
        print_color(
            "Per-CPU sysfs files\n%s"
            % tabulate(df, headers="keys", tablefmt="psql", showindex=False),
            "🔋",
        )

    def gather_msrs(self):
        """Gather MSR information"""
        cpus = []
        for device in self.context.list_devices(subsystem="cpu"):
            cpu = int(re.findall(r"\d+", f"{device.sys_name}")[0])
            cpus.append(cpu)
        cpus.sort()

        df = pd.DataFrame(
            columns=[
                "CPU #",
                "Min Perf",
                "Max Perf",
                "Desired Perf",
                "Energy Performance Perf",
            ]
        )

        msr_df = pd.DataFrame(
            columns=[
                "CPU #",
                "Enable",
                "Status",
                "Cap 1",
                "Cap 2",
                "Request",
            ]
        )

        cap_df = pd.DataFrame(
            columns=[
                "CPU #",
                "Lowest Perf",
                "Nonlinear Perf",
                "Nominal Perf",
                "Highest Perf",
            ]
        )

        try:
            for cpu in cpus:
                enable = read_msr(MSR.MSR_AMD_CPPC_ENABLE, cpu)
                status = read_msr(MSR.MSR_AMD_CPPC_STATUS, cpu)
                cap1 = read_msr(MSR.MSR_AMD_CPPC_CAP1, cpu)
                cap2 = read_msr(MSR.MSR_AMD_CPPC_CAP2, cpu)

                req = read_msr(MSR.MSR_AMD_CPPC_REQ, cpu)
                row = [
                    cpu,
                    amd_cppc_min_perf(req),
                    amd_cppc_max_perf(req),
                    amd_cppc_des_perf(req),
                    amd_cppc_epp_perf(req),
                ]
                df = pd.concat(
                    [pd.DataFrame([row], columns=df.columns), df], ignore_index=True
                )

                row = [
                    cpu,
                    enable,
                    status,
                    hex(cap1),
                    hex(cap2),
                    hex(req),
                ]
                msr_df = pd.concat(
                    [pd.DataFrame([row], columns=msr_df.columns), msr_df],
                    ignore_index=True,
                )

                row = [
                    cpu,
                    amd_cppc_cap_lowest_perf(cap1),
                    amd_cppc_cap_lownonlin_perf(cap1),
                    amd_cppc_cap_nominal_perf(cap1),
                    amd_cppc_cap_highest_perf(cap1),
                ]
                cap_df = pd.concat(
                    [pd.DataFrame([row], columns=cap_df.columns), cap_df],
                    ignore_index=True,
                )

        except FileNotFoundError:
            print_color("Unable to check MSRs: MSR kernel module not loaded", "❌")
            return False
        except PermissionError:
            print_color("MSR checks unavailable", "🚦")
            return

        msr_df = msr_df.sort_values(by="CPU #")
        print_color(
            "CPPC MSRs\n%s"
            % tabulate(msr_df, headers="keys", tablefmt="psql", showindex=False),
            "🔋",
        )

        cap_df = cap_df.sort_values(by="CPU #")
        print_color(
            "MSR_AMD_CPPC_CAP1 (decoded)\n%s"
            % tabulate(cap_df, headers="keys", tablefmt="psql", showindex=False),
            "🔋",
        )

        df = df.sort_values(by="CPU #")
        print_color(
            "MSR_AMD_CPPC_REQ (decoded)\n%s"
            % tabulate(df, headers="keys", tablefmt="psql", showindex=False),
            "🔋",
        )

    def run(self):
        """Run the triage process"""
        self.gather_kernel_info()
        self.gather_amd_pstate_info()
        self.gather_scheduler_info()
        try:
            self.gather_cpu_info()
        except FileNotFoundError:
            print_color("Unable to gather CPU information", "❌")
            return False
        self.gather_msrs()
        return True


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Collect useful information for debugging amd-pstate issues.",
        epilog="Arguments are optional",
    )
    subparsers = parser.add_subparsers(help="Possible commands", dest="command")
    triage_cmd = subparsers.add_parser("triage", help="Run amd-pstate triage")
    triage_cmd.add_argument(
        "--tool-debug",
        action="store_true",
        help="Enable tool debug logging",
    )
    subparsers.add_parser("version", help="Show version information")
    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        sys.exit(1)
    return parser.parse_args()


def main():
    """Main function"""
    args = parse_args()
    ret = False
    if args.command == "version":
        print(version())
        return True
    elif args.command == "triage":
        triage = AmdPstateTriage(args.tool_debug)
        ret = triage.run()
    show_log_info()
    return ret

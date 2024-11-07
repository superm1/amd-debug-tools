#!/usr/bin/python3
# SPDX-License-Identifier: MIT
"""CPPC triage script for AMD systems"""

import sys
import os
import re
import subprocess
import logging
import argparse
import struct
from datetime import datetime, timedelta, date


class defaults:
    log_prefix = "amd_pstate_report"
    log_suffix = "txt"


class colors:
    DEBUG = "\033[90m"
    HEADER = "\033[95m"
    OK = "\033[94m"
    WARNING = "\033[32m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"
    UNDERLINE = "\033[4m"


class MSR:
    MSR_AMD_CPPC_CAP1 = 0xC00102B0
    MSR_AMD_CPPC_ENABLE = 0xC00102B1
    MSR_AMD_CPPC_CAP2 = 0xC00102B2
    MSR_AMD_CPPC_REQ = 0xC00102B3
    MSR_AMD_CPPC_STATUS = 0xC00102B4


def AMD_CPPC_MAX_PERF(x):
    return x & 0xFF


def AMD_CPPC_MIN_PERF(x):
    return (x >> 8) & 0xFF


def AMD_CPPC_DES_PERF(x):
    return (x >> 16) & 0xFF


def AMD_CPPC_EPP_PERF(x):
    return (x >> 24) & 0xFF


class headers:
    LogDescription = "Location of log file"
    InstallAction = "Attempting to install"
    RerunAction = "Running this script as root will attempt to install it"
    MissingPyudev = "Udev access library `pyudev` is missing"
    MissingPandas = "Data library `pandas` is missing"
    MissingTabulate = "Data library `tabulate` is missing"


class DistroPackage:
    def __init__(self, deb, rpm, arch, pip, root):
        self.deb = deb
        self.rpm = rpm
        self.arch = arch
        self.pip = pip
        self.root = root

    def install(self, distro):
        if not self.root:
            sys.exit(1)
        if distro == "ubuntu" or distro == "debian":
            if not self.deb:
                return False
            installer = ["apt", "install", self.deb]
        elif distro == "fedora":
            if not self.rpm:
                return False
            release = read_file("/usr/lib/os-release")
            variant = None
            for line in release.split("\n"):
                if line.startswith("VARIANT_ID"):
                    variant = line.split("=")[-1]
            if variant != "workstation":
                return False
            installer = ["dnf", "install", "-y", self.rpm]
        elif distro == "cachyos" or distro == "arch":
            installer = ["pacman", "-Sy", self.arch]
        else:
            if not self.pip:
                return False
            installer = ["python3", "-m", "pip", "install", "--upgrade", self.pip]
        subprocess.check_call(installer)
        return True


class PyUdevPackage(DistroPackage):
    def __init__(self, root):
        super().__init__(
            deb="python3-pyudev",
            rpm="python3-pyudev",
            arch="python-pyudev",
            pip="pyudev",
            root=root,
        )


class PandasPackage(DistroPackage):
    def __init__(self, root):
        super().__init__(
            deb="python3-pandas",
            rpm="python3-pandas",
            arch="python-pandas",
            pip="pandas",
            root=root,
        )


class TabulatePackage(DistroPackage):
    def __init__(self, root):
        super().__init__(
            deb="python3-tabulate",
            rpm="python3-tabulate",
            arch="python-tabulate",
            pip="tabulate",
            root=root,
        )


def read_file(fn):
    with open(fn, "r") as r:
        return r.read().strip()


def print_color(message, group):
    prefix = "%s " % group
    suffix = colors.ENDC
    if group == "🚦":
        color = colors.WARNING
    elif group == "🦟":
        color = colors.DEBUG
    elif any(mk in group for mk in ["❌", "👀"]):
        color = colors.FAIL
    elif any(mk in group for mk in ["✅", "🔋", "🐧", "💻", "○"]):
        color = colors.OK
    else:
        color = group
        prefix = ""

    log_txt = "{prefix}{message}".format(prefix=prefix, message=message).strip()
    if any(c in color for c in [colors.OK, colors.HEADER, colors.UNDERLINE]):
        logging.info(log_txt)
    elif color == colors.WARNING:
        logging.warning(log_txt)
    elif color == colors.FAIL:
        logging.error(log_txt)
    else:
        logging.debug(log_txt)

    if "TERM" in os.environ and os.environ["TERM"] == "dumb":
        suffix = ""
        color = ""
    print(f"{prefix}{color}{message}{suffix}")


def fatal_error(message):
    print_color(message, "👀")
    sys.exit(1)


class AmdPstateTriage:
    def show_install_message(self, message):
        action = headers.InstallAction if self.root_user else headers.RerunAction
        message = "{message}. {action}.".format(message=message, action=action)
        print_color(message, "👀")

    def __init__(self):
        # for saving a log file for analysis
        logging.basicConfig(
            format="%(asctime)s %(levelname)s:\t%(message)s",
            filename=log,
            filemode="w",
            level=logging.DEBUG,
        )

        self.root_user = os.geteuid() == 0

        try:
            import distro

            self.distro = distro.id()
            self.pretty_distro = distro.distro.os_release_info()["pretty_name"]
        except ModuleNotFoundError:
            fatal_error("Missing python-distro package, unable to identify distro")

        try:
            import pyudev

            self.context = pyudev.Context()
        except ModuleNotFoundError:
            self.context = False

        if not self.context:
            self.show_install_message(headers.MissingPyudev)
            package = PyUdevPackage(self.root_user)
            package.install(self.distro)
            try:
                from pyudev import Context
            except ModuleNotFoundError:
                fatal_error("Missing python-pyudev package, unable to identify devices")
            self.context = Context()

        try:
            from pandas import DataFrame

            self.pandas = True
        except ImportError:
            self.pandas = False
        except ModuleNotFoundError:
            self.pandas = False

        if not self.pandas:
            self.show_install_message(headers.MissingPandas)
            package = PandasPackage(self.root_user)
            package.install(self.distro)
            try:
                from pandas import DataFrame

                self.pandas = True
            except ModuleNotFoundError:
                fatal_error("Missing pandas package, unable to gather data")

        try:
            from tabulate import tabulate

            self.tabulate = True
        except ModuleNotFoundError:
            self.tabulate = False

        if not self.tabulate:
            self.show_install_message(headers.MissingTabulate)
            package = TabulatePackage(self.root_user)
            package.install(self.distro)
            try:
                from tabulate import tabulate

                self.tabulate = True
            except ModuleNotFoundError:
                fatal_error("Missing python-tabulate package, unable to display data")

    def gather_kernel_info(self):
        """Gather kernel information"""
        print_color(f"Kernel:\t{os.uname().release}", "🐧")

    def gather_cpu_info(self):
        """Gather a dataframe of CPU information"""
        import pandas as pd
        from tabulate import tabulate

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
        print_color(f"CPU:\t{re.findall(r'model name\s+:\s+(.*)', cpuinfo)[0]}", "💻")

        df = df.sort_values(by="CPU #")
        print_color(
            "Kernel sysfs files\n%s"
            % tabulate(df, headers="keys", tablefmt="psql", showindex=False),
            "🔋",
        )

    def gather_msrs(self):
        """Gather MSR information"""

        def read_msr(msr, cpu):
            p = "/dev/cpu/%d/msr" % cpu
            if not os.path.exists(p) and self.root_user:
                os.system("modprobe msr")
            f = os.open(p, os.O_RDONLY)
            os.lseek(f, msr, os.SEEK_SET)
            val = struct.unpack("Q", os.read(f, 8))[0]
            os.close(f)
            return val

        import pandas as pd
        from tabulate import tabulate

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

        try:
            for cpu in cpus:
                val = read_msr(MSR.MSR_AMD_CPPC_REQ, cpu)
                row = [
                    cpu,
                    AMD_CPPC_MIN_PERF(val),
                    AMD_CPPC_MAX_PERF(val),
                    AMD_CPPC_DES_PERF(val),
                    AMD_CPPC_EPP_PERF(val),
                ]
                logging.debug(f"CPU{cpu}\tMSR_AMD_CPPC_REQ: 0x{val:016x}")
                df = pd.concat(
                    [pd.DataFrame([row], columns=df.columns), df], ignore_index=True
                )

        except FileNotFoundError:
            print_color("Unabled to check MSRs: MSR kernel module not loaded", "❌")
            return False
        except PermissionError:
            if not self.root_user:
                print_color("Run as root to check MSRs", "🚦")
            else:
                print_color("MSR checks unavailable", "🚦")
            return

        df = df.sort_values(by="CPU #")
        print_color(
            "MSR_AMD_CPPC_REQ\n%s"
            % tabulate(df, headers="keys", tablefmt="psql", showindex=False),
            "🔋",
        )

    def run(self):
        self.gather_kernel_info()
        self.gather_cpu_info()
        self.gather_msrs()


def parse_args():
    parser = argparse.ArgumentParser(
        description="Collect useful information for debugging amd-pstate issues.",
        epilog="Arguments are optional, and if they are not provided will prompted.\n"
        "To use non-interactively, please populate all optional arguments.",
    )
    parser.add_argument(
        "--log",
        help=headers.LogDescription,
    )
    return parser.parse_args()


def configure_log(log):
    if not log:
        fname = "{prefix}-{date}.{suffix}".format(
            prefix=defaults.log_prefix, suffix=defaults.log_suffix, date=date.today()
        )
        log = input(
            "{question} (default {fname})? ".format(
                question=headers.LogDescription, fname=fname
            )
        )
        if not log:
            log = fname
    return log


if __name__ == "__main__":
    args = parse_args()
    log = configure_log(args.log)
    triage = AmdPstateTriage()
    triage.run()

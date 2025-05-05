#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Kernel log analysis"""

import logging
import re
import os
import subprocess
from datetime import timedelta

from amd_debug.common import systemd_in_use, read_file, fatal_error


def get_kernel_command_line() -> str:
    """Get the kernel command line"""
    cmdline = read_file(os.path.join("/proc", "cmdline"))
    # borrowed from https://github.com/fwupd/fwupd/blob/1.9.5/libfwupdplugin/fu-common-linux.c#L95
    filtered = [
        "apparmor",
        "audit",
        "auto",
        "boot",
        "BOOT_IMAGE",
        "console",
        "crashkernel",
        "cryptdevice",
        "cryptkey",
        "dm",
        "earlycon",
        "earlyprintk",
        "ether",
        "initrd",
        "ip",
        "LANG",
        "loglevel",
        "luks.key",
        "luks.name",
        "luks.options",
        "luks.uuid",
        "mitigations",
        "mount.usr",
        "mount.usrflags",
        "mount.usrfstype",
        "netdev",
        "netroot",
        "nfsaddrs",
        "nfs.nfs4_unique_id",
        "nfsroot",
        "noplymouth",
        "ostree",
        "quiet",
        "rd.dm.uuid",
        "rd.luks.allow-discards",
        "rd.luks.key",
        "rd.luks.name",
        "rd.luks.options",
        "rd.luks.uuid",
        "rd.lvm.lv",
        "rd.lvm.vg",
        "rd.md.uuid",
        "rd.systemd.mask",
        "rd.systemd.wants",
        "resume",
        "resumeflags",
        "rhgb",
        "ro",
        "root",
        "rootflags",
        "roothash",
        "rw",
        "security",
        "showopts",
        "splash",
        "swap",
        "systemd.mask",
        "systemd.show_status",
        "systemd.unit",
        "systemd.verity_root_data",
        "systemd.verity_root_hash",
        "systemd.wants",
        "udev.log_priority",
        "verbose",
        "vt.handoff",
        "zfs",
    ]
    # remove anything that starts with something in filtered from cmdline
    return " ".join([x for x in cmdline.split() if not x.startswith(tuple(filtered))])


def sscanf_bios_args(line):
    """Extracts the format string and arguments from a BIOS trace line"""
    if re.search(r"ex_trace_point", line):
        return True
    elif re.search(r"ex_trace_args", line):
        parts = line.split(": ", 1)
        if len(parts) < 2:
            return None

        t = parts[1].strip()
        match = re.match(r'"(.*?)"(,.*)', t)
        if match:
            format_string = match.group(1).strip().replace("\\n", "")
            args_part = match.group(2).strip(", ")
            arguments = [arg.strip() for arg in args_part.split(",")]

            format_specifiers = re.findall(r"%([xXdD])", format_string)

            converted_args = []
            arg_index = 0
            for specifier in format_specifiers:
                if arg_index < len(arguments):
                    value = arguments[arg_index]
                    if value == "Unknown":
                        converted_args.append(-1)
                    elif specifier.lower() == "x":
                        try:
                            converted_args.append(int(value, 16))
                        except ValueError:
                            return None
                    else:  # Decimal conversion
                        try:
                            converted_args.append(int(value))
                        except ValueError:
                            try:
                                converted_args.append(int(value, 16))
                            except ValueError:
                                return None
                    arg_index += 1
                else:
                    break

            try:
                return format_string % tuple(converted_args)
            except TypeError:
                return None
        else:
            # If no format string is found, assume no format modifiers and return True
            return True
    # evmisc-0132 ev_queue_notify_reques: Dispatching Notify on [UBTC] (Device) Value 0x80 (Status Change) Node 00000000851b15c1
    elif re.search(r"ev_queue_notify_reques", line):
        parts = line.split(": ", 1)
        if len(parts) < 2:
            return None
        return parts[1].split("Node")[0].strip()

    return None


class KernelLogger:
    """Base class for kernel loggers"""

    def __init__(self):
        pass

    def seek(self):
        """Seek to the beginning of the log"""

    def seek_tail(self, tim=None):
        """Seek to the end of the log"""

    def process_callback(self, callback, priority):
        """Process the log"""

    def match_line(self, _matches) -> str:
        """Find lines that match all matches"""
        return ""

    def match_pattern(self, _pattern) -> str:
        """Find lines that match a pattern"""
        return ""


class InputFile(KernelLogger):
    """Class for input file parsing"""

    def __init__(self, fname):
        self.since_support = False
        self.buffer = None
        self.seeked = False
        self.buffer = read_file(fname)

    def process_callback(self, callback, priority=None):
        """Process the log"""
        for entry in self.buffer.split("\n"):
            callback(entry, priority)


class DmesgLogger(KernelLogger):
    """Class for dmesg logging"""

    def __init__(self):
        self.since_support = False
        self.buffer = None
        self.seeked = False

        cmd = ["dmesg", "-h"]
        result = subprocess.run(cmd, check=True, capture_output=True)
        for line in result.stdout.decode("utf-8").split("\n"):
            if "--since" in line:
                self.since_support = True
        logging.debug("dmesg since support: %d", self.since_support)

        self.command = ["dmesg", "-t", "-k"]
        self._refresh_head()

    def _refresh_head(self):
        self.buffer = []
        self.seeked = False
        result = subprocess.run(self.command, check=True, capture_output=True)
        if result.returncode == 0:
            self.buffer = result.stdout.decode("utf-8")

    def seek(self):
        """Seek to the beginning of the log"""
        if self.seeked:
            self._refresh_head()

    def seek_tail(self, tim=None):
        """Seek to the end of the log"""
        if tim:
            if self.since_support:
                # look 10 seconds back because dmesg time isn't always accurate
                fuzz = tim - timedelta(seconds=10)
                cmd = self.command + [
                    "--time-format=iso",
                    f"--since={fuzz.strftime('%Y-%m-%dT%H:%M:%S')}",
                ]
            else:
                cmd = self.command
            result = subprocess.run(cmd, check=True, capture_output=True)
            if result.returncode == 0:
                self.buffer = result.stdout.decode("utf-8")
                if self.since_support:
                    self.seeked = True

    def process_callback(self, callback, _priority=None):
        """Process the log"""
        for entry in self.buffer.split("\n"):
            callback(entry, _priority)

    def match_line(self, matches):
        """Find lines that match all matches"""
        for entry in self.buffer.split("\n"):
            for match in matches:
                if match not in entry:
                    break
                return entry
        return ""

    def match_pattern(self, pattern) -> str:
        for entry in self.buffer.split("\n"):
            if re.search(pattern, entry):
                return entry
        return ""

    def capture_header(self):
        """Capture the header of the log"""
        return self.buffer.split("\n")[0]


class CySystemdLogger(KernelLogger):
    """Class for logging using systemd journal using cython"""

    def __init__(self):
        from cysystemd.reader import JournalReader, JournalOpenMode, Rule

        boot_reader = JournalReader()
        boot_reader.open(JournalOpenMode.SYSTEM)
        boot_reader.seek_tail()
        boot_reader.skip_previous(1)

        current_boot_id = None
        for entry in boot_reader:
            if hasattr(entry, "data") and "_BOOT_ID" in entry.data:
                current_boot_id = entry.data["_BOOT_ID"]
                break
        if not current_boot_id:
            raise RuntimeError("Unable to find current boot ID")

        rules = Rule("_BOOT_ID", current_boot_id) & Rule("_TRANSPORT", "kernel")

        self.journal = JournalReader()
        self.journal.open(JournalOpenMode.SYSTEM)
        self.journal.add_filter(rules)

    def seek(self):
        """Seek to the beginning of the log"""
        self.journal.seek_head()

    def seek_tail(self, tim=None):
        """Seek to the end of the log"""
        if tim:
            timestamp_usec = int(tim.timestamp() * 1_000_000)
            self.journal.seek_realtime_usec(timestamp_usec)
        else:
            self.journal.seek_tail()

    def process_callback(self, callback, _priority=None):
        """Process the log"""
        for entry in self.journal:
            callback(entry["MESSAGE"], entry["PRIORITY"])

    def match_line(self, matches):
        """Find lines that match all matches"""
        for entry in self.journal:
            for match in matches:
                if match not in entry["MESSAGE"]:
                    break
                return entry["MESSAGE"]
        return None

    def match_pattern(self, pattern):
        """Find lines that match a pattern"""
        for entry in self.journal:
            if re.search(pattern, entry["MESSAGE"]):
                return entry["MESSAGE"]
        return None


class SystemdLogger(KernelLogger):
    """Class for logging using systemd journal"""

    def __init__(self):
        from systemd import journal  # pylint: disable=import-outside-toplevel

        self.journal = journal.Reader()
        self.journal.this_boot()
        self.journal.log_level(journal.LOG_INFO)
        self.journal.add_match(_TRANSPORT="kernel")
        self.journal.add_match(PRIORITY=journal.LOG_DEBUG)

    def seek(self):
        """Seek to the beginning of the log"""
        self.journal.seek_head()

    def seek_tail(self, tim=None):
        if tim:
            self.journal.seek_realtime(tim)
        else:
            self.journal.seek_tail()

    def process_callback(self, callback, _priority=None):
        """Process the log"""
        for entry in self.journal:
            callback(entry["MESSAGE"], entry["PRIORITY"])

    def match_line(self, matches):
        """Find lines that match all matches"""
        for entry in self.journal:
            for match in matches:
                if match not in entry["MESSAGE"]:
                    break
                return entry["MESSAGE"]
        return ""

    def match_pattern(self, pattern):
        """Find lines that match a pattern"""
        for entry in self.journal:
            if re.search(pattern, entry["MESSAGE"]):
                return entry["MESSAGE"]
        return ""


def get_kernel_log(input_file=None) -> KernelLogger:
    """Get the kernel log provider"""
    kernel_log = None
    if input_file:
        kernel_log = InputFile(input_file)
    elif systemd_in_use():
        try:
            kernel_log = CySystemdLogger()
        except ImportError:
            kernel_log = None
        except RuntimeError as e:
            logging.debug(e)
            kernel_log = None
        if not kernel_log:
            try:
                kernel_log = SystemdLogger()
            except ModuleNotFoundError:
                pass
    if not kernel_log:
        try:
            kernel_log = DmesgLogger()
        except subprocess.CalledProcessError as e:
            fatal_error(f"{e}")
            kernel_log = None
    logging.debug("Kernel log provider: %s", kernel_log.__class__.__name__)
    return kernel_log

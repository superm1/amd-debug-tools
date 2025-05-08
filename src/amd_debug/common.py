#!/usr/bin/python3
# SPDX-License-Identifier: MIT

"""
This module contains common utility functions and classes for various amd-debug-tools.
"""

import importlib.metadata
import logging
import os
import platform
import time
import struct
import subprocess
import re
import sys
from datetime import date, timedelta


class Colors:
    """Colors for the terminal"""

    DEBUG = "\033[90m"
    HEADER = "\033[95m"
    OK = "\033[94m"
    WARNING = "\033[32m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"
    UNDERLINE = "\033[4m"


def read_file(fn) -> str:
    """Read a file and return the contents"""
    with open(fn, "r", encoding="utf-8") as r:
        return r.read().strip()


def compare_file(fn, expect) -> bool:
    """Compare a file to an expected string"""
    return read_file(fn) == expect


def get_group_color(group) -> str:
    """Get the color for a group"""
    if group == "🚦":
        color = Colors.WARNING
    elif group == "🗣️":
        color = Colors.HEADER
    elif group == "💯":
        color = Colors.UNDERLINE
    elif any(mk in group for mk in ["🦟", "🖴"]):
        color = Colors.DEBUG
    elif any(mk in group for mk in ["❌", "👀"]):
        color = Colors.FAIL
    elif any(mk in group for mk in ["✅", "🔋", "🐧", "💻", "○", "💤", "🥱"]):
        color = Colors.OK
    else:
        color = group
    return color


def print_color(message, group) -> None:
    """Print a message with a color"""
    prefix = f"{group} "
    suffix = Colors.ENDC
    color = get_group_color(group)
    if color == group:
        prefix = ""
    log_txt = f"{prefix}{message}".strip()
    if any(c in color for c in [Colors.OK, Colors.HEADER, Colors.UNDERLINE]):
        logging.info(log_txt)
    elif color == Colors.WARNING:
        logging.warning(log_txt)
    elif color == Colors.FAIL:
        logging.error(log_txt)
    else:
        logging.debug(log_txt)
    if "TERM" in os.environ and os.environ["TERM"] == "dumb":
        suffix = ""
        color = ""
    print(f"{prefix}{color}{message}{suffix}")


def fatal_error(message):
    """Prints a fatal error message and exits"""
    _configure_log(None)
    print_color(message, "👀")
    sys.exit(1)


def show_log_info():
    """Show log information"""
    logger = logging.getLogger()
    for handler in logger.handlers:
        if isinstance(handler, logging.FileHandler):
            filename = handler.baseFilename
            if filename != "/dev/null":
                print(f"Debug logs are saved to: {filename}")


def _configure_log(prefix) -> str:
    """Configure logging for the tool"""
    if len(logging.root.handlers) > 0:
        return

    if prefix:
        user = os.environ.get("SUDO_USER")
        home = os.path.expanduser(f"~{user if user else ''}")
        path = os.environ.get("XDG_DATA_HOME") or os.path.join(
            home, ".local", "share", "amd-debug-tools"
        )
        os.makedirs(path, exist_ok=True)
        log = os.path.join(
            path,
            f"{prefix}-{date.today()}.txt",
        )
        if not os.path.exists(log):
            with open(log, "w", encoding="utf-8") as f:
                f.write("")
            if "SUDO_UID" in os.environ:
                os.chown(path, int(os.environ["SUDO_UID"]), int(os.environ["SUDO_GID"]))
                os.chown(log, int(os.environ["SUDO_UID"]), int(os.environ["SUDO_GID"]))
        level = logging.DEBUG
    else:
        log = "/dev/null"
        level = logging.WARNING
    # for saving a log file for analysis
    logging.basicConfig(
        format="%(asctime)s %(levelname)s:\t%(message)s",
        filename=log,
        level=level,
    )
    return log


def check_lockdown():
    """Check if the system is in lockdown"""
    fn = os.path.join("/", "sys", "kernel", "security", "lockdown")
    if not os.path.exists(fn):
        return False
    lockdown = read_file(fn)
    if lockdown.split()[0] != "[none]":
        return lockdown
    return False


def print_temporary_message(msg) -> int:
    """Print a temporary message to the console"""
    print(msg, end="\r", flush=True)
    return len(msg)


def clear_temporary_message(msg_len) -> None:
    """Clear a temporary message from the console"""
    print(" " * msg_len, end="\r")


def run_countdown(action, t) -> bool:
    """Run a countdown timer"""
    msg = ""
    if t < 0:
        return False
    if t == 0:
        return True
    while t > 0:
        msg = f"{action} in {timedelta(seconds=t)}"
        print_temporary_message(msg)
        time.sleep(1)
        t -= 1
    clear_temporary_message(len(msg))
    return True


def get_distro() -> str:
    """Get the distribution name"""
    distro = "unknown"
    if os.path.exists("/etc/os-release"):
        with open("/etc/os-release", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("ID="):
                    return line.split("=")[1].strip().strip('"')
    if os.path.exists("/etc/arch-release"):
        return "arch"
    elif os.path.exists("/etc/fedora-release"):
        return "fedora"
    elif os.path.exists("/etc/debian_version"):
        return "debian"

    return distro


def get_pretty_distro() -> str:
    """Get the pretty distribution name"""
    distro = "Unknown"
    if os.path.exists("/etc/os-release"):
        with open("/etc/os-release", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    distro = line.split("=")[1].strip().strip('"')
                    break
    return distro


def is_root() -> bool:
    """Check if the user is root"""
    return os.geteuid() == 0


def BIT(num):  # pylint: disable=invalid-name
    """Return a bit shifted value"""
    return 1 << num


def get_log_priority(num):
    """Maps an integer debug level to a priority type"""
    if num:
        try:
            num = int(num)
        except ValueError:
            return num
        if num == 7:
            return "🦟"
        elif num == 4:
            return "🚦"
        elif num <= 3:
            return "❌"
    return "○"


def minimum_kernel(major, minor) -> bool:
    """Checks if the kernel version is at least major.minor"""
    ver = platform.uname().release.split(".")
    kmajor = int(ver[0])
    kminor = int(ver[1])
    if kmajor > int(major):
        return True
    if kmajor < int(major):
        return False
    return kminor >= int(minor)


def systemd_in_use() -> bool:
    """Check if systemd is in use"""
    # Check if /proc/1/comm exists and read its contents
    init_daemon = read_file("/proc/1/comm")
    return init_daemon == "systemd"


def get_property_pyudev(properties, key, fallback=""):
    """Get a property from a udev device"""
    try:
        return properties.get(key, fallback)
    except UnicodeDecodeError:
        return ""


def read_msr(msr, cpu):
    """Read a Model-Specific Register (MSR) value from the CPU."""
    p = f"/dev/cpu/{cpu}/msr"
    if not os.path.exists(p) and is_root():
        os.system("modprobe msr")
    try:
        f = os.open(p, os.O_RDONLY)
    except OSError as exc:
        raise PermissionError from exc
    try:
        os.lseek(f, msr, os.SEEK_SET)
        val = struct.unpack("Q", os.read(f, 8))[0]
    except OSError as exc:
        raise PermissionError from exc
    finally:
        os.close(f)
    return val


def relaunch_sudo() -> None:
    """Relaunch the script with sudo if not already running as root"""
    if not is_root():
        logging.debug("Relaunching with sudo")
        os.execvp("sudo", ["sudo", "-E"] + sys.argv)


def running_ssh():
    return "SSH_CLIENT" in os.environ or "SSH_TTY" in os.environ


def _git_describe() -> str:
    """Get the git description of the current commit"""
    try:
        result = subprocess.check_output(
            ["git", "log", "-1", '--format=commit %h ("%s")'],
            cwd=os.path.dirname(__file__),
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return result.strip()
    except subprocess.CalledProcessError:
        return None
    except FileNotFoundError:
        return None


def version() -> str:
    """Get version of the tool"""
    ver = "unknown"
    try:
        ver = importlib.metadata.version("amd-debug-tools")
    except importlib.metadata.PackageNotFoundError:
        pass
    describe = _git_describe()
    if describe:
        ver = f"{ver} [{describe}]"
    return ver


class AmdTool:
    """Base class for AMD tools"""

    def __init__(self, prefix):
        self.log = _configure_log(prefix)
        logging.debug("command: %s (module: %s)", sys.argv, type(self).__name__)
        logging.debug("Version: %s", version())
        if os.uname().sysname != "Linux":
            raise RuntimeError("This tool only runs on Linux")

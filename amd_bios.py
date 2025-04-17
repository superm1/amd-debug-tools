#!/usr/bin/python3
# SPDX-License-Identifier: MIT
"""BIOS debug log control for AMD systems"""

import argparse
import logging
import os
import re
import subprocess
import sys
from datetime import date, timedelta

# test if pip can be used to install anything
try:
    import pip as _

    PIP = True
except ModuleNotFoundError:
    PIP = False

# used to identify the distro
try:
    import distro

    DISTRO = True
except ModuleNotFoundError:
    DISTRO = False


class Colors:
    """Colors for terminal output"""

    DEBUG = "\033[90m"
    HEADER = "\033[95m"
    OK = "\033[94m"
    WARNING = "\033[32m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"
    UNDERLINE = "\033[4m"


class Headers:
    """Headers for the script"""

    LogDescription = "Location of log file"
    InstallAction = "Attempting to install"
    MissingJournald = "Python systemd/journald module is missing"
    RerunAction = "Running this script as root will attempt to install it"


class Defaults:
    """Default values for the script"""

    log_prefix = "bios"
    log_suffix = "txt"


class DistroPackage:
    """Base class for distro packages"""

    def __init__(self, deb, rpm, arch, pip, root):
        self.deb = deb
        self.rpm = rpm
        self.arch = arch
        self.pip = pip
        self.root = root

    def install(self, dist):
        """Install the package for a given distro"""
        if not self.root:
            sys.exit(1)
        if dist == "ubuntu" or dist == "debian":
            if not self.deb:
                return False
            installer = ["apt", "install", self.deb]
        elif dist == "fedora":
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
        elif dist == "arch" or os.path.exists("/etc/arch-release"):
            if not self.arch:
                return False
            installer = ["pacman", "-Sy", self.arch]
        else:
            if not PIP or not self.pip:
                return False
            installer = ["python3", "-m", "pip", "install", "--upgrade", self.pip]

        subprocess.check_call(installer)
        return True


class JournaldPackage(DistroPackage):
    """Journald package"""

    def __init__(self, root):
        super().__init__(
            deb="python3-systemd",
            rpm="python3-pyudev",
            arch="python-systemd",
            pip=None,
            root=root,
        )


class KernelLogger:
    """Base class for kernel loggers"""

    def __init__(self):
        pass

    def seek(self):
        """Seek to the beginning of the log"""

    def process_callback(self, callback):
        """Process the log"""

    def match_line(self, matches):
        """Find lines that match all matches"""

    def match_pattern(self, pattern):
        """Find lines that match a pattern"""

    def capture_full_dmesg(self, line):
        """Capture the full dmesg"""
        logging.debug(line)


class InputFile(KernelLogger):
    """Class for input file parsing"""

    def __init__(self, fname):
        self.since_support = False
        self.buffer = None
        self.seeked = False
        self.buffer = read_file(fname)

    def process_callback(self, callback):
        """Process the log"""
        for entry in self.buffer.split("\n"):
            callback(entry)


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
        logging.debug("Since support: %d", self.since_support)

        self.command = ["dmesg", "-t", "-k"]
        self._refresh_head()

    def _refresh_head(self):
        self.buffer = []
        self.seeked = False
        result = subprocess.run(self.command, check=True, capture_output=True)
        if result.returncode == 0:
            self.buffer = result.stdout.decode("utf-8")

    def seek(self, tim=None):
        """Seek to the beginning of the log"""
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
        elif self.seeked:
            self._refresh_head()

    def process_callback(self, callback):
        """Process the log"""
        for entry in self.buffer.split("\n"):
            callback(entry)

    def match_line(self, matches):
        """Find lines that match all matches"""
        for entry in self.buffer.split("\n"):
            for match in matches:
                if match not in entry:
                    break
                return entry
        return None

    def match_pattern(self, pattern):
        for entry in self.buffer.split("\n"):
            if re.search(pattern, entry):
                return entry
        return None

    def capture_full_dmesg(self, line=None):
        """Capture the full dmesg"""
        self.seek()
        for entry in self.buffer.split("\n"):
            super().capture_full_dmesg(entry)

    def capture_header(self):
        """Capture the header of the log"""
        return self.buffer.split("\n")[0]


class SystemdLogger(KernelLogger):
    """Class for logging using systemd journal"""

    def __init__(self):
        from systemd import journal  # pylint: disable=import-outside-toplevel

        self.journal = journal.Reader()
        self.journal.this_boot()
        self.journal.log_level(journal.LOG_INFO)
        self.journal.add_match(_TRANSPORT="kernel")
        self.journal.add_match(PRIORITY=journal.LOG_DEBUG)

    def seek(self, tim=None):
        """Seek to the beginning of the log"""
        if tim:
            self.journal.seek_realtime(tim)
        else:
            self.journal.seek_head()

    def process_callback(self, callback):
        """Process the log"""
        for entry in self.journal:
            callback(entry["MESSAGE"])

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

    def capture_full_dmesg(self, line=None):
        """Capture the full dmesg"""
        self.seek()
        for entry in self.journal:
            super().capture_full_dmesg(entry["MESSAGE"])


def read_file(fn):
    """Reads and returns the contents of fn"""
    with open(fn, "r", encoding="utf-8") as r:
        return r.read().strip()


def print_color(message, group):
    """Prints a message with a color"""
    prefix = f"{group} "
    suffix = Colors.ENDC
    if group == "🚦":
        color = Colors.WARNING
    elif any(mk in group for mk in ["🦟", "🖴"]):
        color = Colors.DEBUG
    elif any(mk in group for mk in ["❌", "👀", "🌡️"]):
        color = Colors.FAIL
    elif any(mk in group for mk in ["✅", "🔋", "🐧", "💻", "○", "💤", "🥱"]):
        color = Colors.OK
    else:
        color = group
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
    print_color(message, "👀")
    sys.exit(1)


class AmdBios:
    """
    AmdBios is a class which fetches the BIOS events from kernel logs.
    """

    def __init__(self, inf, kernel_log_provider):
        self.distro = None
        self.pretty_distro = None
        self.root_user = os.geteuid() == 0
        self.guess_distro()
        if inf:
            self.kernel_log = InputFile(inf)
        else:
            self.setup_kernel_log(kernel_log_provider)

    def setup_kernel_log(self, kernel_log):
        """Setup the kernel log provider"""
        self.kernel_log = None
        if kernel_log == "auto":
            init_daemon = read_file("/proc/1/comm")
            if "systemd" in init_daemon:
                try:
                    self.kernel_log = SystemdLogger()
                except ImportError:
                    self.kernel_log = None
                if not self.kernel_log:
                    self.show_install_message(Headers.MissingJournald)
                    package = JournaldPackage(self.root_user)
                    package.install(self.distro)
                    self.kernel_log = SystemdLogger()
            else:
                try:
                    self.kernel_log = DmesgLogger()
                except subprocess.CalledProcessError:
                    self.kernel_log = None
        elif kernel_log == "systemd":
            self.kernel_log = SystemdLogger()
        elif kernel_log == "dmesg":
            self.kernel_log = DmesgLogger()

    def show_install_message(self, message):
        """Show a message to install a package"""
        action = Headers.InstallAction if self.root_user else Headers.RerunAction
        message = f"{message}. {action}."
        print_color(message, "👀")

    def guess_distro(self):
        """Guess the distro based on heuristics"""
        self.distro = None
        self.pretty_distro = None

        if DISTRO:
            try:
                self.distro = distro.id()
                self.pretty_distro = distro.distro.os_release_info()["pretty_name"]
            except AttributeError:
                print_color("Failed to discover distro using python-distro", "🚦")

        if not self.distro or not self.pretty_distro:
            p = os.path.join("/", "etc", "os-release")
            if os.path.exists(p):
                v = read_file(p)
                for line in v.split("\n"):
                    if "ID=" in line:
                        self.distro = line.split("=")[-1].strip().strip('"')
                    if "PRETTY_NAME=" in line:
                        self.pretty_distro = line.split("=")[-1].strip().strip('"')
        if not self.distro:
            if os.path.exists("/etc/arch-release"):
                self.distro = "arch"
            elif os.path.exists("/etc/fedora-release"):
                self.distro = "fedora"
            elif os.path.exists("/etc/debian_version"):
                self.distro = "debian"

        if not self.distro:
            fatal_error("Unable to identify distro")

    def set_tracing(self, enable, disable):
        """Run the action"""

        if enable or disable:
            if not self.root_user:
                fatal_error("Please run this script as root")

        expected = {
            "trace_debug_layer": 0x80,
            "trace_debug_level": 0x10,
            "trace_method_name": "\\M460",
            "trace_state": "method",
        }
        actual = {}
        acpi_base = os.path.join("/", "sys", "module", "acpi", "parameters")
        for key, _value in expected.items():
            p = os.path.join(acpi_base, key)
            if not os.path.exists(p):
                fatal_error(
                    "BIOS tracing not supported, please check your kernel for CONFIG_ACPI_DEBUG"
                )
            actual[key] = read_file(p)
        logging.debug(actual)

        if enable:
            for key, value in expected.items():
                p = os.path.join(acpi_base, key)
                t = actual[key]
                if isinstance(value, int):
                    if int(actual[key]) & value:
                        continue
                    t = str(int(t) | value)
                else:
                    if actual[key].strip() == str(value):
                        continue
                with open(p, "w", encoding="utf-8") as w:
                    w.write(t)
            print_color("Enabled BIOS tracing", "✅")
        elif disable:
            p = os.path.join(acpi_base, "trace_state")
            with open(p, "w", encoding="utf-8") as w:
                w.write("disable")
            print_color("Disabled BIOS tracing", "✅")

    def _analyze_kernel_log_line(self, line):
        """Analyze a line from the kernel log"""
        if re.search(r"ex_trace_point", line):
            pass
        elif re.search(r"ex_trace_args", line):
            t = line.split(":", 1)[-1].strip()
            # extract format string using regex
            match = re.match(r"\"(.*?)\"(, .*)", t)
            if match:
                format_string = match.group(1)  # Format string inside quotes
                format_string = format_string.strip().strip("\\n")
                args_part = match.group(2).strip(", ")  # Remaining arguments

                # extract argument values
                arguments = args_part.split(", ")

                # extract format specifiers from the string
                format_specifiers = re.findall(
                    r"%[xXdD]", format_string
                )  # Adjusting case sensitivity

                converted_args = []
                for specifier, value in zip(format_specifiers, arguments):
                    if value == "Unknown":
                        converted_args.append(
                            -1
                        )  # Handle unknown values like ACPI Buffer
                        continue
                    if specifier.lower() == "%x":  # Hexadecimal conversion
                        converted_args.append(int(value, 16))
                    else:  # Decimal conversion
                        try:
                            converted_args.append(int(value))
                        except ValueError:
                            converted_args.append(
                                int(value, 16)
                            )  # Fallback to hex if decimal fails

                # apply formatting while ignoring extra unused zeros
                formatted_string = format_string % tuple(
                    converted_args[: len(format_specifiers)]
                )
                print_color(formatted_string, "🖴")
        else:
            # strip timestamp
            t = re.sub(r"^\[\s*\d+\.\d+\]", "", line).strip()
            print_color(t, "🐧")

    def run(self):
        """Exfiltrate from the kernel log"""
        self.kernel_log.process_callback(self._analyze_kernel_log_line)


def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Parse a combined kernel/BIOS log.",
    )
    parser.add_argument(
        "--log",
        help=Headers.LogDescription,
    )
    parser.add_argument(
        "--input",
        help="Optional input file to parse",
    )
    parser.add_argument(
        "--enable",
        action="store_true",
        help="Enable BIOS AML tracing",
    )
    parser.add_argument(
        "--disable",
        action="store_true",
        help="Disable BIOS AML tracing",
    )
    parser.add_argument(
        "--kernel-log-provider",
        default="auto",
        choices=["auto", "systemd", "dmesg"],
        help="Kernel log provider",
    )

    return parser.parse_args()


def configure_log(logf):
    """Configure the log file"""
    if not logf:
        fname = f"{Defaults.log_prefix}-{date.today()}.{Defaults.log_suffix}"
        logf = input(f"{Headers.LogDescription} (default {fname})? ")
        if not logf:
            logf = fname
    # for saving a log file for analysis
    logging.basicConfig(
        format="%(asctime)s %(levelname)s:\t%(message)s",
        filename=logf,
        filemode="w",
        level=logging.DEBUG,
    )


if __name__ == "__main__":
    args = parse_args()

    if args.enable and args.disable:
        raise ValueError("can't set both enable and disable")

    try:
        configure_log(args.log)
    except KeyboardInterrupt:
        print("")
        sys.exit(0)

    app = AmdBios(args.input, args.kernel_log_provider)
    if not args.input:
        app.set_tracing(args.enable, args.disable)
    if args.enable or args.disable:
        sys.exit(0)
    app.run()

#!/usr/bin/python3
# SPDX-License-Identifier: MIT
"""BIOS debug log control for AMD systems"""

import argparse
import logging
import os
import re
import sys

try:
    from amd_debug.common import (
        read_file,
        print_color,
        is_root,
        fatal_error,
        AmdTool,
    )
    from amd_debug.kernel_log import get_kernel_log
    from amd_debug.installer import Installer
except ModuleNotFoundError:
    sys.exit(
        f"\033[91m{sys.argv[0]} can not be run standalone.\n\033[0m\033[94mCheck out the full branch from git://git.kernel.org/pub/scm/linux/kernel/git/superm1/amd-debug-tools.git\033[0m"
    )

ACPI_METHOD = "M460"


class AmdBios(AmdTool):
    """
    AmdBios is a class which fetches the BIOS events from kernel logs.
    """

    def __init__(self, inf, log_file):
        super().__init__("bios", log_file)
        self.distro = None
        self.pretty_distro = None
        self.root_user = is_root()
        self.kernel_log = get_kernel_log(inf)

    def set_tracing(self, enable, disable):
        """Run the action"""

        def search_acpi_tables(pattern):
            """Search for a pattern in ACPI tables"""
            p = os.path.join("/", "sys", "firmware", "acpi", "tables")

            for fn in os.listdir(p):
                if not fn.startswith("SSDT") and not fn.startswith("DSDT"):
                    continue
                fp = os.path.join(p, fn)
                with open(fp, "rb") as file:
                    content = file.read()
                    if pattern.encode() in content:
                        return True
            return False

        if enable or disable:
            if not self.root_user:
                fatal_error("Please run this script as root")

        expected = {
            "trace_debug_layer": 0x80,
            "trace_debug_level": 0x10,
            "trace_method_name": f"\\{ACPI_METHOD}",
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
            # check that ACPI tables have \_SB.\M460
            if not search_acpi_tables(ACPI_METHOD):
                fatal_error(
                    f"{sys.argv[0]} will not work on this system: ACPI tables do not contain {ACPI_METHOD}"
                )
            for key, value in expected.items():
                p = os.path.join(acpi_base, key)
                t = actual[key]
                if isinstance(value, int):
                    if int(actual[key]) & value:
                        continue
                    t = str(int(t) | value)
                else:
                    t = value
                with open(p, "w", encoding="utf-8") as w:
                    w.write(t)
            print_color("Enabled BIOS tracing", "✅")
        elif disable:
            p = os.path.join(acpi_base, "trace_state")
            with open(p, "w", encoding="utf-8") as w:
                w.write("disable")
            print_color("Disabled BIOS tracing", "✅")

    def _analyze_kernel_log_line(self, line, _priority):
        """Analyze a line from the kernel log"""
        if re.search(r"ex_trace_point", line):
            pass
        elif re.search(r"ex_trace_args", line):
            t = line.split(": ")[-1].strip()
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
        installer = Installer()
        installer.set_requirements("journald")
        if not installer.install_dependencies():
            fatal_error("Failed to install dependencies")

        self.kernel_log.process_callback(self._analyze_kernel_log_line)


def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Parse a combined kernel/BIOS log.",
        epilog="If not arguments are provided the tool will parse log from a live system.",
    )
    parser.add_argument(
        "--log",
        help="Location of log file",
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

    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    if args.enable and args.disable:
        raise ValueError("can't set both enable and disable")

    app = AmdBios(args.input, args.log)
    if not args.input:
        app.set_tracing(args.enable, args.disable)
    if not args.enable and not args.disable:
        app.run()

#!/usr/bin/python3
# SPDX-License-Identifier: MIT
"""s2idle analysis tool"""
import argparse
import logging
import os
import re
import sys

from amd_debug.common import (
    AmdTool,
    fatal_error,
    get_log_priority,
    print_color,
    read_file,
    relaunch_sudo,
    show_log_info,
    version,
)
from amd_debug.kernel_log import get_kernel_log

ACPI_METHOD = "M460"


class AmdBios(AmdTool):
    """
    AmdBios is a class which fetches the BIOS events from kernel logs.
    """

    def __init__(self, inf, log_file):
        super().__init__("bios", log_file)
        self.distro = None
        self.pretty_distro = None
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
            relaunch_sudo()

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
                    if actual[key].strip() == str(value):
                        continue
                    t = value
                with open(p, "w", encoding="utf-8") as w:
                    w.write(t)
            print_color("Enabled BIOS tracing", "✅")
        elif disable:
            p = os.path.join(acpi_base, "trace_state")
            with open(p, "w", encoding="utf-8") as w:
                w.write("disable")
            print_color("Disabled BIOS tracing", "✅")
        return True

    def _analyze_kernel_log_line(self, line, priority):
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
            print_color(t, get_log_priority(priority))

    def run(self):
        """Exfiltrate from the kernel log"""
        self.kernel_log.process_callback(self._analyze_kernel_log_line)


def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Parse a combined kernel/BIOS log.",
    )
    subparsers = parser.add_subparsers(help="Possible commands", dest="command")
    parse_cmd = subparsers.add_parser(
        "parse", help="Parse log for kernel and BIOS messages"
    )
    parse_cmd.add_argument(
        "--input",
        help="Optional input file to parse",
    )
    parse_cmd.add_argument(
        "--log",
        help="Location of log file",
    )
    trace_cmd = subparsers.add_parser("trace", help="Enable or disable tracing")
    trace_cmd.add_argument(
        "--enable",
        action="store_true",
        help="Enable BIOS AML tracing",
    )
    trace_cmd.add_argument(
        "--disable",
        action="store_true",
        help="Disable BIOS AML tracing",
    )
    subparsers.add_parser("version", help="Show version information")

    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        sys.exit(1)

    return parser.parse_args()


def main():
    """Main function"""
    args = parse_args()
    if args.command == "trace":
        if args.enable and args.disable:
            sys.exit("can't set both enable and disable")
        if not args.enable and not args.disable:
            sys.exit("must set either enable or disable")
        app = AmdBios(None, None)
        app.set_tracing(args.enable, args.disable)
    elif args.command == "parse":
        app = AmdBios(args.input, args.log)
        app.run()
    elif args.command == "version":
        print(version())
    show_log_info()

#!/usr/bin/python3
# SPDX-License-Identifier: MIT
"""s2idle analysis tool"""
import argparse
import re
import sys
from amd_debug.common import (
    AmdTool,
    fatal_error,
    get_log_priority,
    minimum_kernel,
    print_color,
    relaunch_sudo,
    show_log_info,
    version,
)
from amd_debug.kernel import get_kernel_log, sscanf_bios_args
from amd_debug.acpi import AcpicaTracer
from amd_debug.args import parse_bios_args


class AmdBios(AmdTool):
    """
    AmdBios is a class which fetches the BIOS events from kernel logs.
    """

    def __init__(self, inf, debug):
        log_prefix = "bios" if debug else None
        super().__init__(log_prefix)
        self.kernel_log = get_kernel_log(inf)

    def set_tracing(self, enable):
        """Run the action"""
        relaunch_sudo()

        if not minimum_kernel(6, 16):
            print_color(
                "Support for BIOS debug logging was merged in mainline 6.16, "
                "this tool may not work correctly unless support is manually "
                "backported",
                "🚦",
            )

        tracer = AcpicaTracer()
        ret = tracer.trace_bios() if enable else tracer.disable()
        if ret:
            action = "enabled" if enable else "disabled"
            print_color(f"Set BIOS tracing to {action}", "✅")
        else:
            fatal_error(
                "BIOS tracing not supported, please check your kernel for CONFIG_ACPI_DEBUG"
            )

        return True

    def _analyze_kernel_log_line(self, line, priority):
        """Analyze a line from the kernel log"""
        bios_args = sscanf_bios_args(line)
        if bios_args:
            if isinstance(bios_args, str):
                print_color(bios_args, "🖴")
            else:
                return
        else:
            # strip timestamp
            t = re.sub(r"^\[\s*\d+\.\d+\]", "", line).strip()
            print_color(t, get_log_priority(priority))

    def run(self):
        """Exfiltrate from the kernel log"""
        self.kernel_log.process_callback(self._analyze_kernel_log_line)
        return True


def main():
    """Main function"""
    args = parse_bios_args()
    ret = False
    if args.command == "trace":
        app = AmdBios(None, args.tool_debug)
        ret = app.set_tracing(True if args.enable else False)
    elif args.command == "parse":
        app = AmdBios(args.input, args.tool_debug)
        ret = app.run()
    elif args.command == "version":
        print(version())
    show_log_info()
    return ret

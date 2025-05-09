#!/usr/bin/python3
# SPDX-License-Identifier: MIT
"""s2idle analysis tool"""
import argparse
import sys

from datetime import date, timedelta


class Defaults:
    """Default values for the script"""

    duration = 10
    wait = 4
    count = 1
    since = date.today() - timedelta(days=60)
    until = date.today() + timedelta(days=1)
    format_choices = ["txt", "md", "html", "stdout"]


class Headers:
    """Headers for the script"""

    DurationDescription = "How long should suspend cycles last (seconds)"
    WaitDescription = "How long to wait in between suspend cycles (seconds)"
    CountDescription = "How many suspend cycles to run"
    SinceDescription = "What date to start report data"
    UntilDescription = "What date to end report data"
    LogDescription = "Location of log file"
    ReportFileDescription = "Location of report file"
    FormatDescription = "What format to output the report in"
    MaxDurationDescription = "What is the maximum suspend cycle length (seconds)"
    MaxWaitDescription = "What is the maximum time between suspend cycles (seconds)"


def parse_s2idle_args(help_on_empty=False) -> argparse.Namespace:
    """Parse command line arguments for s2idle tool"""
    parser = argparse.ArgumentParser(
        description="Swiss army knife for analyzing Linux s2idle problems",
        epilog="The tool can run an immediate test with the 'test' command or can be used to hook into systemd for building reports later.\n"
        "All optional arguments will be prompted if needed.\n"
        "To use non-interactively, please populate all optional arguments.",
    )
    subparsers = parser.add_subparsers(help="Possible commands", dest="action")

    # 'test' command
    test_cmd = subparsers.add_parser("test", help="Run amd-s2idle test and report")
    test_cmd.add_argument("--count", help=Headers.CountDescription)
    test_cmd.add_argument(
        "--duration",
        help=Headers.DurationDescription,
    )
    test_cmd.add_argument(
        "--wait",
        help=Headers.WaitDescription,
    )
    test_cmd.add_argument(
        "--logind", action="store_true", help="Use logind to suspend system"
    )
    test_cmd.add_argument(
        "--random",
        action="store_true",
        help="Run sleep cycles for random durations and wait, using the --duration and --wait arguments as an upper bound",
    )
    test_cmd.add_argument(
        "--force",
        action="store_true",
        help="Run suspend test even if prerequisites failed",
    )
    test_cmd.add_argument(
        "--format",
        choices=Defaults.format_choices,
        help="Report format",
    )
    test_cmd.add_argument(
        "--tool-debug",
        action="store_true",
        help="Enable tool debug logging",
    )
    test_cmd.add_argument(
        "--bios-debug",
        action="store_true",
        help="Enable BIOS debug logging instead of notify logging",
    )
    test_cmd.add_argument("--report-file", help=Headers.ReportFileDescription)

    # 'report' command
    report_cmd = subparsers.add_parser(
        "report", help="Generate amd-s2idle report from previous runs"
    )
    report_cmd.add_argument(
        "--since",
        help=Headers.SinceDescription,
    )
    report_cmd.add_argument(
        "--until",
        default=Defaults.until.isoformat(),
        help=Headers.UntilDescription,
    )
    report_cmd.add_argument("--report-file", help=Headers.ReportFileDescription)
    report_cmd.add_argument(
        "--format",
        choices=Defaults.format_choices,
        help="Report format",
    )
    report_cmd.add_argument(
        "--tool-debug",
        action="store_true",
        help="Enable tool debug logging",
    )
    report_cmd.add_argument(
        "--report-debug",
        action="store_true",
        help="Include debug messages in report (WARNING: can significantly increase report size)",
    )

    # if running in a venv, install/uninstall hook options
    if sys.prefix != sys.base_prefix:
        install_cmd = subparsers.add_parser(
            "install", help="Install systemd s2idle hook"
        )
        uninstall_cmd = subparsers.add_parser(
            "uninstall", help="Uninstall systemd s2idle hook"
        )
        install_cmd.add_argument(
            "--tool-debug",
            action="store_true",
            help="Enable tool debug logging",
        )
        uninstall_cmd.add_argument(
            "--tool-debug",
            action="store_true",
            help="Enable tool debug logging",
        )

    subparsers.add_parser("version", help="Show version information")

    if len(sys.argv) == 1 and help_on_empty:
        parser.print_help(sys.stderr)
        sys.exit(1)

    return parser.parse_args()


def parse_pstate_args(help_on_empty=False) -> argparse.Namespace:
    """Parse command line arguments for pstate tool."""
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

    if len(sys.argv) == 1 and help_on_empty:
        parser.print_help(sys.stderr)
        sys.exit(1)
    return parser.parse_args()


def parse_bios_args(help_on_empty=False) -> argparse.Namespace:
    """Parse command line arguments for bios tool."""
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
        "--tool-debug",
        action="store_true",
        help="Enable tool debug logging",
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
    trace_cmd.add_argument(
        "--tool-debug",
        action="store_true",
        help="Enable tool debug logging",
    )
    subparsers.add_parser("version", help="Show version information")

    if len(sys.argv) == 1 and help_on_empty:
        parser.print_help(sys.stderr)
        sys.exit(1)

    args = parser.parse_args()

    if args.command == "trace":
        if args.enable and args.disable:
            sys.exit("can't set both enable and disable")
        if not args.enable and not args.disable:
            sys.exit("must set either enable or disable")

    return args

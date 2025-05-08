#!/usr/bin/python3
# SPDX-License-Identifier: MIT
"""s2idle analysis tool"""
import argparse
import sys
import os
import subprocess
import sqlite3

from datetime import date, timedelta, datetime
from amd_debug.common import is_root, relaunch_sudo, show_log_info, version, running_ssh

from amd_debug.validator import SleepValidator
from amd_debug.installer import Installer
from amd_debug.prerequisites import PrerequisiteValidator
from amd_debug.sleep_report import SleepReport


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


def display_report_file(fname, fmt) -> None:
    """Display report file"""
    if fmt != "html":
        return
    if not is_root():
        subprocess.call(["xdg-open", fname])
        return
    user = os.environ.get("SUDO_USER")
    if user:
        # ensure that xdg tools will know how to display the file (user may need to call tool with sudo -E)
        if os.environ.get("XDG_SESSION_TYPE"):
            subprocess.call(["sudo", "-E", "-u", user, "xdg-open", fname])
        else:
            print(
                f"To display report automatically in browser launch tool with '-E' argument (Example: sudo -E {sys.argv[0]})"
            )


def get_report_file(report_file, extension) -> str:
    """Prompt user for report file"""
    if extension == "stdout":
        return None
    if not report_file:
        return f"amd-s2idle-report-{date.today()}.{extension}"
    return report_file


def get_report_format() -> str:
    """Get report format"""
    if running_ssh():
        return "txt"
    return "html"


def prompt_report_arguments(since, until, fname, fmt) -> str:
    """Prompt user for report configuration"""
    if not since:
        default = Defaults.since
        since = input(f"{Headers.SinceDescription} (default {default})? ")
        if not since:
            since = default.isoformat()
    try:
        since = datetime.fromisoformat(since)
    except ValueError as e:
        sys.exit(f"Invalid date, use YYYY-MM-DD: {e}")
    if not until:
        default = Defaults.until
        until = input(f"{Headers.SinceDescription} (default {default})? ")
        if not until:
            until = default.isoformat()
    try:
        until = datetime.fromisoformat(until)
    except ValueError as e:
        sys.exit(f"Invalid date, use YYYY-MM-DD: {e}")

    if not fmt:
        fmt = input(f"{Headers.FormatDescription} (default {get_report_format()})? ")
        if not fmt:
            fmt = get_report_format()
        if fmt not in Defaults.format_choices:
            sys.exit(f"Invalid format: {fmt}")
    return [since, until, get_report_file(fname, fmt), fmt]


def prompt_test_arguments(duration, wait, count, rand) -> list:
    """Prompt user for test configuration"""
    if not duration:
        if rand:
            question = Headers.MaxDurationDescription
        else:
            question = Headers.DurationDescription
        duration = input(f"{question} (default {Defaults.duration})? ")
        if not duration:
            duration = Defaults.duration
    try:
        duration = int(duration)
    except ValueError as e:
        sys.exit(f"Invalid duration: {e}")
    if not wait:
        if rand:
            question = Headers.MaxWaitDescription
        else:
            question = Headers.WaitDescription
        wait = input(f"{question} (default {Defaults.wait})? ")
        if not wait:
            wait = Defaults.wait
    try:
        wait = int(wait)
    except ValueError as e:
        sys.exit(f"Invalid wait: {e}")
    if not count:
        count = input(f"{Headers.CountDescription} (default {Defaults.count})? ")
        if not count:
            count = Defaults.count
    try:
        count = int(count)
    except ValueError as e:
        sys.exit(f"Invalid count: {e}")
    return [duration, wait, count]


def report(since, until, fname, fmt, tool_debug, report_debug) -> bool:
    """Generate a report from previous sleep cycles"""
    try:
        since, until, fname, fmt = prompt_report_arguments(since, until, fname, fmt)
    except KeyboardInterrupt:
        sys.exit("\nReport generation cancelled")
    try:
        app = SleepReport(
            since=since,
            until=until,
            fname=fname,
            fmt=fmt,
            tool_debug=tool_debug,
            report_debug=report_debug,
        )
    except sqlite3.OperationalError as e:
        print(f"Failed to generate report: {e}")
        return False
    except PermissionError as e:
        print(f"Failed to generate report: {e}")
        return False
    try:
        app.run()
    except PermissionError as e:
        print(f"Failed to generate report: {e}")
        return False
    except ValueError as e:
        print(f"Failed to generate report: {e}")
        return False
    display_report_file(fname, fmt)
    return True


def test(
    duration, wait, count, fmt, fname, force, debug, rand, logind, bios_debug
) -> bool:
    """Run a test"""
    app = Installer(tool_debug=debug)
    app.set_requirements("iasl", "ethtool")
    if not app.install_dependencies():
        print("Failed to install dependencies")
        return False

    try:
        app = PrerequisiteValidator(debug)
        run = app.run()
    except PermissionError as e:
        print(f"Failed to run prerequisite check: {e}")
        return False
    app.report()

    if run or force:
        app = SleepValidator(tool_debug=debug, bios_debug=bios_debug)
        try:
            duration, wait, count = prompt_test_arguments(duration, wait, count, rand)
            since, until, fname, fmt = prompt_report_arguments(
                datetime.now().isoformat(), Defaults.until.isoformat(), fname, fmt
            )
        except KeyboardInterrupt:
            sys.exit("\nTest cancelled")

        app.run(
            duration=duration,
            wait=wait,
            count=count,
            rand=rand,
            logind=logind,
        )

        app = SleepReport(
            since=since,
            until=until,
            fname=fname,
            fmt=fmt,
            tool_debug=debug,
            report_debug=True,
        )
        app.run()

        # open report in browser if it's html
        display_report_file(fname, fmt)

        return True
    return False


def install(debug) -> None:
    """Install the tool"""
    installer = Installer(tool_debug=debug)
    installer.set_requirements("iasl", "ethtool")
    if not installer.install_dependencies():
        sys.exit("Failed to install dependencies")
    try:
        app = PrerequisiteValidator(debug)
        run = app.run()
    except PermissionError as e:
        sys.exit(f"Failed to run prerequisite check: {e}")
    if not run:
        app.report()
        sys.exit("Failed to meet prerequisites")

    if not installer.install():
        sys.exit("Failed to install")


def uninstall(debug) -> None:
    """Uninstall the tool"""
    app = Installer(tool_debug=debug)
    if not app.remove():
        sys.exit("Failed to remove")


def parse_args():
    """Parse command line arguments"""
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

    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        sys.exit(1)

    return parser.parse_args()


def main():
    """Main function"""
    args = parse_args()
    ret = False
    if args.action == "install":
        relaunch_sudo()
        install(args.tool_debug)
    elif args.action == "uninstall":
        relaunch_sudo()
        uninstall(args.tool_debug)
    elif args.action == "report":
        ret = report(
            args.since,
            args.until,
            args.report_file,
            args.format,
            args.tool_debug,
            args.report_debug,
        )
    elif args.action == "test":
        relaunch_sudo()
        ret = test(
            args.duration,
            args.wait,
            args.count,
            args.format,
            args.report_file,
            args.force,
            args.tool_debug,
            args.random,
            args.logind,
            args.bios_debug,
        )
    elif args.action == "version":
        print(version())
        return True
    else:
        sys.exit("no action specified")
    show_log_info()
    return ret

#!/usr/bin/python3
# SPDX-License-Identifier: MIT
"""s2idle analysis tool"""
import argparse
import sys
import os
import importlib.metadata
import subprocess
import sqlite3

from datetime import date, timedelta, datetime
from amd_debug.common import is_root, relaunch_sudo, show_log_info

from amd_debug.validator import SleepValidator
from amd_debug.installer import Installer
from amd_debug.prerequisites import PrerequisiteValidator
from amd_debug.sleep_report import SleepReport


class Defaults:
    """Default values for the script"""

    duration = 10
    wait = 4
    count = 1
    format = "html"
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
        fmt = input(f"{Headers.FormatDescription} (default {Defaults.format})? ")
        if not fmt:
            fmt = Defaults.format
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


def report(since, until, fname, fmt, debug, log) -> None:
    """Generate a report from previous sleep cycles"""
    try:
        since, until, fname, fmt = prompt_report_arguments(since, until, fname, fmt)
    except KeyboardInterrupt:
        sys.exit("\nReport generation cancelled")
    try:
        app = SleepReport(
            since=since, until=until, fname=fname, fmt=fmt, debug=debug, log_file=log
        )
    except sqlite3.OperationalError as e:
        sys.exit(f"Failed to generate report: {e}")
    except PermissionError as e:
        sys.exit(f"Failed to generate report: {e}")
    try:
        app.run()
    except PermissionError as e:
        sys.exit(f"Failed to generate report: {e}")
    except ValueError as e:
        sys.exit(f"Failed to generate report: {e}")
    display_report_file(fname, fmt)


def test(duration, wait, count, fmt, fname, force, debug, rand, logind, log) -> None:
    """Run a test"""
    app = Installer()
    app.set_requirements("iasl", "ethtool")
    if not app.install_dependencies():
        sys.exit("Failed to install dependencies")

    try:
        app = PrerequisiteValidator(log_file=log, debug=debug)
        run = app.run()
    except PermissionError as e:
        sys.exit(f"Failed to run prerequisite check: {e}")
    app.report()

    if run or force:
        app = SleepValidator(log_file=log, debug=debug)
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
            since=since, until=until, fname=fname, fmt=fmt, log_file=log, debug=True
        )
        app.run()

        # open report in browser if it's html
        display_report_file(fname, fmt)

        return True
    return False


def install(log) -> None:
    """Install the tool"""
    installer = Installer()
    installer.set_requirements("iasl", "ethtool")
    if not installer.install_dependencies():
        sys.exit("Failed to install dependencies")
    try:
        app = PrerequisiteValidator(log_file=log, debug=False)
        run = app.run()
    except PermissionError as e:
        sys.exit(f"Failed to run prerequisite check: {e}")
    if not run:
        app.report()
        sys.exit("Failed to meet prerequisites")

    if not installer.install():
        sys.exit("Failed to install")


def uninstall() -> None:
    """Uninstall the tool"""
    app = Installer()
    if not app.remove():
        sys.exit("Failed to remove")


def version() -> str:
    """Get version of the tool"""
    return importlib.metadata.version("amd-debug-tools")


def parse_args(packaged):
    """Parse command line arguments"""
    choices = ["report", "test", "version"]
    if not packaged:
        choices.append("install")
        choices.append("uninstall")

    parser = argparse.ArgumentParser(
        description=f"Swiss army knife for analyzing Linux s2idle problems (version {version()})",
        epilog="The tool can run an immediate test with the 'test' command or can be used to hook into systemd for building reports later.\n"
        "All optional arguments will be prompted if needed.\n"
        "To use non-interactively, please populate all optional arguments.",
    )
    parser.add_argument(
        "action",
        choices=choices,
        help="Action to perform",
    )
    parser.add_argument("--count", help=Headers.CountDescription)
    parser.add_argument(
        "--log",
        help=Headers.LogDescription,
    )
    parser.add_argument(
        "--duration",
        help=Headers.DurationDescription,
    )
    parser.add_argument(
        "--wait",
        help=Headers.WaitDescription,
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Run suspend test even if prerequisites failed",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Display report debug data",
    )
    parser.add_argument(
        "--since",
        help=Headers.SinceDescription,
    )
    parser.add_argument(
        "--until",
        default=Defaults.until.isoformat(),
        help=Headers.UntilDescription,
    )
    parser.add_argument("--report-file", help=Headers.ReportFileDescription)
    parser.add_argument(
        "--format",
        choices=Defaults.format_choices,
        default=Defaults.format,
        help="Report format",
    )
    parser.add_argument(
        "--random",
        action="store_true",
        help="Run sleep cycles for random durations and wait, using the --duration and --wait arguments as an upper bound",
    )
    parser.add_argument(
        "--logind", action="store_true", help="Use logind to suspend system"
    )

    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        sys.exit(1)

    return parser.parse_args()


def main(packaged):
    """Main function"""
    args = parse_args(packaged)
    if args.force and args.action != "test":
        sys.exit("Force can only be used with test")
    if args.since and args.action != "report":
        sys.exit("Since can only be used with report")
    if args.action == "install":
        relaunch_sudo()
        install(args.log)
    elif args.action == "uninstall":
        relaunch_sudo()
        uninstall()
    elif args.action == "report":
        report(
            args.since, args.until, args.report_file, args.format, args.debug, args.log
        )
    elif args.action == "test":
        relaunch_sudo()
        test(
            args.duration,
            args.wait,
            args.count,
            args.format,
            args.report_file,
            args.force,
            args.debug,
            args.random,
            args.logind,
            args.log,
        )
    elif args.action == "version":
        print(version())
    else:
        sys.exit("no action specified")
    show_log_info()

#!/usr/bin/python3
# SPDX-License-Identifier: MIT
"""s2idle analysis tool"""
import sys
import os
import subprocess
import sqlite3

from datetime import date, datetime
from amd_debug.common import is_root, relaunch_sudo, show_log_info, version, running_ssh

from amd_debug.validator import SleepValidator
from amd_debug.installer import Installer
from amd_debug.prerequisites import PrerequisiteValidator
from amd_debug.sleep_report import SleepReport
from amd_debug.args import Defaults, Headers, parse_s2idle_args


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


def run_test_cycle(
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


def main():
    """Main function"""
    args = parse_s2idle_args(help_on_empty=True)
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
        ret = run_test_cycle(
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

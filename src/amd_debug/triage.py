# SPDX-License-Identifier: MIT
"""Guided triage for s2idle hangs

Some s2idle problems hang the machine, so the tool can't finish and report
on its own.  Triage mode runs an interview with the user across several
invocations.  Progress is stored in the database before every risky step, so
when the user runs the tool again after resetting the hung machine it knows
what was being tested and what to ask them to change next.
"""

import os
import stat
import sys
from typing import Optional
from datetime import date, datetime, timedelta

from amd_debug.common import print_color, read_file
from amd_debug.database import SleepDatabase
from amd_debug.installer import Installer
from amd_debug.prereq import get_validator
from amd_debug.sleep_report import SleepReport
from amd_debug.validator import SleepValidator

# A single successful suspend cycle is all triage needs
CYCLE_DURATION = 10
CYCLE_WAIT = 4


class Stage:
    """Triage stages, in the order they are attempted"""

    BASELINE = "baseline"
    BIOS_DEFAULTS = "bios_defaults"
    IOMMU = "iommu"


class Status:
    """What the tool was doing in a stage when it last stored progress"""

    READY = "ready"  # about to run the test for the stage
    CHANGE_PENDING = "change_pending"  # waiting for the user to change something
    PREREQ_FAILED = "prereq_failed"  # user needs to fix prerequisites
    RUNNING = "running"  # test started, never finished => probably hung


# stage to move to when the test hangs in a stage
NEXT_STAGE = {
    Stage.BASELINE: Stage.BIOS_DEFAULTS,
    Stage.BIOS_DEFAULTS: Stage.IOMMU,
    Stage.IOMMU: None,
}

STAGE_TITLES = {
    Stage.BASELINE: "Baseline (current configuration)",
    Stage.BIOS_DEFAULTS: "BIOS reset to default settings",
    Stage.IOMMU: "IOMMU disabled",
}

INTRO = """\
This is the amd-s2idle triage mode.

Some s2idle problems make the system hang, which means the tool can't
analyze them itself.  Triage mode helps to narrow down the cause by
interviewing you across several runs:

  1. The prerequisite checks and an s2idle test are run on the current
     configuration.  If the prerequisites fail you will be told what to fix.
  2. If the system hangs, reset it and run `amd-s2idle triage` again.  The
     tool remembers where it was and will ask you to reset the BIOS to its
     default settings, then runs the test again.
  3. If it hangs again, you will be asked to disable the IOMMU (in the BIOS
     or on the kernel command line) and the test is run once more.

Progress is kept in the amd-s2idle database.  Once the test completes, or
every step has been tried, a triage report is generated that lists
everything you tried, the questions you were asked and the s2idle report.

WARNING: the system may hang during the test.  Save your work first.
"""

BIOS_DEFAULTS_INSTRUCTIONS = """\
The test hung with the current configuration.  The next step is to rule out
a BIOS setting that was changed from its default.

  1. Reboot and enter the BIOS setup.
  2. Load the default settings (usually called "Load Setup Defaults",
     "Load Optimized Defaults" or "Restore Defaults").
  3. Save and exit.

Don't re-apply any custom BIOS settings until the triage is finished.  If
you can, also make sure the BIOS is updated to the latest version, but
do that as a separate triage run since it changes more than one thing.
"""

IOMMU_INSTRUCTIONS = """\
The test hung again with the BIOS at default settings.  The next step is to
rule out the IOMMU.  Disable it using either of these methods:

  * BIOS: disable "IOMMU" in the BIOS setup (usually under
    Advanced -> AMD CBS -> NBIO Common Options).
  * Kernel command line: add `amd_iommu=off` to the boot parameters
    (for example in /etc/default/grub), regenerate your bootloader
    configuration and reboot.

Then run `amd-s2idle triage` again.
"""

INSTRUCTIONS = {
    Stage.BIOS_DEFAULTS: BIOS_DEFAULTS_INSTRUCTIONS,
    Stage.IOMMU: IOMMU_INSTRUCTIONS,
}

DMI_FIELDS = [
    ("Vendor", "sys_vendor"),
    ("Product", "product_name"),
    ("BIOS vendor", "bios_vendor"),
    ("BIOS version", "bios_version"),
    ("BIOS date", "bios_date"),
]


def get_boot_id() -> str:
    """Identifier that changes on every boot"""
    try:
        return read_file("/proc/sys/kernel/random/boot_id").strip() or "unknown"
    except OSError:
        return "unknown"


def iommu_disabled() -> bool:
    """Check if the IOMMU is disabled for this boot"""
    try:
        cmdline = read_file("/proc/cmdline").split()
    except OSError:
        cmdline = []
    if "amd_iommu=off" in cmdline or "iommu=off" in cmdline:
        return True
    try:
        return not os.listdir("/sys/class/iommu")
    except FileNotFoundError:
        # no IOMMU class devices at all: no IOMMU driver bound
        return True
    except OSError:
        # can't tell
        return False


def get_dmi_info() -> list:
    """Get (label, value) pairs identifying the system and BIOS"""
    info = []
    for label, name in DMI_FIELDS:
        try:
            info.append((label, read_file(f"/sys/class/dmi/id/{name}").strip()))
        except OSError:
            continue
    return info


def format_ts(ts) -> str:
    """Convert a database timestamp to something readable"""
    try:
        return datetime.strptime(str(ts), "%Y%m%d%H%M%S").strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return str(ts)


class Triage:
    """Interview driven s2idle hang triage"""

    def __init__(
        self,
        fmt,
        fname,
        debug,
        ask=input,
    ) -> None:
        self.fmt = fmt if fmt in ("txt", "md") else "txt"
        self.fname = fname
        self.debug = debug
        self.ask = ask
        self.db = SleepDatabase()
        self.session = None

    # -- helpers ---------------------------------------------------------

    def say(self, message, group="○") -> None:
        """Show a message to the user"""
        print_color(message, group)

    def say_block(self, text) -> None:
        """Show a block of text"""
        print(text)

    def log(self, kind, message, answer=None) -> None:
        """Record an event in the triage history"""
        self.db.triage_log(self.session["id"], kind, message, answer)

    def question(self, prompt, default=True) -> bool:
        """Ask a yes/no question and record it and the answer"""
        hint = "Y/n" if default else "y/N"
        try:
            reply = self.ask(f"{prompt} ({hint})? ").strip().lower()
        except EOFError:
            reply = ""
        if not reply:
            answer = default
        else:
            answer = reply in ("y", "yes")
        self.log("question", prompt, "yes" if answer else "no")
        return answer

    def set_status(self, status=None, stage=None, boot_id=None) -> None:
        """Store progress and keep the cached session up to date"""
        self.db.triage_update(self.session["id"], stage, status, boot_id)
        self.session = self.db.triage_get(self.session["id"])

    # -- steps -----------------------------------------------------------

    def start(self) -> bool:
        """Explain triage mode and begin a new session"""
        self.say_block(INTRO)
        try:
            reply = self.ask("Do you want to proceed (y/N)? ").strip().lower()
        except EOFError:
            reply = ""
        if reply not in ("y", "yes"):
            self.say("Triage cancelled")
            return False
        sid = self.db.triage_start(Stage.BASELINE, get_boot_id())
        self.session = self.db.triage_get(sid)
        self.log("info", "Triage started")
        for label, value in get_dmi_info():
            self.log("info", f"{label}: {value}")
        return True

    def resume(self, session) -> bool:
        """Continue a triage session from a previous run"""
        self.session = session
        stage = session["stage"]
        self.say(
            f"Resuming triage started {format_ts(session['started'])}, "
            f"step: {STAGE_TITLES[stage]}",
            "🚦",
        )
        if session["status"] == Status.RUNNING:
            return self.handle_interrupted_test()
        return True

    def handle_interrupted_test(self) -> bool:
        """The last test never finished; find out why and move on"""
        stage = self.session["stage"]
        if get_boot_id() == self.session["boot_id"]:
            # No reboot since the test started so the system didn't hang;
            # the tool was killed or it is still running elsewhere.
            self.say(
                "The previous test was interrupted but the system wasn't "
                "reset, so it didn't hang.",
                "🚦",
            )
            self.log("result", f"{STAGE_TITLES[stage]}: test interrupted, no reboot")
            self.set_status(Status.READY)
            return True
        hung = self.question(
            "The previous s2idle test didn't finish. "
            "Did the system hang and need to be reset",
        )
        if not hung:
            self.log("result", f"{STAGE_TITLES[stage]}: test interrupted by the user")
            self.set_status(Status.READY)
            return True
        self.log("result", f"{STAGE_TITLES[stage]}: system hung")
        nxt = NEXT_STAGE[stage]
        if nxt is None:
            self.conclude("hang_persists")
            return False
        self.set_status(Status.CHANGE_PENDING, stage=nxt, boot_id="")
        return True

    def guide_change(self) -> bool:
        """Walk the user through the change needed for the current stage"""
        stage = self.session["stage"]
        # The instructions are only shown once; remember the boot that they
        # were shown on to verify the system was rebooted afterwards.
        if not self.session["boot_id"]:
            self.say_block(INSTRUCTIONS[stage])
            self.log("action", f"Asked to change: {STAGE_TITLES[stage]}")
            self.set_status(boot_id=get_boot_id())
            self.say("Make the change, reboot and run `amd-s2idle triage` again.", "🚦")
            return False

        if get_boot_id() == self.session["boot_id"]:
            self.say(
                "The system hasn't been rebooted since the instructions were shown, "
                "so the change can't be in effect yet.",
                "❌",
            )
            self.say(
                "Make the change, reboot and run `amd-s2idle triage` again "
                "(or use --restart to start over).",
                "🚦",
            )
            return False

        if stage == Stage.IOMMU:
            if not iommu_disabled():
                self.say("The IOMMU still appears to be enabled.", "❌")
                self.log("result", "IOMMU still enabled after reboot")
                if not self.question("Do you want to run the test anyway", False):
                    self.say_block(IOMMU_INSTRUCTIONS)
                    return False
            else:
                self.say("Verified the IOMMU is disabled", "✅")
                self.log("result", "Verified IOMMU is disabled")
        else:
            # BIOS settings can't be read back, so rely on what the user says
            if not self.question(
                "Did you load the BIOS default settings and save them"
            ):
                self.say_block(INSTRUCTIONS[stage])
                return False
        self.log("action", f"Change applied: {STAGE_TITLES[stage]}")
        self.set_status(Status.READY)
        return True

    def run_prereqs(self) -> bool:
        """Run the prerequisite checks; tell the user what to fix on failure"""
        try:
            app = get_validator(self.debug)
            passed = app.run()
        except PermissionError as e:
            self.say(f"Failed to run prerequisite check: {e}", "❌")
            self.log("result", f"Prerequisite check could not run: {e}")
            return False
        app.report()
        if passed:
            self.log("result", "Prerequisites passed")
            return True
        ts = self.db.get_last_prereq_ts()
        try:
            rows = self.db.report_prereq(datetime.strptime(str(ts), "%Y%m%d%H%M%S"))
        except ValueError:
            rows = []
        problems = [r[2] for r in rows if r[3] in ("❌", "🚫")]
        self.log(
            "result",
            "Prerequisites failed:\n" + "\n".join(f"  - {p}" for p in problems),
        )
        if self.session["stage"] != Stage.BASELINE:
            # a change made for triage can cause a prerequisite to fail
            # (e.g. the NPU needs the IOMMU), don't let that block the test
            self.say("Continuing with the test despite the failures", "🚦")
            return True
        self.say(
            "The prerequisite checks failed. Fix the errors above, then run "
            "`amd-s2idle triage` again.",
            "🚦",
        )
        self.set_status(Status.PREREQ_FAILED)
        return False

    def run_test(self) -> bool:
        """Run the s2idle test with progress stored for hang detection"""
        stage = self.session["stage"]
        # Stored (and committed) before the suspend; if the system hangs
        # this is how the next run knows.
        self.set_status(Status.RUNNING, boot_id=get_boot_id())
        self.log("action", f"Running s2idle test: {STAGE_TITLES[stage]}")
        self.say(
            "Starting the s2idle test. If the system hangs, reset it and "
            "run `amd-s2idle triage` again.",
            "🚦",
        )
        try:
            app = SleepValidator(tool_debug=self.debug, bios_debug=False)
            ok = app.run(
                duration=CYCLE_DURATION,
                wait=CYCLE_WAIT,
                count=1,
                rand=False,
                logind=False,
            )
        except KeyboardInterrupt:
            self.log("result", f"{STAGE_TITLES[stage]}: test cancelled by the user")
            self.set_status(Status.READY)
            self.say("Test cancelled", "🚦")
            return False
        except Exception as e:
            # a crash isn't a hang, don't let the next run mistake it for one
            self.log("result", f"{STAGE_TITLES[stage]}: test failed to run: {e}")
            self.set_status(Status.READY)
            raise
        if not ok:
            self.log("result", f"{STAGE_TITLES[stage]}: test didn't complete a suspend")
            self.set_status(Status.READY)
            self.say(
                "The test failed before suspending, so it can't be used for "
                "triage. Fix the errors above and run `amd-s2idle triage` again.",
                "❌",
            )
            return False
        self.log("result", f"{STAGE_TITLES[stage]}: test completed without hanging")
        if stage == Stage.BASELINE:
            self.conclude("no_hang")
        else:
            self.conclude("fixed_by_" + stage)
        return True

    def conclude(self, outcome) -> None:
        """Finish the session and build the triage report"""
        self.db.triage_complete(self.session["id"], outcome)
        self.session = self.db.triage_get(self.session["id"])
        self.build_report()

    # -- report ----------------------------------------------------------

    OUTCOMES = {
        "no_hang": (
            "The system did not hang with the current configuration. Any "
            "issues found by the test are in the s2idle report below."
        ),
        "fixed_by_"
        + Stage.BIOS_DEFAULTS: (
            "The hang went away after resetting the BIOS to default settings. "
            "A BIOS setting changed from its default is the likely cause. "
            "Re-apply custom settings one at a time to find which one. If "
            "the settings were never changed, report this to the system "
            "vendor as a BIOS problem."
        ),
        "fixed_by_"
        + Stage.IOMMU: (
            "The hang went away after disabling the IOMMU. This points to an "
            "IOMMU related problem in the platform firmware (IVRS/ACPI tables "
            "or the BIOS) or the Linux IOMMU driver. Report it including this "
            "report."
        ),
        "hang_persists": (
            "The system still hung with the BIOS at default settings and the "
            "IOMMU disabled. The common BIOS configuration and IOMMU causes "
            "are ruled out. Further investigation is needed on the EC/BIOS "
            "firmware and Linux kernel/driver side; attach this report to "
            "the bug report."
        ),
        "abandoned": "The triage was abandoned before it finished.",
    }

    def format_history(self, session) -> str:
        """Render the history of what was tried and asked"""
        lines = [
            "Triage history",
            f"Started: {format_ts(session['started'])}",
            f"Finished: {format_ts(session['updated'])}",
            "",
        ]
        for ts, kind, message, answer in self.db.triage_events(session["id"]):
            prefix = {
                "question": "Q",
                "action": "Action",
                "result": "Result",
                "info": "Info",
            }.get(kind, kind)
            lines.append(f"[{format_ts(ts)}] {prefix}: {message}")
            if answer is not None:
                lines.append(f"    A: {answer}")
        lines.append("")
        lines.append("Conclusion")
        lines.append(self.OUTCOMES.get(session["outcome"], session["outcome"] or ""))
        return "\n".join(lines)

    def pick_filename(self) -> str:
        """Pick the output file without overwriting anything"""
        if self.fname:
            root, ext = os.path.splitext(self.fname)
        else:
            root, ext = f"amd-s2idle-triage-{date.today()}", f".{self.fmt}"
        name = root + ext
        n = 1
        while os.path.lexists(name):
            name = f"{root}-{n}{ext}"
            n += 1
        return name

    def build_report(self) -> Optional[str]:
        """Write the triage report: history, conclusion and s2idle report"""
        session = self.session
        text = self.format_history(session) + "\n\n"
        try:
            sleep_report = SleepReport(
                since=datetime.strptime(str(session["started"]), "%Y%m%d%H%M%S"),
                until=datetime.now() + timedelta(seconds=1),
                fname="",
                fmt=self.fmt,
                tool_debug=self.debug,
                report_debug=True,
            ).build_template(True)
        except Exception as e:  # pylint: disable=broad-except
            sleep_report = f"Unable to build the s2idle report: {e}"
        if self.fmt == "md":
            text = "# amd-s2idle triage report\n\n```\n" + text + "```\n\n"
        else:
            text = "amd-s2idle triage report\n\n" + text
        text += sleep_report

        fname = self.pick_filename()
        try:
            fd = os.open(
                fname,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                mode=stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH,
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
                if "SUDO_UID" in os.environ and "SUDO_GID" in os.environ:
                    try:
                        os.fchown(
                            f.fileno(),
                            int(os.environ["SUDO_UID"]),
                            int(os.environ["SUDO_GID"]),
                        )
                    except OSError:
                        pass  # root owned is fine, the report is readable
        except OSError as e:
            self.say(f"Failed to write the triage report: {e}", "❌")
            print(text)
            return None
        print(self.format_history(session))
        self.say(f"Triage report written to {fname}", "✅")
        return fname

    # -- main ------------------------------------------------------------

    def run(self) -> bool:
        """Run (or continue) the triage"""
        app = Installer(tool_debug=self.debug)
        app.set_requirements("iasl", "ethtool", "edid-decode")
        if not app.install_dependencies():
            self.say("Failed to install dependencies", "❌")
            return False

        try:
            session = self.db.triage_get()
            if session is None:
                if not self.start():
                    return False
            elif not self.resume(session):
                return True

            if self.session["status"] == Status.CHANGE_PENDING:
                if not self.guide_change():
                    return True

            if not self.run_prereqs():
                return False
            return self.run_test()
        except KeyboardInterrupt:
            sys.exit("\nTriage interrupted, run `amd-s2idle triage` to continue")

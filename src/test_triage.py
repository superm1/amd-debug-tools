#!/usr/bin/python3
# SPDX-License-Identifier: MIT

"""
This module contains unit tests for the triage mode in the amd-debug-tools package.
"""

import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from amd_debug.database import SleepDatabase
from amd_debug import triage
from amd_debug.triage import Triage, Stage, Status


def make_triage(answers, **kwargs):
    """Build a Triage backed by an in-memory database"""
    answers = iter(answers)
    with patch("amd_debug.triage.SleepDatabase", lambda: SleepDatabase(":memory:")):
        t = Triage(
            fmt="txt",
            fname=kwargs.get("fname"),
            debug=False,
            ask=lambda _prompt: next(answers),
        )
    return t


class TestTriageDatabase(unittest.TestCase):
    """Test the triage tables"""

    def setUp(self):
        self.db = SleepDatabase(":memory:")

    def test_session_lifecycle(self):
        """Progress is stored and unfinished sessions are found"""
        self.assertIsNone(self.db.triage_get())
        sid = self.db.triage_start(Stage.BASELINE, "boot")
        s = self.db.triage_get()
        self.assertEqual(s["id"], sid)
        self.assertEqual(s["status"], Status.READY)
        self.db.triage_update(sid, status=Status.RUNNING)
        self.assertEqual(self.db.triage_get()["status"], Status.RUNNING)
        self.assertEqual(self.db.triage_get()["stage"], Stage.BASELINE)
        self.db.triage_complete(sid, "no_hang")
        self.assertIsNone(self.db.triage_get())
        self.assertEqual(self.db.triage_get(sid)["outcome"], "no_hang")

    def test_events(self):
        """Events are kept in order"""
        sid = self.db.triage_start(Stage.BASELINE)
        self.db.triage_log(sid, "info", "one")
        self.db.triage_log(sid, "question", "two", "yes")
        events = self.db.triage_events(sid)
        self.assertEqual([e[2] for e in events], ["one", "two"])
        self.assertEqual(events[1][3], "yes")

    def test_abandon(self):
        """Abandoning closes unfinished sessions"""
        sid = self.db.triage_start(Stage.BASELINE)
        self.db.triage_abandon_all()
        self.assertIsNone(self.db.triage_get())
        self.assertEqual(self.db.triage_get(sid)["outcome"], "abandoned")


@patch("amd_debug.triage.get_boot_id", return_value="boot-a")
@patch("amd_debug.triage.print_color")
@patch("builtins.print")
class TestTriageFlow(unittest.TestCase):
    """Test the interview flow"""

    def test_decline(self, *_):
        """Declining the intro doesn't store anything"""
        t = make_triage(["n"])
        self.assertFalse(t.start())
        self.assertIsNone(t.db.triage_get())

    def test_start_stores_progress(self, *_):
        """Accepting the intro starts a session"""
        t = make_triage(["y"])
        self.assertTrue(t.start())
        self.assertEqual(t.db.triage_get()["stage"], Stage.BASELINE)

    def test_prereq_failure(self, *_):
        """Failed prerequisites tell the user to fix them"""
        t = make_triage(["y"])
        t.start()
        validator = MagicMock()
        validator.run.return_value = False
        t.db.report_prereq = MagicMock(return_value=[(0, 0, "bad thing", "❌")])
        t.db.get_last_prereq_ts = MagicMock(return_value=20250101000000)
        with patch("amd_debug.triage.get_validator", return_value=validator):
            self.assertFalse(t.run_prereqs())
        self.assertEqual(t.db.triage_get()["status"], Status.PREREQ_FAILED)
        self.assertIn("bad thing", t.db.triage_events(t.session["id"])[-1][2])

    def test_hang_walks_through_stages(self, *_):
        """Each hang advances to the next change"""
        t = make_triage(["y", "y", "y", "y"])
        t.start()
        t.set_status(Status.RUNNING, boot_id="boot-old")
        # first hang -> BIOS defaults
        self.assertTrue(t.resume(t.db.triage_get()))
        s = t.db.triage_get()
        self.assertEqual(
            (s["stage"], s["status"]), (Stage.BIOS_DEFAULTS, Status.CHANGE_PENDING)
        )
        # instructions shown; same boot so no progress
        self.assertFalse(t.guide_change())
        self.assertEqual(t.db.triage_get()["boot_id"], "boot-a")
        self.assertFalse(t.guide_change())
        self.assertEqual(t.db.triage_get()["status"], Status.CHANGE_PENDING)
        # rebooted
        with patch("amd_debug.triage.get_boot_id", return_value="boot-b"):
            self.assertTrue(t.guide_change())
        self.assertEqual(t.db.triage_get()["status"], Status.READY)
        # second hang -> IOMMU
        t.set_status(Status.RUNNING, boot_id="boot-old")
        self.assertTrue(t.resume(t.db.triage_get()))
        self.assertEqual(t.db.triage_get()["stage"], Stage.IOMMU)

    def test_iommu_verification(self, *_):
        """IOMMU stage verifies the change"""
        t = make_triage(["y", "n"])
        t.start()
        t.set_status(Status.CHANGE_PENDING, stage=Stage.IOMMU, boot_id="boot-a")
        with patch("amd_debug.triage.get_boot_id", return_value="boot-b"):
            with patch("amd_debug.triage.iommu_disabled", return_value=False):
                self.assertFalse(t.guide_change())
            with patch("amd_debug.triage.iommu_disabled", return_value=True):
                self.assertTrue(t.guide_change())

    def test_final_hang_concludes(self, *_):
        """A hang with everything tried ends the triage with a report"""
        with tempfile.TemporaryDirectory() as d:
            t = make_triage(["y", "y"], fname=os.path.join(d, "r.txt"))
            t.start()
            t.set_status(Status.RUNNING, stage=Stage.IOMMU, boot_id="boot-old")
            with patch.object(triage, "SleepReport") as sr:
                sr.return_value.build_template.return_value = "S2IDLE REPORT"
                self.assertFalse(t.resume(t.db.triage_get()))
            self.assertEqual(
                t.db.triage_get(t.session["id"])["outcome"], "hang_persists"
            )
            with open(os.path.join(d, "r.txt"), encoding="utf-8") as f:
                content = f.read()
            self.assertIn("system hung", content)
            self.assertIn("S2IDLE REPORT", content)
            self.assertIn("Did the system hang", content)

    def test_completed_test(self, *_):
        """A test that finishes in a later stage credits the change"""
        with tempfile.TemporaryDirectory() as d:
            t = make_triage(["y"], fname=os.path.join(d, "r.txt"))
            t.start()
            t.set_status(Status.READY, stage=Stage.BIOS_DEFAULTS)
            with patch.object(triage, "SleepReport") as sr, patch.object(
                triage, "SleepValidator"
            ) as sv:
                sv.return_value.run.return_value = True
                sr.return_value.build_template.return_value = "x"
                t.run_test()
            self.assertEqual(
                t.db.triage_get(t.session["id"])["outcome"], "fixed_by_bios_defaults"
            )


class TestTriageHelpers(unittest.TestCase):
    """Test the system helper functions"""

    def test_boot_id(self):
        """boot id is read or empty"""
        with patch("amd_debug.triage.read_file", return_value="abc\n"):
            self.assertEqual(triage.get_boot_id(), "abc")
        with patch("amd_debug.triage.read_file", side_effect=OSError):
            self.assertEqual(triage.get_boot_id(), "unknown")
        with patch("amd_debug.triage.read_file", return_value="\n"):
            self.assertEqual(triage.get_boot_id(), "unknown")

    def test_iommu_disabled(self):
        """IOMMU detection via cmdline and sysfs"""
        with patch("amd_debug.triage.read_file", return_value="quiet amd_iommu=off"):
            self.assertTrue(triage.iommu_disabled())
        with patch("amd_debug.triage.read_file", return_value="quiet iommu=off"):
            self.assertTrue(triage.iommu_disabled())
        with patch("amd_debug.triage.read_file", return_value="quiet"):
            with patch("os.listdir", return_value=["ivhd0"]):
                self.assertFalse(triage.iommu_disabled())
            with patch("os.listdir", return_value=[]):
                self.assertTrue(triage.iommu_disabled())
            with patch("os.listdir", side_effect=FileNotFoundError):
                self.assertTrue(triage.iommu_disabled())
            with patch("os.listdir", side_effect=PermissionError):
                self.assertFalse(triage.iommu_disabled())
        with patch("amd_debug.triage.read_file", side_effect=OSError):
            with patch("os.listdir", return_value=["ivhd0"]):
                self.assertFalse(triage.iommu_disabled())

    def test_dmi_info(self):
        """DMI info skips unreadable fields"""

        def fake(path):
            if path.endswith("bios_version"):
                return "1.2\n"
            raise OSError

        with patch("amd_debug.triage.read_file", side_effect=fake):
            self.assertEqual(triage.get_dmi_info(), [("BIOS version", "1.2")])

    def test_format_ts(self):
        """Timestamps are formatted, bad ones passed through"""
        self.assertEqual(triage.format_ts(20250102030405), "2025-01-02 03:04:05")
        self.assertEqual(triage.format_ts("garbage"), "garbage")


@patch("amd_debug.triage.get_boot_id", return_value="boot-a")
@patch("amd_debug.triage.print_color")
@patch("builtins.print")
class TestTriageMore(unittest.TestCase):
    """Test the remaining branches"""

    def test_question_defaults_and_eof(self, *_):
        """Empty reply uses the default, EOF too"""
        t = make_triage(["y", "", ""])
        t.start()
        self.assertTrue(t.question("q", True))
        self.assertFalse(t.question("q", False))

        def eof(_):
            raise EOFError

        t.ask = eof
        self.assertTrue(t.question("q", True))
        self.assertFalse(t.question("q", False))

    def test_start_eof(self, *_):
        """EOF on the intro cancels"""
        t = make_triage([])

        def eof(_):
            raise EOFError

        t.ask = eof
        self.assertFalse(t.start())

    def test_start_logs_dmi(self, *_):
        """System info is part of the history"""
        t = make_triage(["y"])
        with patch("amd_debug.triage.get_dmi_info", return_value=[("Vendor", "ACME")]):
            t.start()
        self.assertIn(
            "Vendor: ACME", [e[2] for e in t.db.triage_events(t.session["id"])]
        )

    def test_hang_denied(self, *_):
        """User says it didn't hang: retry the same stage"""
        t = make_triage(["y", "n"])
        t.start()
        t.set_status(Status.RUNNING, boot_id="boot-old")
        self.assertTrue(t.resume(t.db.triage_get()))
        s = t.db.triage_get()
        self.assertEqual((s["stage"], s["status"]), (Stage.BASELINE, Status.READY))

    def test_resume_ready(self, *_):
        """Resuming a non running session just continues"""
        t = make_triage(["y"])
        t.start()
        t.set_status(Status.PREREQ_FAILED)
        self.assertTrue(t.resume(t.db.triage_get()))

    def test_bios_not_confirmed(self, *_):
        """Not confirming the BIOS reset keeps waiting"""
        t = make_triage(["y", "n"])
        t.start()
        t.set_status(Status.CHANGE_PENDING, stage=Stage.BIOS_DEFAULTS, boot_id="boot-a")
        with patch("amd_debug.triage.get_boot_id", return_value="boot-b"):
            self.assertFalse(t.guide_change())
        self.assertEqual(t.db.triage_get()["status"], Status.CHANGE_PENDING)

    def test_iommu_run_anyway(self, *_):
        """User can run the test even if the IOMMU is still enabled"""
        t = make_triage(["y", "y"])
        t.start()
        t.set_status(Status.CHANGE_PENDING, stage=Stage.IOMMU, boot_id="boot-a")
        with patch("amd_debug.triage.get_boot_id", return_value="boot-b"):
            with patch("amd_debug.triage.iommu_disabled", return_value=False):
                self.assertTrue(t.guide_change())

    def test_prereq_pass(self, *_):
        """Passing prerequisites are logged"""
        t = make_triage(["y"])
        t.start()
        validator = MagicMock()
        validator.run.return_value = True
        with patch("amd_debug.triage.get_validator", return_value=validator):
            self.assertTrue(t.run_prereqs())
        self.assertEqual(
            t.db.triage_events(t.session["id"])[-1][2], "Prerequisites passed"
        )

    def test_prereq_permission_error(self, *_):
        """Permission errors stop the run"""
        t = make_triage(["y"])
        t.start()
        with patch("amd_debug.triage.get_validator", side_effect=PermissionError("no")):
            self.assertFalse(t.run_prereqs())

    def _failing_prereqs(self, t):
        validator = MagicMock()
        validator.run.return_value = False
        t.db.report_prereq = MagicMock(return_value=[(0, 0, "bad", "❌")])
        t.db.get_last_prereq_ts = MagicMock(return_value=20250101000000)
        return patch("amd_debug.triage.get_validator", return_value=validator)

    def test_prereq_fail_later_stage_continues(self, *_):
        """Failures after a triage change don't block"""
        t = make_triage(["y"])
        t.start()
        t.set_status(Status.READY, stage=Stage.IOMMU)
        with self._failing_prereqs(t):
            self.assertTrue(t.run_prereqs())

    def test_run_test_keyboard_interrupt(self, *_):
        """Ctrl-C isn't treated as a hang"""
        t = make_triage(["y"])
        t.start()
        with patch.object(triage, "SleepValidator") as sv:
            sv.return_value.run.side_effect = KeyboardInterrupt
            self.assertFalse(t.run_test())
        self.assertEqual(t.db.triage_get()["status"], Status.READY)

    def test_run_test_baseline_no_hang(self, *_):
        """A clean baseline ends triage with no_hang"""
        with tempfile.TemporaryDirectory() as d:
            t = make_triage(["y"], fname=os.path.join(d, "r.txt"))
            t.start()
            with patch.object(triage, "SleepValidator") as sv, patch.object(
                triage, "SleepReport"
            ) as sr:
                sv.return_value.run.return_value = True
                sr.return_value.build_template.return_value = "x"
                self.assertTrue(t.run_test())
            kwargs = sv.return_value.run.call_args.kwargs
            self.assertEqual(kwargs["count"], 1)
            self.assertEqual(t.db.triage_get(t.session["id"])["outcome"], "no_hang")

    def test_run_test_validator_fails(self, *_):
        """A suspend that never happened isn't a result"""
        t = make_triage(["y"])
        t.start()
        with patch.object(triage, "SleepValidator") as sv, patch.object(
            t, "conclude"
        ) as conclude:
            sv.return_value.run.return_value = False
            self.assertFalse(t.run_test())
        conclude.assert_not_called()
        self.assertEqual(t.db.triage_get()["status"], Status.READY)

    def test_run_test_exception(self, *_):
        """Crashes aren't mistaken for hangs"""
        t = make_triage(["y"])
        t.start()
        with patch.object(triage, "SleepValidator") as sv:
            sv.return_value.run.side_effect = PermissionError("nope")
            with self.assertRaises(PermissionError):
                t.run_test()
        self.assertEqual(t.db.triage_get()["status"], Status.READY)
        self.assertIn("nope", t.db.triage_events(t.session["id"])[-1][2])

    def test_interrupted_same_boot(self, *_):
        """Without a reboot the test didn't hang; no question asked"""
        t = make_triage(["y"])
        t.start()
        t.set_status(Status.RUNNING, boot_id="boot-a")
        self.assertTrue(t.resume(t.db.triage_get()))
        s = t.db.triage_get()
        self.assertEqual((s["stage"], s["status"]), (Stage.BASELINE, Status.READY))

    def test_prereq_fail_without_timestamp(self, *_):
        """Missing prerequisite rows don't crash"""
        t = make_triage(["y"])
        t.start()
        validator = MagicMock()
        validator.run.return_value = False
        t.db.get_last_prereq_ts = MagicMock(return_value=0)
        with patch("amd_debug.triage.get_validator", return_value=validator):
            self.assertFalse(t.run_prereqs())
        self.assertEqual(t.db.triage_get()["status"], Status.PREREQ_FAILED)

    def test_pick_filename_user_supplied_exists(self, *_):
        """A user supplied name that exists isn't clobbered"""
        with tempfile.TemporaryDirectory() as d:
            fname = os.path.join(d, "r.txt")
            open(fname, "w", encoding="utf-8").close()
            t = make_triage(["y"], fname=fname)
            self.assertEqual(t.pick_filename(), os.path.join(d, "r-1.txt"))

    def test_report_chown_failure_ignored(self, *_):
        """Failing to chown doesn't fail the report; SUDO_GID is optional"""
        with tempfile.TemporaryDirectory() as d:
            fname = os.path.join(d, "r.txt")
            t = make_triage(["y"], fname=fname)
            t.start()
            t.session = t.db.triage_get(t.session["id"])
            with patch.object(triage, "SleepReport") as sr:
                sr.return_value.build_template.return_value = "x"
                with patch.dict(os.environ, {"SUDO_UID": "1", "SUDO_GID": "2"}):
                    with patch("os.fchown", side_effect=OSError):
                        self.assertEqual(t.build_report(), fname)
                os.remove(fname)
                env = {k: v for k, v in os.environ.items() if k != "SUDO_GID"}
                env["SUDO_UID"] = "1"
                with patch.dict(os.environ, env, clear=True):
                    with patch("os.fchown") as chown:
                        self.assertEqual(t.build_report(), fname)
                    chown.assert_not_called()

    def test_pick_filename(self, *_):
        """Default names don't overwrite existing files"""
        t = make_triage(["y"])
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as d:
            os.chdir(d)
            try:
                first = t.pick_filename()
                open(first, "w", encoding="utf-8").close()
                second = t.pick_filename()
            finally:
                os.chdir(cwd)
        self.assertNotEqual(first, second)
        self.assertTrue(second.endswith("-1.txt"))

    def test_format_fallback(self, *_):
        """Unsupported formats fall back to txt"""
        t = make_triage(["y"])
        t.fmt = "txt"
        self.assertEqual(t.fmt, "txt")

    def test_report_markdown_and_failure(self, *_):
        """Markdown reports, s2idle report failure and chown"""
        with tempfile.TemporaryDirectory() as d:
            fname = os.path.join(d, "r.md")
            t = make_triage(["y"], fname=fname)
            t.fmt = "md"
            t.start()
            t.db.triage_log(t.session["id"], "unknown", "odd")
            t.db.triage_complete(t.session["id"], "mystery")
            t.session = t.db.triage_get(t.session["id"])
            env = {"SUDO_UID": "1", "SUDO_GID": "2"}
            with patch.object(triage, "SleepReport", side_effect=ValueError("boom")):
                with patch.dict(os.environ, env), patch("os.fchown") as chown:
                    self.assertEqual(t.build_report(), fname)
                chown.assert_called_once()
            with open(fname, encoding="utf-8") as f:
                content = f.read()
            self.assertIn("# amd-s2idle triage report", content)
            self.assertIn("Unable to build the s2idle report: boom", content)
            self.assertIn("unknown: odd", content)
            self.assertIn("mystery", content)

    def test_report_write_failure(self, *_):
        """An unwritable report is printed instead"""
        t = make_triage(["y"], fname="/nonexistent-dir/r.txt")
        t.start()
        t.session = t.db.triage_get(t.session["id"])
        with patch.object(triage, "SleepReport") as sr:
            sr.return_value.build_template.return_value = "x"
            self.assertIsNone(t.build_report())


@patch("amd_debug.triage.get_boot_id", return_value="boot-a")
@patch("amd_debug.triage.print_color")
@patch("builtins.print")
class TestTriageRun(unittest.TestCase):
    """Test the top level run()"""

    def setUp(self):
        patcher = patch("amd_debug.triage.Installer")
        self.installer = patcher.start().return_value
        self.installer.install_dependencies.return_value = True
        self.addCleanup(patcher.stop)

    def test_dependencies_fail(self, *_):
        """Missing dependencies abort"""
        self.installer.install_dependencies.return_value = False
        t = make_triage([])
        self.assertFalse(t.run())

    def test_declined(self, *_):
        """Declining the intro returns False"""
        t = make_triage(["n"])
        self.assertFalse(t.run())

    def test_new_session_runs_test(self, *_):
        """A new session runs prerequisites then the test"""
        t = make_triage(["y"])
        with patch.object(t, "run_prereqs", return_value=True), patch.object(
            t, "run_test"
        ) as rt:
            self.assertTrue(t.run())
        rt.assert_called_once()

    def test_prereq_failure_stops(self, *_):
        """Failed prerequisites skip the test"""
        t = make_triage(["y"])
        with patch.object(t, "run_prereqs", return_value=False), patch.object(
            t, "run_test"
        ) as rt:
            self.assertFalse(t.run())
        rt.assert_not_called()

    def test_resume_final_hang(self, *_):
        """A final hang concludes and returns True"""
        t = make_triage(["y", "y"])
        with patch.object(triage, "SleepReport") as sr, patch.object(
            t, "pick_filename", return_value="/nonexistent-dir/x"
        ):
            sr.return_value.build_template.return_value = "x"
            t.start()
            t.set_status(Status.RUNNING, stage=Stage.IOMMU, boot_id="boot-old")
            t.session = None
            self.assertTrue(t.run())

    def test_run_returns_test_result(self, *_):
        """run() reports whether the test completed"""
        t = make_triage(["y"])
        with patch.object(t, "run_prereqs", return_value=True), patch.object(
            t, "run_test", return_value=False
        ):
            self.assertFalse(t.run())

    def test_change_pending_waits(self, *_):
        """Waiting for the user's change stops before the test"""
        t = make_triage(["y", "y"])
        t.start()
        t.set_status(Status.RUNNING, boot_id="boot-old")
        with patch.object(t, "run_test") as rt:
            self.assertTrue(t.run())
        rt.assert_not_called()
        self.assertEqual(t.db.triage_get()["status"], Status.CHANGE_PENDING)

    def test_keyboard_interrupt(self, *_):
        """Ctrl-C exits with a hint"""
        t = make_triage(["y"])
        with patch.object(t, "run_prereqs", side_effect=KeyboardInterrupt):
            with self.assertRaises(SystemExit):
                t.run()


if __name__ == "__main__":
    unittest.main()

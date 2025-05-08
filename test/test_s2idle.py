#!/usr/bin/python3
# SPDX-License-Identifier: MIT

"""
This module contains unit tests for the s2idle tool in the amd-debug-tools package.
"""
import argparse
import os
import sys
import unittest
import logging
import sqlite3
from datetime import datetime
from unittest.mock import patch

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from amd_debug.s2idle import (
    parse_args,
    main,
    install,
    uninstall,
    test,
    display_report_file,
    report,
    prompt_report_arguments,
    Defaults,
)


class TestParseArgs(unittest.TestCase):
    """Test parse_args function"""

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(filename="/dev/null", level=logging.DEBUG)

    def setUp(self):
        self.default_sys_argv = sys.argv

    def tearDown(self):
        sys.argv = self.default_sys_argv

    @patch("sys.stderr")
    def test_no_arguments(self, _mock_print):
        """Test parse_args with no arguments"""
        sys.argv = ["s2idle.py"]
        with self.assertRaises(SystemExit):
            parse_args()

    def test_test_command_with_arguments(self):
        """Test parse_args with test command and arguments"""
        sys.argv = [
            "s2idle.py",
            "test",
            "--count",
            "5",
            "--duration",
            "10",
            "--wait",
            "3",
            "--format",
            "txt",
            "--tool-debug",
        ]
        args = parse_args()
        self.assertEqual(args.action, "test")
        self.assertEqual(args.count, "5")
        self.assertEqual(args.duration, "10")
        self.assertEqual(args.wait, "3")
        self.assertEqual(args.format, "txt")
        self.assertTrue(args.tool_debug)

    def test_report_command_with_arguments(self):
        """Test parse_args with report command and arguments"""
        sys.argv = [
            "s2idle.py",
            "report",
            "--since",
            "2023-01-01",
            "--until",
            "2023-02-01",
            "--format",
            "html",
            "--report-debug",
        ]
        args = parse_args()
        self.assertEqual(args.action, "report")
        self.assertEqual(args.since, "2023-01-01")
        self.assertEqual(args.until, "2023-02-01")
        self.assertEqual(args.format, "html")
        self.assertTrue(args.report_debug)

    @patch("sys.prefix", "amd_debug.s2idle")
    @patch("sys.base_prefix", "foo")
    def test_install_command(self):
        """Test parse_args with install command"""
        sys.argv = ["s2idle.py", "install", "--tool-debug"]
        args = parse_args()
        self.assertEqual(args.action, "install")
        self.assertTrue(args.tool_debug)

    @patch("sys.prefix", "amd_debug.s2idle")
    @patch("sys.base_prefix", "foo")
    def test_uninstall_command(self):
        """Test parse_args with uninstall command"""
        sys.argv = ["s2idle.py", "uninstall", "--tool-debug"]
        args = parse_args()
        self.assertEqual(args.action, "uninstall")
        self.assertTrue(args.tool_debug)

    @patch("sys.prefix", "amd_debug.s2idle")
    @patch("sys.base_prefix", "amd_debug.s2idle")
    @patch("sys.stderr")
    def test_hidden_install_command(self, _mock_print):
        """Test parse_args with install command"""
        sys.argv = ["s2idle.py", "install", "--tool-debug"]
        with self.assertRaises(SystemExit):
            parse_args()

    def test_version_command(self):
        """Test parse_args with version command"""
        sys.argv = ["s2idle.py", "version"]
        args = parse_args()
        self.assertEqual(args.action, "version")


class TestMainFunction(unittest.TestCase):
    """Test main function"""

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(filename="/dev/null", level=logging.DEBUG)

    def setUp(self):
        self.default_sys_argv = sys.argv

    def tearDown(self):
        sys.argv = self.default_sys_argv

    @patch("amd_debug.s2idle.relaunch_sudo")
    @patch("amd_debug.s2idle.install")
    def test_main_install(self, mock_install, mock_relaunch_sudo):
        """Test main function with install action"""
        sys.argv = ["s2idle.py", "install", "--tool-debug"]
        with patch("amd_debug.s2idle.parse_args") as mock_parse_args:
            mock_parse_args.return_value = argparse.Namespace(
                action="install", tool_debug=True
            )
            main()
            mock_relaunch_sudo.assert_called_once()
            mock_install.assert_called_once_with(True)

    @patch("amd_debug.s2idle.relaunch_sudo")
    @patch("amd_debug.s2idle.uninstall")
    def test_main_uninstall(self, mock_uninstall, mock_relaunch_sudo):
        """Test main function with uninstall action"""
        sys.argv = ["s2idle.py", "uninstall", "--tool-debug"]
        with patch("amd_debug.s2idle.parse_args") as mock_parse_args:
            mock_parse_args.return_value = argparse.Namespace(
                action="uninstall", tool_debug=True
            )
            main()
            mock_relaunch_sudo.assert_called_once()
            mock_uninstall.assert_called_once_with(True)

    @patch("amd_debug.s2idle.report")
    def test_main_report(self, mock_report):
        """Test main function with report action"""
        sys.argv = ["s2idle.py", "report", "--since", "2023-01-01"]
        with patch("amd_debug.s2idle.parse_args") as mock_parse_args:
            mock_parse_args.return_value = argparse.Namespace(
                action="report",
                since="2023-01-01",
                until="2023-02-01",
                report_file=None,
                format="html",
                tool_debug=False,
                report_debug=False,
            )
            mock_report.return_value = True
            result = main()
            mock_report.assert_called_once_with(
                "2023-01-01", "2023-02-01", None, "html", False, False
            )
            self.assertTrue(result)

    @patch("amd_debug.s2idle.relaunch_sudo")
    @patch("amd_debug.s2idle.test")
    def test_main_test(self, mock_test, mock_relaunch_sudo):
        """Test main function with test action"""
        sys.argv = ["s2idle.py", "test", "--count", "5"]
        with patch("amd_debug.s2idle.parse_args") as mock_parse_args:
            mock_parse_args.return_value = argparse.Namespace(
                action="test",
                duration=None,
                wait=None,
                count="5",
                format="txt",
                report_file=None,
                force=False,
                tool_debug=False,
                random=False,
                logind=False,
                bios_debug=False,
            )
            mock_test.return_value = True
            result = main()
            mock_relaunch_sudo.assert_called_once()
            mock_test.assert_called_once_with(
                None, None, "5", "txt", None, False, False, False, False, False
            )
            self.assertTrue(result)

    @patch("amd_debug.s2idle.version")
    def test_main_version(self, mock_version):
        """Test main function with version action"""
        sys.argv = ["s2idle.py", "version"]
        with patch("amd_debug.s2idle.parse_args") as mock_parse_args:
            mock_parse_args.return_value = argparse.Namespace(action="version")
            mock_version.return_value = "1.0.0"
            with patch("builtins.print") as mock_print:
                result = main()
                mock_version.assert_called_once()
                mock_print.assert_called_once_with("1.0.0")
                self.assertTrue(result)

    def test_main_no_action(self):
        """Test main function with no action specified"""
        sys.argv = ["s2idle.py"]
        with patch("amd_debug.s2idle.parse_args") as mock_parse_args:
            mock_parse_args.return_value = argparse.Namespace(action=None)
            with self.assertRaises(SystemExit) as cm:
                main()
            self.assertEqual(cm.exception.code, "no action specified")

            @patch("amd_debug.s2idle.Installer")
            def test_uninstall_success(self, mock_installer):
                """Test uninstall function when removal is successful"""
                mock_app = mock_installer.return_value
                mock_app.remove.return_value = True

                uninstall(debug=True)
                mock_installer.assert_called_once_with(tool_debug=True)
                mock_app.remove.assert_called_once()


class TestInstallFunction(unittest.TestCase):
    """Test main function"""

    @patch("amd_debug.s2idle.Installer")
    @patch("sys.exit")
    def test_uninstall_failure(self, mock_sys_exit, mock_installer):
        """Test uninstall function when removal fails"""
        mock_app = mock_installer.return_value
        mock_app.remove.return_value = False

        uninstall(debug=True)
        mock_installer.assert_called_once_with(tool_debug=True)
        mock_app.remove.assert_called_once()
        mock_sys_exit.assert_called_once_with("Failed to remove")

    @patch("amd_debug.s2idle.Installer")
    @patch("amd_debug.s2idle.PrerequisiteValidator")
    @patch("sys.exit")
    def test_install_success(
        self, mock_sys_exit, mock_prerequisite_validator, mock_installer
    ):
        """Test install function when installation is successful"""
        mock_installer_instance = mock_installer.return_value
        mock_installer_instance.install_dependencies.return_value = True
        mock_installer_instance.install.return_value = True

        mock_prerequisite_instance = mock_prerequisite_validator.return_value
        mock_prerequisite_instance.run.return_value = True

        install(debug=True)

        mock_installer.assert_called_once_with(tool_debug=True)
        mock_installer_instance.set_requirements.assert_called_once_with(
            "iasl", "ethtool"
        )
        mock_installer_instance.install_dependencies.assert_called_once()
        mock_prerequisite_validator.assert_called_once_with(True)
        mock_prerequisite_instance.run.assert_called_once()
        mock_installer_instance.install.assert_called_once()
        mock_sys_exit.assert_not_called()

    @patch("amd_debug.s2idle.Installer")
    def test_install_dependencies_failure(self, mock_installer):
        """Test install function when dependency installation fails"""
        mock_installer_instance = mock_installer.return_value
        mock_installer_instance.install_dependencies.return_value = False

        with self.assertRaises(SystemExit):
            install(debug=True)

    @patch("amd_debug.s2idle.Installer")
    @patch("amd_debug.s2idle.PrerequisiteValidator")
    @patch("sys.exit")
    def test_prerequisite_check_failure(
        self, mock_sys_exit, mock_prerequisite_validator, mock_installer
    ):
        """Test install function when prerequisite check fails"""
        mock_installer_instance = mock_installer.return_value
        mock_installer_instance.install_dependencies.return_value = True

        mock_prerequisite_instance = mock_prerequisite_validator.return_value
        mock_prerequisite_instance.run.return_value = False

        install(debug=True)

        mock_installer.assert_called_once_with(tool_debug=True)
        mock_installer_instance.set_requirements.assert_called_once_with(
            "iasl", "ethtool"
        )
        mock_installer_instance.install_dependencies.assert_called_once()
        mock_prerequisite_validator.assert_called_once_with(True)
        mock_prerequisite_instance.run.assert_called_once()
        mock_prerequisite_instance.report.assert_called_once()
        mock_sys_exit.assert_called_once_with("Failed to meet prerequisites")

    @patch("amd_debug.s2idle.Installer")
    @patch("amd_debug.s2idle.PrerequisiteValidator")
    @patch("sys.exit")
    def test_install_failure(
        self, mock_sys_exit, mock_prerequisite_validator, mock_installer
    ):
        """Test install function when installation fails"""
        mock_installer_instance = mock_installer.return_value
        mock_installer_instance.install_dependencies.return_value = True
        mock_installer_instance.install.return_value = False

        mock_prerequisite_instance = mock_prerequisite_validator.return_value
        mock_prerequisite_instance.run.return_value = True

        install(debug=True)

        mock_installer.assert_called_once_with(tool_debug=True)
        mock_installer_instance.set_requirements.assert_called_once_with(
            "iasl", "ethtool"
        )
        mock_installer_instance.install_dependencies.assert_called_once()
        mock_prerequisite_validator.assert_called_once_with(True)
        mock_prerequisite_instance.run.assert_called_once()
        mock_installer_instance.install.assert_called_once()
        mock_sys_exit.assert_called_once_with("Failed to install")


class TestTestFunction(unittest.TestCase):
    """Test the test function"""

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(filename="/dev/null", level=logging.DEBUG)

    @patch("amd_debug.s2idle.Installer")
    @patch("amd_debug.s2idle.PrerequisiteValidator")
    @patch("amd_debug.s2idle.SleepValidator")
    @patch("amd_debug.s2idle.SleepReport")
    @patch("amd_debug.s2idle.prompt_test_arguments")
    @patch("amd_debug.s2idle.prompt_report_arguments")
    @patch("amd_debug.s2idle.display_report_file")
    def test_test_success(
        self,
        mock_display_report_file,
        mock_prompt_report_arguments,
        mock_prompt_test_arguments,
        mock_sleep_report,
        mock_sleep_validator,
        mock_prerequisite_validator,
        mock_installer,
    ):
        """Test the test function when everything succeeds"""
        mock_installer_instance = mock_installer.return_value
        mock_installer_instance.install_dependencies.return_value = True

        mock_prerequisite_instance = mock_prerequisite_validator.return_value
        mock_prerequisite_instance.run.return_value = True

        mock_prompt_test_arguments.return_value = (10, 5, 3)
        mock_prompt_report_arguments.return_value = (
            "2023-01-01",
            "2023-02-01",
            "report.html",
            "html",
        )

        mock_sleep_validator_instance = mock_sleep_validator.return_value
        mock_sleep_report_instance = mock_sleep_report.return_value

        result = test(
            duration=None,
            wait=None,
            count=None,
            fmt=None,
            fname=None,
            force=False,
            debug=True,
            rand=False,
            logind=False,
            bios_debug=False,
        )

        mock_installer.assert_called_once_with(tool_debug=True)
        mock_installer_instance.set_requirements.assert_called_once_with(
            "iasl", "ethtool"
        )
        mock_installer_instance.install_dependencies.assert_called_once()
        mock_prerequisite_validator.assert_called_once_with(True)
        mock_prerequisite_instance.run.assert_called_once()
        mock_prerequisite_instance.report.assert_called_once()
        mock_prompt_test_arguments.assert_called_once_with(None, None, None, False)
        mock_prompt_report_arguments.assert_called_once()
        mock_sleep_validator.assert_called_once_with(tool_debug=True, bios_debug=False)
        mock_sleep_validator_instance.run.assert_called_once_with(
            duration=10, wait=5, count=3, rand=False, logind=False
        )
        mock_sleep_report.assert_called_once_with(
            since="2023-01-01",
            until="2023-02-01",
            fname="report.html",
            fmt="html",
            tool_debug=True,
            report_debug=True,
        )
        mock_sleep_report_instance.run.assert_called_once()
        mock_display_report_file.assert_called_once_with("report.html", "html")
        self.assertTrue(result)

    @patch("amd_debug.s2idle.Installer")
    @patch("builtins.print")
    def test_test_install_dependencies_failure(self, _mock_print, mock_installer):
        """Test the test function when dependency installation fails"""
        mock_installer_instance = mock_installer.return_value
        mock_installer_instance.install_dependencies.return_value = False

        result = test(
            duration=None,
            wait=None,
            count=None,
            fmt=None,
            fname=None,
            force=False,
            debug=True,
            rand=False,
            logind=False,
            bios_debug=False,
        )

        mock_installer.assert_called_once_with(tool_debug=True)
        mock_installer_instance.set_requirements.assert_called_once_with(
            "iasl", "ethtool"
        )
        mock_installer_instance.install_dependencies.assert_called_once()
        self.assertFalse(result)

    @patch("amd_debug.s2idle.Installer")
    @patch("amd_debug.s2idle.PrerequisiteValidator")
    @patch("amd_debug.prerequisites.SleepDatabase")
    @patch("amd_debug.validator.SleepDatabase")
    def test_test_prerequisite_failure(
        self,
        _mock_sleep_db,
        _mock_sleep_db_prerequisite,
        mock_prerequisite_validator,
        mock_installer,
    ):
        """Test the test function when prerequisite check fails"""
        mock_installer_instance = mock_installer.return_value
        mock_installer_instance.install_dependencies.return_value = True

        mock_prerequisite_instance = mock_prerequisite_validator.return_value
        mock_prerequisite_instance.run.return_value = False

        result = test(
            duration=None,
            wait=None,
            count=None,
            fmt=None,
            fname=None,
            force=False,
            debug=True,
            rand=False,
            logind=False,
            bios_debug=False,
        )

        mock_installer.assert_called_once_with(tool_debug=True)
        mock_installer_instance.set_requirements.assert_called_once_with(
            "iasl", "ethtool"
        )
        mock_installer_instance.install_dependencies.assert_called_once()
        mock_prerequisite_validator.assert_called_once_with(True)
        mock_prerequisite_instance.run.assert_called_once()
        mock_prerequisite_instance.report.assert_called_once()
        self.assertFalse(result)

    @patch("amd_debug.s2idle.Installer")
    @patch("amd_debug.s2idle.PrerequisiteValidator")
    @patch("amd_debug.s2idle.prompt_test_arguments", side_effect=KeyboardInterrupt)
    @patch("amd_debug.prerequisites.SleepDatabase")
    @patch("amd_debug.validator.SleepDatabase")
    def test_test_keyboard_interrupt(
        self,
        _mock_sleep_db_validator,
        _mock_sleep_db_prerequisite,
        mock_prompt_test_arguments,
        mock_prerequisite_validator,
        mock_installer,
    ):
        """Test the test function when interrupted by the user"""
        mock_installer_instance = mock_installer.return_value
        mock_installer_instance.install_dependencies.return_value = True

        mock_prerequisite_instance = mock_prerequisite_validator.return_value
        mock_prerequisite_instance.run.return_value = True

        with self.assertRaises(SystemExit):
            test(
                duration=None,
                wait=None,
                count=None,
                fmt=None,
                fname=None,
                force=False,
                debug=True,
                rand=False,
                logind=False,
                bios_debug=False,
            )

        mock_installer.assert_called_once_with(tool_debug=True)
        mock_installer_instance.set_requirements.assert_called_once_with(
            "iasl", "ethtool"
        )
        mock_installer_instance.install_dependencies.assert_called_once()
        mock_prerequisite_validator.assert_called_once_with(True)
        mock_prerequisite_instance.run.assert_called_once()
        mock_prerequisite_instance.report.assert_called_once()
        mock_prompt_test_arguments.assert_called_once_with(None, None, None, False)


class TestDisplayReportFile(unittest.TestCase):
    """Test display_report_file function"""

    @patch("amd_debug.s2idle.is_root", return_value=False)
    @patch("subprocess.call")
    def test_display_report_file_non_html(self, mock_subprocess_call, mock_is_root):
        """Test display_report_file when format is not html"""
        display_report_file("report.txt", "txt")
        mock_is_root.assert_not_called()
        mock_subprocess_call.assert_not_called()

    @patch("amd_debug.s2idle.is_root", return_value=False)
    @patch("subprocess.call")
    def test_display_report_file_html_non_root(
        self, mock_subprocess_call, mock_is_root
    ):
        """Test display_report_file when format is html and user is not root"""
        display_report_file("report.html", "html")
        mock_is_root.assert_called_once()
        mock_subprocess_call.assert_called_once_with(["xdg-open", "report.html"])

    @patch("amd_debug.s2idle.is_root", return_value=True)
    @patch(
        "os.environ.get",
        side_effect=lambda key: "testuser" if key == "SUDO_USER" else "foo",
    )
    @patch("subprocess.call")
    def test_display_report_file_html_root_with_user(
        self, mock_subprocess_call, mock_env_get, mock_is_root
    ):
        """Test display_report_file when format is html, user is root, and SUDO_USER is set"""
        display_report_file("report.html", "html")
        mock_is_root.assert_called_once()
        mock_env_get.assert_any_call("SUDO_USER")
        mock_env_get.assert_any_call("XDG_SESSION_TYPE")
        mock_subprocess_call.assert_called_once_with(
            ["sudo", "-E", "-u", "testuser", "xdg-open", "report.html"]
        )

    @patch("amd_debug.s2idle.is_root", return_value=True)
    @patch("os.environ.get", side_effect=lambda key: None)
    @patch("builtins.print")
    def test_display_report_file_html_root_without_user(
        self, mock_print, mock_env_get, mock_is_root
    ):
        """Test display_report_file when format is html, user is root, and SUDO_USER is not set"""
        display_report_file("report.html", "html")
        mock_is_root.assert_called_once()
        mock_env_get.assert_any_call("SUDO_USER")
        mock_print.assert_not_called()


class TestReportFunction(unittest.TestCase):
    """Test the report function"""

    @patch("amd_debug.s2idle.prompt_report_arguments")
    @patch("amd_debug.s2idle.SleepReport")
    @patch("amd_debug.s2idle.display_report_file")
    def test_report_success(
        self, mock_display_report_file, mock_sleep_report, mock_prompt_report_arguments
    ):
        """Test the report function when everything succeeds"""
        mock_prompt_report_arguments.return_value = (
            "2023-01-01",
            "2023-02-01",
            "report.html",
            "html",
        )
        mock_sleep_report_instance = mock_sleep_report.return_value

        result = report(
            since=None,
            until=None,
            fname=None,
            fmt=None,
            tool_debug=True,
            report_debug=True,
        )

        mock_prompt_report_arguments.assert_called_once_with(None, None, None, None)
        mock_sleep_report.assert_called_once_with(
            since="2023-01-01",
            until="2023-02-01",
            fname="report.html",
            fmt="html",
            tool_debug=True,
            report_debug=True,
        )
        mock_sleep_report_instance.run.assert_called_once()
        mock_display_report_file.assert_called_once_with("report.html", "html")
        self.assertTrue(result)

    @patch("amd_debug.s2idle.prompt_report_arguments", side_effect=KeyboardInterrupt)
    def test_report_keyboard_interrupt(self, mock_prompt_report_arguments):
        """Test the report function when interrupted by the user"""
        with self.assertRaises(SystemExit):
            report(
                since=None,
                until=None,
                fname=None,
                fmt=None,
                tool_debug=True,
                report_debug=True,
            )

        mock_prompt_report_arguments.assert_called_once_with(None, None, None, None)

    @patch("amd_debug.s2idle.prompt_report_arguments")
    @patch(
        "amd_debug.s2idle.SleepReport", side_effect=sqlite3.OperationalError("DB error")
    )
    @patch("builtins.print")
    def test_report_sqlite_error(
        self, _mock_print, mock_sleep_report, mock_prompt_report_arguments
    ):
        """Test the report function when a SQLite error occurs"""
        mock_prompt_report_arguments.return_value = (
            "2023-01-01",
            "2023-02-01",
            "report.html",
            "html",
        )

        result = report(
            since=None,
            until=None,
            fname=None,
            fmt=None,
            tool_debug=True,
            report_debug=True,
        )

        mock_prompt_report_arguments.assert_called_once_with(None, None, None, None)
        mock_sleep_report.assert_called_once_with(
            since="2023-01-01",
            until="2023-02-01",
            fname="report.html",
            fmt="html",
            tool_debug=True,
            report_debug=True,
        )
        self.assertFalse(result)

    @patch("amd_debug.s2idle.prompt_report_arguments")
    @patch(
        "amd_debug.s2idle.SleepReport", side_effect=PermissionError("Permission denied")
    )
    @patch("builtins.print")
    def test_report_permission_error(
        self, _mock_print, mock_sleep_report, mock_prompt_report_arguments
    ):
        """Test the report function when a PermissionError occurs"""
        mock_prompt_report_arguments.return_value = (
            "2023-01-01",
            "2023-02-01",
            "report.html",
            "html",
        )

        result = report(
            since=None,
            until=None,
            fname=None,
            fmt=None,
            tool_debug=True,
            report_debug=True,
        )

        mock_prompt_report_arguments.assert_called_once_with(None, None, None, None)
        mock_sleep_report.assert_called_once_with(
            since="2023-01-01",
            until="2023-02-01",
            fname="report.html",
            fmt="html",
            tool_debug=True,
            report_debug=True,
        )
        self.assertFalse(result)

    @patch("amd_debug.s2idle.prompt_report_arguments")
    @patch("amd_debug.s2idle.SleepReport")
    @patch("builtins.print")
    def test_report_run_error(
        self, _mock_print, mock_sleep_report, mock_prompt_report_arguments
    ):
        """Test the report function when an error occurs during app.run()"""
        mock_prompt_report_arguments.return_value = (
            "2023-01-01",
            "2023-02-01",
            "report.html",
            "html",
        )
        mock_sleep_report_instance = mock_sleep_report.return_value
        mock_sleep_report_instance.run.side_effect = ValueError("Invalid value")

        result = report(
            since=None,
            until=None,
            fname=None,
            fmt=None,
            tool_debug=True,
            report_debug=True,
        )

        mock_prompt_report_arguments.assert_called_once_with(None, None, None, None)
        mock_sleep_report.assert_called_once_with(
            since="2023-01-01",
            until="2023-02-01",
            fname="report.html",
            fmt="html",
            tool_debug=True,
            report_debug=True,
        )
        mock_sleep_report_instance.run.assert_called_once()
        self.assertFalse(result)


class TestPromptReportArguments(unittest.TestCase):
    """Test prompt_report_arguments function"""

    @patch("builtins.input", side_effect=["2023-01-01", "2023-02-01", "html"])
    @patch("amd_debug.s2idle.get_report_file", return_value="report.html")
    @patch("amd_debug.s2idle.get_report_format", return_value="html")
    def test_prompt_report_arguments_success(
        self, mock_get_report_format, mock_get_report_file, _mock_input
    ):
        """Test prompt_report_arguments with valid inputs"""
        result = prompt_report_arguments(None, None, None, None)
        self.assertEqual(result[0], datetime(2023, 1, 1))
        self.assertEqual(result[1], datetime(2023, 2, 1))
        self.assertEqual(result[2], "report.html")
        self.assertEqual(result[3], "html")
        mock_get_report_file.assert_called_once_with(None, "html")
        mock_get_report_format.assert_called_once()

    @patch(
        "builtins.input",
        side_effect=["invalid-date", "2023-01-01", "2023-02-01", "html"],
    )
    @patch("sys.exit")
    def test_prompt_report_arguments_invalid_since_date(self, mock_exit, mock_input):
        """Test prompt_report_arguments with invalid 'since' date"""
        mock_exit.side_effect = SystemExit
        with self.assertRaises(SystemExit):
            prompt_report_arguments(None, None, None, None)
        mock_exit.assert_called_once_with(
            "Invalid date, use YYYY-MM-DD: Invalid isoformat string: 'invalid-date'"
        )

    @patch(
        "builtins.input",
        side_effect=["2023-01-01", "invalid-date", "2023-02-01", "html"],
    )
    @patch("sys.exit")
    def test_prompt_report_arguments_invalid_until_date(self, mock_exit, mock_input):
        """Test prompt_report_arguments with invalid 'until' date"""
        mock_exit.side_effect = SystemExit
        with self.assertRaises(SystemExit):
            prompt_report_arguments(None, None, None, None)
        mock_exit.assert_called_once_with(
            "Invalid date, use YYYY-MM-DD: Invalid isoformat string: 'invalid-date'"
        )

    @patch("builtins.input", side_effect=["2023-01-01", "2023-02-01", "invalid-format"])
    @patch("amd_debug.s2idle.get_report_format", return_value="html")
    @patch("sys.exit")
    def test_prompt_report_arguments_invalid_format(
        self, mock_exit, mock_get_report_format, mock_input
    ):
        """Test prompt_report_arguments with invalid format"""
        mock_exit.side_effect = SystemExit
        with self.assertRaises(SystemExit):
            prompt_report_arguments(None, None, None, None)
        mock_exit.assert_called_once_with("Invalid format: invalid-format")
        mock_get_report_format.assert_called_once()

    @patch("builtins.input", side_effect=["", "", ""])
    @patch(
        "amd_debug.s2idle.get_report_file",
        return_value="amd-s2idle-report-2023-01-01.html",
    )
    @patch("amd_debug.s2idle.get_report_format", return_value="html")
    def test_prompt_report_arguments_defaults(
        self, mock_get_report_format, mock_get_report_file, mock_input
    ):
        """Test prompt_report_arguments with default values"""
        result = prompt_report_arguments(None, None, None, None)
        self.assertEqual(datetime.date(result[0]), Defaults.since)
        self.assertEqual(datetime.date(result[1]), Defaults.until)
        self.assertEqual(result[2], "amd-s2idle-report-2023-01-01.html")
        self.assertEqual(result[3], "html")
        mock_get_report_file.assert_called_once_with(None, "html")
        mock_get_report_format.assert_called()

#!/usr/bin/python3
# SPDX-License-Identifier: MIT

"""
This module contains unit tests for the common functions in the amd-debug-tools package.
"""
from unittest.mock import patch, mock_open, call

import logging
import tempfile
import unittest
import os
from platform import uname_result


from amd_debug.common import (
    apply_prefix_wrapper,
    Colors,
    colorize_choices,
    check_lockdown,
    compare_file,
    fatal_error,
    get_distro,
    get_log_priority,
    get_pretty_distro,
    is_root,
    minimum_kernel,
    print_color,
    run_countdown,
    systemd_in_use,
    running_ssh,
)

color_dict = {
    "🚦": Colors.WARNING,
    "🦟": Colors.DEBUG,
    "❌": Colors.FAIL,
    "👀": Colors.FAIL,
    "✅": Colors.OK,
    "🔋": Colors.OK,
    "🐧": Colors.OK,
    "💻": Colors.OK,
    "○": Colors.OK,
    "💤": Colors.OK,
    "💯": Colors.UNDERLINE,
    "🗣️": Colors.HEADER,
}


class TestCommon(unittest.TestCase):
    """Test common functions"""

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(filename="/dev/null", level=logging.DEBUG)

    def test_read_compare_file(self):
        """Test read_file and compare_file strip files correctly"""

        f = tempfile.NamedTemporaryFile()
        f.write("foo bar baz\n ".encode("utf-8"))
        f.seek(0)
        self.assertTrue(compare_file(f.name, "foo bar baz"))

    def test_countdown(self):
        """Test countdown function"""

        result = run_countdown("Full foo", 1)
        self.assertTrue(result)
        result = run_countdown("Half foo", 0.5)
        self.assertTrue(result)
        result = run_countdown("No foo", 0)
        self.assertTrue(result)
        result = run_countdown("Negative foo", -1)
        self.assertFalse(result)

    @patch("os.path.exists", return_value=True)
    @patch("builtins.open", new_callable=mock_open, read_data="ID=foo\nVERSION_ID=bar")
    def test_get_distro_known(self, mock_exists, _mock_open):
        """Test get_distro function"""
        distro = get_distro()
        mock_exists.assert_has_calls(
            [
                call("/etc/os-release", "r", encoding="utf-8"),
                call().__enter__(),
                call().__iter__(),
                call().__exit__(None, None, None),
            ]
        )
        self.assertEqual(distro, "foo")

    @patch("os.path.exists", return_value=False)
    def test_get_distro_unknown(self, mock_exists):
        """Test get_distro function"""
        distro = get_distro()
        mock_exists.assert_has_calls(
            [
                call("/etc/os-release"),
                call("/etc/arch-release"),
                call("/etc/fedora-release"),
                call("/etc/debian_version"),
            ]
        )
        self.assertEqual(distro, "unknown")

    @patch("os.path.exists", return_value=True)
    @patch("builtins.open", new_callable=mock_open, read_data="PRETTY_NAME=Foo")
    def test_get_pretty_distro_known(self, mock_exists, _mock_open):
        """Test get_distro function"""
        distro = get_pretty_distro()
        self.assertEqual(distro, "Foo")
        mock_exists.assert_has_calls(
            [
                call("/etc/os-release", "r", encoding="utf-8"),
                call().__enter__(),
                call().__iter__(),
                call().__exit__(None, None, None),
            ]
        )

    @patch("os.path.exists", return_value=False)
    def test_get_pretty_distro_unknown(self, mock_exists):
        """Test get_distro function"""
        distro = get_pretty_distro()
        self.assertEqual(distro, "Unknown")
        mock_exists.assert_has_calls(
            [
                call("/etc/os-release"),
            ]
        )

    @patch("os.path.exists", return_value=True)
    @patch(
        "builtins.open",
        new_callable=mock_open,
        read_data="[none] integrity confidentiality",
    )
    def test_lockdown_pass(self, mock_exists, _mock_file):
        """Test lockdown function"""
        lockdown = check_lockdown()
        mock_exists.assert_called_once_with(
            "/sys/kernel/security/lockdown", "r", encoding="utf-8"
        )
        self.assertFalse(lockdown)

    @patch("os.path.exists", return_value=True)
    @patch(
        "builtins.open",
        new_callable=mock_open,
        read_data="none [integrity] confidentiality",
    )
    def test_lockdown_fail_integrity(self, mock_exists, _mock_file):
        """Test lockdown function"""
        lockdown = check_lockdown()
        mock_exists.assert_called_once_with(
            "/sys/kernel/security/lockdown", "r", encoding="utf-8"
        )
        self.assertTrue(lockdown)

    @patch("os.path.exists", return_value=True)
    @patch(
        "builtins.open",
        new_callable=mock_open,
        read_data="none integrity [confidentiality]",
    )
    def test_lockdown_fail_confidentiality(self, mock_exists, _mock_file):
        """Test lockdown function"""
        lockdown = check_lockdown()
        mock_exists.assert_called_once_with(
            "/sys/kernel/security/lockdown", "r", encoding="utf-8"
        )
        self.assertTrue(lockdown)

    @patch("os.path.exists", return_value=False)
    def test_lockdown_missing(self, mock_exists):
        """Test lockdown function"""
        lockdown = check_lockdown()
        mock_exists.assert_called_once_with("/sys/kernel/security/lockdown")
        self.assertFalse(lockdown)

    @patch("builtins.print")
    def test_print_color(self, mocked_print):
        """Test print_color function for all expected levels"""
        message = "foo"
        # test all color groups
        for group, color in color_dict.items():
            prefix = f"{group} "
            print_color(message, group)
            mocked_print.assert_called_once_with(
                f"{prefix}{color}{message}{Colors.ENDC}"
            )
            mocked_print.reset_mock()

        # call without a group
        print_color(message, Colors.WARNING)
        mocked_print.assert_called_once_with(f"{Colors.WARNING}{message}{Colors.ENDC}")
        mocked_print.reset_mock()

        # test dumb terminal
        os.environ["TERM"] = "dumb"
        print_color(message, Colors.WARNING)
        mocked_print.assert_called_once_with(f"{message}")

    @patch("builtins.print")
    def test_fatal_error(self, mocked_print):
        """Test fatal_error function"""
        with patch("sys.exit") as mock_exit:
            fatal_error("foo")
            mocked_print.assert_called_once_with(f"👀 {Colors.FAIL}foo{Colors.ENDC}")
            mock_exit.assert_called_once_with(1)

    @patch("os.geteuid", return_value=0)
    def test_is_root_true(self, mock_geteuid):
        """Test is_root function when user is root"""
        self.assertTrue(is_root())
        mock_geteuid.assert_called_once()
        self.assertEqual(mock_geteuid.call_count, 1)

    @patch("os.geteuid", return_value=1000)
    def test_is_root_false(self, mock_geteuid):
        """Test is_root function when user is not root"""
        self.assertFalse(is_root())
        mock_geteuid.assert_called_once()
        self.assertEqual(mock_geteuid.call_count, 1)

    def test_get_log_priority(self):
        """Test get_log_priority works for expected values"""
        ret = get_log_priority(None)
        self.assertEqual(ret, "○")
        ret = get_log_priority("foo")
        self.assertEqual(ret, "foo")
        ret = get_log_priority("3")
        self.assertEqual(ret, "❌")
        ret = get_log_priority(4)
        self.assertEqual(ret, "🚦")
        ret = get_log_priority(7)
        self.assertEqual(ret, "🦟")

    def test_minimum_kernel(self):
        """Test minimum_kernel function"""
        with patch("platform.uname") as mock_uname:
            mock_uname.return_value = uname_result(
                system="Linux",
                node="foo",
                release="6.12.0-rc5",
                version="baz",
                machine="x86_64",
            )
            self.assertTrue(minimum_kernel("6", "12"))
            self.assertFalse(minimum_kernel("6", "13"))
            self.assertTrue(minimum_kernel(5, 1))
            self.assertFalse(minimum_kernel(7, 1))
            with self.assertRaises(ValueError):
                minimum_kernel("foo", "bar")
            with self.assertRaises(TypeError):
                minimum_kernel(None, None)

    def test_systemd_in_use(self):
        """Test systemd_in_use function"""
        with patch(
            "builtins.open", new_callable=mock_open, read_data="systemd"
        ) as mock_file:
            self.assertTrue(systemd_in_use())
            mock_file.assert_called_once_with("/proc/1/comm", "r", encoding="utf-8")
        with patch(
            "builtins.open", new_callable=mock_open, read_data="upstart"
        ) as mock_file:
            self.assertFalse(systemd_in_use())
            mock_file.assert_called_once_with("/proc/1/comm", "r", encoding="utf-8")

    def test_running_in_ssh(self):
        """Test running_in_ssh function"""
        with patch("os.environ", {"SSH_TTY": "/dev/pts/0"}):
            self.assertTrue(running_ssh())
        with patch("os.environ", {}):
            self.assertFalse(running_ssh())

    def test_apply_prefix_wrapper(self):
        """Test apply_prefix_wrapper function"""
        header = "Header:"
        message = "Line 1\nLine 2\nLine 3"
        expected_output = "Header:\n" "│ Line 1\n" "│ Line 2\n" "└─ Line 3\n"
        self.assertEqual(apply_prefix_wrapper(header, message), expected_output)

        # Test with a single line message
        message = "Single Line"
        expected_output = "Header:\n└─ Single Line\n"
        self.assertEqual(apply_prefix_wrapper(header, message), expected_output)

        # Test with an empty message
        message = ""
        expected_output = "Header:\n"
        self.assertEqual(apply_prefix_wrapper(header, message), expected_output)

        # Test with leading/trailing whitespace in the message
        message = "  Line 1\nLine 2  \n  Line 3  "
        expected_output = "Header:\n" "│ Line 1\n" "│ Line 2\n" "└─ Line 3\n"
        self.assertEqual(apply_prefix_wrapper(header, message), expected_output)

    def test_colorize_choices_with_default(self):
        """Test colorize_choices function with a default value"""
        choices = ["option1", "option2", "option3"]
        default = "option2"
        expected_output = f"{Colors.OK}{default}{Colors.ENDC}, option1, option3"
        self.assertEqual(colorize_choices(choices, default), expected_output)

    def test_colorize_choices_without_default(self):
        """Test colorize_choices function when default is not in choices"""
        choices = ["option1", "option2", "option3"]
        default = "option4"
        with self.assertRaises(ValueError) as context:
            colorize_choices(choices, default)
        self.assertEqual(
            str(context.exception), "Default choice 'option4' not in choices"
        )

    def test_colorize_choices_empty_list(self):
        """Test colorize_choices function with an empty list"""
        choices = []
        default = "option1"
        with self.assertRaises(ValueError) as context:
            colorize_choices(choices, default)
        self.assertEqual(
            str(context.exception), "Default choice 'option1' not in choices"
        )

    def test_colorize_choices_single_choice(self):
        """Test colorize_choices function with a single choice"""
        choices = ["option1"]
        default = "option1"
        expected_output = f"{Colors.OK}{default}{Colors.ENDC}"
        self.assertEqual(colorize_choices(choices, default), expected_output)

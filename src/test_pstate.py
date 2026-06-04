#!/usr/bin/python3
# SPDX-License-Identifier: MIT

"""
This module contains unit tests for the pstate tool in the amd-debug-tools package.
"""

import logging
import unittest
from unittest.mock import patch, MagicMock

from amd_debug.pstate import (
    AmdPstateTriage,
    amd_cppc_cap_lowest_perf,
    amd_cppc_cap_lownonlin_perf,
    amd_cppc_cap_nominal_perf,
    amd_cppc_cap_highest_perf,
    amd_cppc_max_perf,
    amd_cppc_min_perf,
    amd_cppc_des_perf,
    amd_cppc_epp_perf,
)


class TestAmdPstateTriage(unittest.TestCase):
    """Test AmdPstateTriage class"""

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(filename="/dev/null", level=logging.DEBUG)

    @patch("amd_debug.pstate.relaunch_sudo")
    @patch("amd_debug.pstate.get_pretty_distro", return_value="Test Distro")
    @patch("amd_debug.pstate.print_color")
    @patch("amd_debug.pstate.Context")
    def test_init(
        self,
        _mock_context,
        mock_print_color,
        mock_get_pretty_distro,
        mock_relaunch_sudo,
    ):
        """Test initialization of AmdPstateTriage class"""
        triage = AmdPstateTriage(logging=True)
        mock_relaunch_sudo.assert_called_once()
        mock_get_pretty_distro.assert_called_once()
        mock_print_color.assert_called_with("Test Distro", "🐧")
        self.assertIsNotNone(triage.context)

    @patch("amd_debug.pstate.os.path.exists", return_value=True)
    @patch("amd_debug.pstate.read_file", return_value="test_value")
    @patch("amd_debug.pstate.print_color")
    @patch("amd_debug.pstate.relaunch_sudo")
    def test_gather_amd_pstate_info(
        self, _mock_relaunch_sudo, mock_print_color, mock_read_file, mock_path_exists
    ):
        """Test gather_amd_pstate_info method"""
        triage = AmdPstateTriage(logging=False)
        triage.gather_amd_pstate_info()
        mock_path_exists.assert_called()
        mock_read_file.assert_called()
        mock_print_color.assert_any_call("'status':\ttest_value", "○")
        mock_print_color.assert_any_call("'prefcore':\ttest_value", "○")

    @patch(
        "amd_debug.pstate.os.uname",
        return_value=MagicMock(sysname="Linux", release="5.15.0"),
    )
    @patch("amd_debug.pstate.print_color")
    @patch("amd_debug.pstate.relaunch_sudo")
    def test_gather_kernel_info(
        self, _mock_relaunch_sudo, mock_print_color, mock_uname
    ):
        """Test gather_kernel_info method"""
        triage = AmdPstateTriage(logging=False)
        triage.gather_kernel_info()
        mock_uname.assert_called()
        mock_print_color.assert_called_with("Kernel:\t5.15.0", "🐧")

    @patch("amd_debug.pstate.os.path.exists", return_value=True)
    @patch("amd_debug.pstate.read_file", return_value="1")
    @patch("amd_debug.pstate.print_color")
    @patch("amd_debug.pstate.relaunch_sudo")
    def test_gather_scheduler_info(
        self, _mock_relaunch_sudo, mock_print_color, mock_read_file, mock_path_exists
    ):
        """Test gather_scheduler_info method"""
        triage = AmdPstateTriage(logging=False)
        triage.gather_scheduler_info()
        mock_path_exists.assert_called()
        mock_read_file.assert_called()
        mock_print_color.assert_any_call("ITMT:\t1", "🐧")

    @patch("amd_debug.pstate.read_msr")
    @patch("amd_debug.pstate.print_color")
    @patch("amd_debug.pstate.Context")
    @patch("amd_debug.pstate.relaunch_sudo")
    def test_gather_msrs(
        self, _mock_relaunch_sudo, mock_context, mock_print_color, mock_read_msr
    ):
        """Test gather_msrs method"""
        # Mock the list of CPUs
        mock_context.return_value.list_devices.return_value = [
            MagicMock(sys_name="cpu0"),
            MagicMock(sys_name="cpu1"),
        ]

        # Mock MSR values for the CPUs
        mock_read_msr.side_effect = [
            0x1,  # MSR_AMD_CPPC_ENABLE for cpu0
            0x2,  # MSR_AMD_CPPC_STATUS for cpu0
            0x12345678,  # MSR_AMD_CPPC_CAP1 for cpu0
            0x87654321,  # MSR_AMD_CPPC_CAP2 for cpu0
            0xABCDEF,  # MSR_AMD_CPPC_REQ for cpu0
            0x1,  # MSR_AMD_CPPC_ENABLE for cpu1
            0x2,  # MSR_AMD_CPPC_STATUS for cpu1
            0x12345678,  # MSR_AMD_CPPC_CAP1 for cpu1
            0x87654321,  # MSR_AMD_CPPC_CAP2 for cpu1
            0xABCDEF,  # MSR_AMD_CPPC_REQ for cpu1
        ]

        triage = AmdPstateTriage(logging=False)
        result = triage.gather_msrs()

        # Assert that MSR values were read for both CPUs
        self.assertEqual(mock_read_msr.call_count, 10)

        # Assert that print_color was called to display the MSR information
        self.assertTrue(mock_print_color.called)

        # Assert that the method returned True (indicating success)
        self.assertIsNone(result)

    def test_amd_cppc_cap_lowest_perf(self):
        """Test amd_cppc_cap_lowest_perf function"""
        self.assertEqual(amd_cppc_cap_lowest_perf(0x12345678), 0x78)

    def test_amd_cppc_cap_lownonlin_perf(self):
        """Test amd_cppc_cap_lownonlin_perf function"""
        self.assertEqual(amd_cppc_cap_lownonlin_perf(0x12345678), 0x56)

    def test_amd_cppc_cap_nominal_perf(self):
        """Test amd_cppc_cap_nominal_perf function"""
        self.assertEqual(amd_cppc_cap_nominal_perf(0x12345678), 0x34)

    def test_amd_cppc_cap_highest_perf(self):
        """Test amd_cppc_cap_highest_perf function"""
        self.assertEqual(amd_cppc_cap_highest_perf(0x12345678), 0x12)

    def test_amd_cppc_max_perf(self):
        """Test amd_cppc_max_perf function"""
        self.assertEqual(amd_cppc_max_perf(0x12345678), 0x78)

    def test_amd_cppc_min_perf(self):
        """Test amd_cppc_min_perf function"""
        self.assertEqual(amd_cppc_min_perf(0x12345678), 0x56)

    def test_amd_cppc_des_perf(self):
        """Test amd_cppc_des_perf function"""
        self.assertEqual(amd_cppc_des_perf(0x12345678), 0x34)

    def test_amd_cppc_epp_perf(self):
        """Test amd_cppc_epp_perf function"""
        self.assertEqual(amd_cppc_epp_perf(0x12345678), 0x12)

    @patch("amd_debug.pstate.read_file", return_value="data")
    @patch("amd_debug.pstate.os.path.exists", return_value=True)
    @patch("amd_debug.pstate.print_color")
    @patch("amd_debug.pstate.Context")
    @patch("amd_debug.pstate.relaunch_sudo")
    def test_gather_cpu_info(
        self,
        _mock_relaunch_sudo,
        mock_context,
        mock_print_color,
        _mock_path_exists,
        mock_read_file,
    ):
        """gather_cpu_info builds a CPU dataframe and prints it"""
        cpu0 = MagicMock(sys_name="cpu0", sys_path="/sys/devices/system/cpu/cpu0")
        cpu1 = MagicMock(sys_name="cpu1", sys_path="/sys/devices/system/cpu/cpu1")
        mock_context.return_value.list_devices.return_value = [cpu1, cpu0]

        # cpuinfo read needs to contain a "model name" line
        def _read(path):
            if path == "/proc/cpuinfo":
                return "model name\t: AMD Test CPU\n"
            return "1"

        mock_read_file.side_effect = _read

        triage = AmdPstateTriage(logging=False)
        triage.gather_cpu_info()
        # ensure CPU model line printed
        mock_print_color.assert_any_call("CPU:\t\tAMD Test CPU", "💻")

    @patch("amd_debug.pstate.read_msr", side_effect=FileNotFoundError())
    @patch("amd_debug.pstate.print_color")
    @patch("amd_debug.pstate.Context")
    @patch("amd_debug.pstate.relaunch_sudo")
    def test_gather_msrs_module_missing(
        self, _mock_relaunch_sudo, mock_context, mock_print_color, _mock_read_msr
    ):
        """gather_msrs returns False when MSR module not loaded"""
        mock_context.return_value.list_devices.return_value = [
            MagicMock(sys_name="cpu0"),
        ]
        triage = AmdPstateTriage(logging=False)
        result = triage.gather_msrs()
        self.assertFalse(result)
        mock_print_color.assert_any_call(
            "Unable to check MSRs: MSR kernel module not loaded", "❌"
        )

    @patch("amd_debug.pstate.read_msr", side_effect=PermissionError())
    @patch("amd_debug.pstate.print_color")
    @patch("amd_debug.pstate.Context")
    @patch("amd_debug.pstate.relaunch_sudo")
    def test_gather_msrs_permission(
        self, _mock_relaunch_sudo, mock_context, mock_print_color, _mock_read_msr
    ):
        """gather_msrs returns silently when MSR reads denied"""
        mock_context.return_value.list_devices.return_value = [
            MagicMock(sys_name="cpu0"),
        ]
        triage = AmdPstateTriage(logging=False)
        result = triage.gather_msrs()
        self.assertIsNone(result)
        mock_print_color.assert_any_call("MSR checks unavailable", "🚦")

    @patch("amd_debug.pstate.print_color")
    @patch("amd_debug.pstate.Context")
    @patch("amd_debug.pstate.relaunch_sudo")
    def test_run_cpu_info_failure(
        self, _mock_relaunch_sudo, _mock_context, mock_print_color
    ):
        """run returns False when gather_cpu_info raises FileNotFoundError"""
        triage = AmdPstateTriage(logging=False)
        with patch.object(triage, "gather_kernel_info"), \
             patch.object(triage, "gather_amd_pstate_info"), \
             patch.object(triage, "gather_scheduler_info"), \
             patch.object(
                 triage, "gather_cpu_info", side_effect=FileNotFoundError()
             ):
            result = triage.run()
        self.assertFalse(result)
        mock_print_color.assert_any_call("Unable to gather CPU information", "❌")

    @patch("amd_debug.pstate.print_color")
    @patch("amd_debug.pstate.Context")
    @patch("amd_debug.pstate.relaunch_sudo")
    def test_run_success(self, _mock_relaunch_sudo, _mock_context, _mock_print_color):
        """run returns True when all gather steps succeed"""
        triage = AmdPstateTriage(logging=False)
        with patch.object(triage, "gather_kernel_info"), \
             patch.object(triage, "gather_amd_pstate_info"), \
             patch.object(triage, "gather_scheduler_info"), \
             patch.object(triage, "gather_cpu_info"), \
             patch.object(triage, "gather_msrs"):
            self.assertTrue(triage.run())


class TestPstateMain(unittest.TestCase):
    """Test the pstate module-level main/parse_args helpers"""

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(filename="/dev/null", level=logging.DEBUG)

    @patch("amd_debug.pstate.sys.argv", ["amd_pstate"])
    def test_parse_args_no_args_exits(self):
        """parse_args exits when no arguments provided"""
        from amd_debug.pstate import parse_args
        with self.assertRaises(SystemExit):
            parse_args()

    @patch("amd_debug.pstate.sys.argv", ["amd_pstate", "--version"])
    def test_parse_args_version(self):
        """parse_args parses --version"""
        from amd_debug.pstate import parse_args
        args = parse_args()
        self.assertTrue(args.version)

    @patch("amd_debug.pstate.sys.argv", ["amd_pstate", "triage", "--tool-debug"])
    def test_parse_args_triage(self):
        """parse_args parses triage subcommand"""
        from amd_debug.pstate import parse_args
        args = parse_args()
        self.assertEqual(args.command, "triage")
        self.assertTrue(args.tool_debug)

    @patch("amd_debug.pstate.version", return_value="1.2.3")
    @patch("amd_debug.pstate.parse_args")
    def test_main_version(self, mock_parse, mock_version):
        """main prints version and returns None"""
        from amd_debug.pstate import main
        mock_parse.return_value = MagicMock(version=True, command=None)
        self.assertIsNone(main())
        mock_version.assert_called_once()

    @patch("amd_debug.pstate.show_log_info")
    @patch("amd_debug.pstate.AmdPstateTriage")
    @patch("amd_debug.pstate.parse_args")
    def test_main_triage_success(self, mock_parse, mock_triage_cls, _mock_show):
        """main returns None when triage succeeds"""
        from amd_debug.pstate import main
        mock_parse.return_value = MagicMock(
            version=False, command="triage", tool_debug=False
        )
        mock_triage_cls.return_value.run.return_value = True
        self.assertIsNone(main())

    @patch("amd_debug.pstate.show_log_info")
    @patch("amd_debug.pstate.AmdPstateTriage")
    @patch("amd_debug.pstate.parse_args")
    def test_main_triage_failure(self, mock_parse, mock_triage_cls, _mock_show):
        """main returns 1 when triage fails"""
        from amd_debug.pstate import main
        mock_parse.return_value = MagicMock(
            version=False, command="triage", tool_debug=False
        )
        mock_triage_cls.return_value.run.return_value = False
        self.assertEqual(main(), 1)

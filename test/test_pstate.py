#!/usr/bin/python3
# SPDX-License-Identifier: MIT

"""
This module contains unit tests for the pstate tool in the amd-debug-tools package.
"""

import logging
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from amd_debug.pstate import (
    AmdPstateTriage,
    MSR,
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

#!/usr/bin/python3
# SPDX-License-Identifier: MIT

"""
This module contains unit tests for the Intel specific prerequisite
functions in the amd-debug-tools package.
"""

import logging
import unittest
from unittest.mock import patch, MagicMock

from amd_debug.prereq.intel import IntelPrerequisiteValidator
from amd_debug.failures import (
    IntelDmcFirmwareMissing,
    MissingIntelGraphics,
    MissingIntelPmcCore,
    S0ixNotReached,
)
from amd_debug.intel import S0IX_SUBSTATES


class TestIntelPrerequisiteValidator(unittest.TestCase):
    """Unit tests for the Intel prerequisite validator"""

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(filename="/dev/null", level=logging.DEBUG)

    @patch("amd_debug.prereq.base.is_root", return_value=True)
    @patch("amd_debug.prereq.base.get_kernel_log")
    @patch("amd_debug.prereq.base.get_distro", return_value="Ubuntu")
    @patch("amd_debug.prereq.base.read_file", return_value="mocked_cmdline")
    @patch("amd_debug.prereq.base.pyudev.Context")
    @patch("amd_debug.prereq.base.SleepDatabase")
    def setUp(
        self,
        MockSleepDatabase,
        MockPyudev,
        _mock_read_file,
        _mock_get_distro,
        mock_get_kernel_log,
        _mock_is_root,
    ):
        self.mock_db = MockSleepDatabase.return_value
        self.mock_pyudev = MockPyudev.return_value
        self.mock_kernel_log = mock_get_kernel_log.return_value
        self.validator = IntelPrerequisiteValidator(tool_debug=True)

    @patch("amd_debug.prereq.intel.intel_pmc_core_loaded")
    def test_check_intel_pmc_core_loaded(self, mock_loaded):
        """Test check_intel_pmc_core when the driver is loaded"""
        mock_loaded.return_value = True
        result = self.validator.check_intel_pmc_core()
        self.assertTrue(result)
        self.assertEqual(self.validator.failures, [])

    @patch("amd_debug.prereq.intel.intel_pmc_core_loaded")
    def test_check_intel_pmc_core_missing(self, mock_loaded):
        """Test check_intel_pmc_core when the driver is missing"""
        mock_loaded.return_value = False
        result = self.validator.check_intel_pmc_core()
        self.assertFalse(result)
        self.assertTrue(
            any(isinstance(f, MissingIntelPmcCore) for f in self.validator.failures)
        )

    @patch("amd_debug.prereq.intel.get_intel_graphics_driver")
    def test_check_intel_graphics_found(self, mock_driver):
        """Test check_intel_graphics when a driver is present"""
        mock_driver.return_value = "i915"
        result = self.validator.check_intel_graphics()
        self.assertTrue(result)
        self.assertEqual(self.validator.failures, [])

    @patch("amd_debug.prereq.intel.get_intel_graphics_driver")
    def test_check_intel_graphics_missing(self, mock_driver):
        """Test check_intel_graphics when no driver is present"""
        mock_driver.return_value = ""
        result = self.validator.check_intel_graphics()
        self.assertFalse(result)
        self.assertTrue(
            any(isinstance(f, MissingIntelGraphics) for f in self.validator.failures)
        )

    @patch("amd_debug.prereq.intel.get_dmc_firmware_status")
    @patch("amd_debug.prereq.intel.get_intel_graphics_driver")
    def test_check_intel_dmc_xe_driver(self, mock_driver, mock_status):
        """Test check_intel_dmc with the xe driver

        The xe driver exposes the i915_dmc_info debugfs interface since
        kernel 6.14 when it is built with display support.
        """
        mock_driver.return_value = "xe"
        mock_status.return_value = {"fw loaded": "yes", "version": "2.23"}
        result = self.validator.check_intel_dmc()
        self.assertTrue(result)
        self.assertEqual(self.validator.failures, [])
        self.mock_db.record_prereq.assert_called_with(
            "Intel display firmware loaded (2.23)", "✅"
        )

    @patch("amd_debug.prereq.intel.get_dmc_firmware_status")
    @patch("amd_debug.prereq.intel.get_intel_graphics_driver")
    def test_check_intel_dmc_xe_driver_unknown_status(
        self, mock_driver, mock_status
    ):
        """Test check_intel_dmc with xe when the status is unavailable"""
        mock_driver.return_value = "xe"
        mock_status.return_value = {}
        result = self.validator.check_intel_dmc()
        self.assertTrue(result)
        self.mock_db.record_prereq.assert_called_with(
            "Unable to determine Intel display firmware status", "🚦"
        )

    @patch("amd_debug.prereq.intel.get_dmc_firmware_status")
    @patch("amd_debug.prereq.intel.get_intel_graphics_driver")
    def test_check_intel_dmc_loaded(self, mock_driver, mock_status):
        """Test check_intel_dmc when the firmware is loaded"""
        mock_driver.return_value = "i915"
        mock_status.return_value = {"fw loaded": "yes", "DMC firmware": "4.11"}
        result = self.validator.check_intel_dmc()
        self.assertTrue(result)
        self.assertEqual(self.validator.failures, [])
        self.mock_db.record_prereq.assert_called_once_with(
            "Intel display firmware loaded (4.11)", "✅"
        )

    @patch("amd_debug.prereq.intel.get_dmc_firmware_status")
    @patch("amd_debug.prereq.intel.get_intel_graphics_driver")
    def test_check_intel_dmc_loaded_version_key(self, mock_driver, mock_status):
        """Test check_intel_dmc when the version is in the 'version' key

        Newer kernels expose the firmware version in the 'version' key
        instead of the 'DMC firmware' key.
        """
        mock_driver.return_value = "i915"
        mock_status.return_value = {"fw loaded": "yes", "version": "2.23"}
        result = self.validator.check_intel_dmc()
        self.assertTrue(result)
        self.assertEqual(self.validator.failures, [])
        self.mock_db.record_prereq.assert_called_once_with(
            "Intel display firmware loaded (2.23)", "✅"
        )

    @patch("amd_debug.prereq.intel.get_dmc_firmware_status")
    @patch("amd_debug.prereq.intel.get_intel_graphics_driver")
    def test_check_intel_dmc_loaded_no_version(self, mock_driver, mock_status):
        """Test check_intel_dmc when the version is missing"""
        mock_driver.return_value = "i915"
        mock_status.return_value = {"fw loaded": "yes"}
        result = self.validator.check_intel_dmc()
        self.assertTrue(result)
        self.assertEqual(self.validator.failures, [])
        self.mock_db.record_prereq.assert_called_once_with(
            "Intel display firmware loaded", "✅"
        )

    @patch("amd_debug.prereq.intel.get_dmc_firmware_status")
    @patch("amd_debug.prereq.intel.get_intel_graphics_driver")
    def test_check_intel_dmc_not_loaded(self, mock_driver, mock_status):
        """Test check_intel_dmc when the firmware is missing"""
        mock_driver.return_value = "i915"
        mock_status.return_value = {"fw loaded": "no"}
        result = self.validator.check_intel_dmc()
        self.assertFalse(result)
        self.assertTrue(
            any(isinstance(f, IntelDmcFirmwareMissing) for f in self.validator.failures)
        )

    @patch("amd_debug.prereq.intel.get_dmc_firmware_status")
    @patch("amd_debug.prereq.intel.get_intel_graphics_driver")
    def test_check_intel_dmc_unknown(self, mock_driver, mock_status):
        """Test check_intel_dmc when the status is unavailable"""
        mock_driver.return_value = "i915"
        mock_status.return_value = {}
        result = self.validator.check_intel_dmc()
        self.assertTrue(result)
        self.assertEqual(self.validator.failures, [])

    @patch("amd_debug.prereq.intel.get_lps0_disabled")
    def test_check_lps0_interface_enabled(self, mock_disabled):
        """Test check_lps0_interface when the interface is enabled"""
        mock_disabled.return_value = False
        result = self.validator.check_lps0_interface()
        self.assertTrue(result)
        self.assertEqual(self.validator.failures, [])

    @patch("amd_debug.prereq.intel.get_lps0_disabled")
    def test_check_lps0_interface_disabled(self, mock_disabled):
        """Test check_lps0_interface when the interface is disabled"""
        mock_disabled.return_value = True
        result = self.validator.check_lps0_interface()
        self.assertFalse(result)
        self.assertTrue(
            any(isinstance(f, S0ixNotReached) for f in self.validator.failures)
        )

    @patch("amd_debug.prereq.intel.get_lps0_disabled")
    def test_check_lps0_interface_unknown(self, mock_disabled):
        """Test check_lps0_interface when the status can't be determined"""
        mock_disabled.return_value = None
        result = self.validator.check_lps0_interface()
        self.assertTrue(result)
        self.assertEqual(self.validator.failures, [])

    def test_check_cpu_unknown_family(self):
        """Test check_cpu when the CPU family can't be determined"""
        self.validator.cpu_family = None
        result = self.validator.check_cpu()
        self.assertTrue(result)

    def test_check_cpu_not_intel(self):
        """Test check_cpu with a non-Intel family"""
        self.validator.cpu_family = 0x19
        result = self.validator.check_cpu()
        self.assertTrue(result)

    def test_check_cpu_intel(self):
        """Test check_cpu with an Intel family"""
        self.validator.cpu_family = 6
        result = self.validator.check_cpu()
        self.assertTrue(result)

    def test_capture_pmc_core_unavailable(self):
        """Test capture_pmc_core when the debugfs isn't available"""
        self.validator.pmc_core.available = False
        self.validator.capture_pmc_core()
        self.mock_db.record_debug.assert_called_with(
            "Intel PMC core debugfs is not available"
        )

    @patch("amd_debug.prereq.intel.IntelPmcCore")
    def test_capture_pmc_core(self, mock_pmc):
        """Test capture_pmc_core with data available"""
        pmc = mock_pmc.return_value
        self.validator.pmc_core = pmc
        pmc.available = True
        pmc.slp_s0_residency = 1000
        pmc.substate_residencies = {"S0i3.0": 240}
        pmc.substate_requirements = (
            "                                     Element |    S0i2.0 | Status\n"
            "pmc0:                       PMC OPI S0i2.0 |  Required |      No\n"
        )
        pmc.substate_status_registers = "STATUS DATA"
        pmc.substate_live_status_registers = "LIVE DATA"
        self.validator.capture_pmc_core()
        pmc.capture.assert_called_once()
        messages = [call[0][0] for call in self.mock_db.record_debug.call_args_list]
        self.assertIn("SLP_S0 residency: 1000 usec", messages)
        self.assertTrue(any("S0ix substate residency" in m for m in messages))
        self.assertTrue(any("S0ix substate blockers" in m for m in messages))
        self.assertTrue(any("STATUS DATA" in m for m in messages))
        self.assertTrue(any("LIVE DATA" in m for m in messages))

    @patch("amd_debug.prereq.intel.get_dmc_firmware_status")
    def test_capture_intel_graphics_firmware(self, mock_status):
        """Test capture_intel_graphics_firmware with data"""
        mock_status.return_value = {"fw loaded": "yes"}
        self.validator.capture_intel_graphics_firmware()
        messages = [call[0][0] for call in self.mock_db.record_debug.call_args_list]
        self.assertTrue(any("fw loaded: yes" in m for m in messages))

    @patch("amd_debug.prereq.intel.get_dmc_firmware_status")
    def test_capture_intel_graphics_firmware_empty(self, mock_status):
        """Test capture_intel_graphics_firmware without data"""
        mock_status.return_value = {}
        self.validator.capture_intel_graphics_firmware()
        self.mock_db.record_debug.assert_not_called()

    @patch("amd_debug.prereq.intel.os.path.isdir")
    @patch("amd_debug.prereq.intel.os.listdir")
    @patch("amd_debug.prereq.intel.os.path.exists")
    @patch("amd_debug.prereq.intel.read_file")
    def test_capture_intel_cpuidle(
        self, mock_read_file, mock_exists, mock_listdir, mock_isdir
    ):
        """Test capture_intel_cpuidle with idle states present"""
        mock_isdir.return_value = True
        mock_listdir.return_value = ["state0", "state1", "something_else"]
        mock_exists.return_value = True
        mock_read_file.side_effect = lambda p: "C1" if "name" in p else "10"
        self.validator.capture_intel_cpuidle()
        messages = [call[0][0] for call in self.mock_db.record_debug.call_args_list]
        self.assertTrue(any("state0: C1 (latency 10 usec)" in m for m in messages))
        self.assertTrue(any("state1: C1 (latency 10 usec)" in m for m in messages))

    @patch("amd_debug.prereq.intel.os.path.isdir")
    def test_capture_intel_cpuidle_missing(self, mock_isdir):
        """Test capture_intel_cpuidle without a cpuidle directory"""
        mock_isdir.return_value = False
        self.validator.capture_intel_cpuidle()
        self.mock_db.record_debug.assert_not_called()

    def test_substates_known(self):
        """Test that the known S0ix substates are documented"""
        self.assertEqual(len(S0IX_SUBSTATES), 8)
        self.assertIn("S0i2.0", S0IX_SUBSTATES)
        self.assertIn("S0i3.4", S0IX_SUBSTATES)


if __name__ == "__main__":
    unittest.main()

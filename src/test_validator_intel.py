#!/usr/bin/python3
# SPDX-License-Identifier: MIT

"""
This module contains unit tests for the Intel specific sleep validator
capture functions in the amd-debug-tools package.
"""

import logging
import unittest
from unittest.mock import patch, MagicMock

from amd_debug.validator.intel import IntelCaptureHelpers

SUBSTATE_RESIDENCIES = """pmc0        Substate     Residency
          S0i2.0              0
          S0i3.0            240
"""


class FakeIntelCapture(IntelCaptureHelpers):
    """Minimal stand-in for the sleep validator"""

    def __init__(self):
        self.db = MagicMock()
        self.pmc_core = None
        self.s0ix_residency = 0
        self.s0ix_residency_before = None
        self.s0ix_substates_before = {}


class TestIntelCaptureHelpers(unittest.TestCase):
    """Unit tests for the Intel capture helpers"""

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(filename="/dev/null", level=logging.DEBUG)

    def setUp(self):
        """Set up a mock context for testing"""
        self.validator = FakeIntelCapture()

    @patch("amd_debug.validator.intel.IntelPmcCore")
    def test_capture_intel_s0ix_unavailable(self, mock_pmc):
        """Test that nothing is captured when the PMC core is unavailable"""
        mock_pmc.return_value.available = False
        self.validator.capture_intel_s0ix()
        self.assertIsNone(self.validator.pmc_core)
        self.assertIsNone(self.validator.s0ix_residency_before)
        self.validator.db.record_s0ix_baseline.assert_not_called()

    @patch("amd_debug.validator.intel.IntelPmcCore")
    def test_capture_intel_s0ix(self, mock_pmc):
        """Test that the S0ix data is captured before the suspend"""
        pmc = mock_pmc.return_value
        pmc.available = True
        pmc.slp_s0_residency = 1000
        pmc.substate_residencies = {"S0i3.0": 240}
        self.validator.capture_intel_s0ix()
        self.assertEqual(self.validator.s0ix_residency_before, 1000)
        self.assertEqual(self.validator.s0ix_substates_before, {"S0i3.0": 240})
        pmc.capture.assert_called_once()
        self.validator.db.record_s0ix_baseline.assert_called_once_with(
            1000, {"S0i3.0": 240}
        )

    @patch("amd_debug.validator.intel.IntelPmcCore")
    def test_capture_intel_s0ix_no_substates(self, mock_pmc):
        """Test that the capture works without substate data"""
        pmc = mock_pmc.return_value
        pmc.available = True
        pmc.slp_s0_residency = None
        pmc.substate_residencies = {}
        self.validator.capture_intel_s0ix()
        self.assertIsNone(self.validator.s0ix_residency_before)
        self.assertEqual(self.validator.s0ix_substates_before, {})

    def test_capture_intel_s0ix_residency_no_before(self):
        """Test that the residency is 0 when nothing was captured before"""
        self.validator.db.get_s0ix_baseline.return_value = None
        result = self.validator.capture_intel_s0ix_residency()
        self.assertEqual(result, 0)
        self.validator.db.record_cycle_data.assert_not_called()

    @patch("amd_debug.validator.intel.IntelPmcCore")
    def test_capture_intel_s0ix_residency_restored_baseline(
        self, mock_pmc
    ):
        """Test that the baseline is restored from the database

        The post-resume capture runs in a separate process when using the
        systemd sleep hook, so the baseline has to be restored from the
        database.
        """
        pmc = mock_pmc.return_value
        pmc.available = True
        pmc.read_slp_s0_residency.return_value = 2500000
        self.validator.pmc_core = None
        self.validator.db.get_s0ix_baseline.return_value = (
            1000000,
            {"S0i3.0": 100},
        )
        result = self.validator.capture_intel_s0ix_residency()
        self.assertEqual(result, 1.5)
        self.assertEqual(self.validator.s0ix_residency, 1.5)
        self.assertEqual(self.validator.s0ix_residency_before, 1000000)
        self.assertEqual(self.validator.s0ix_substates_before, {"S0i3.0": 100})
        self.validator.db.record_cycle_data.assert_called_once_with(
            "Spent 1.50 seconds in S0ix", "💤"
        )

    @patch("amd_debug.validator.intel.IntelPmcCore")
    def test_capture_intel_s0ix_residency_null_baseline(self, mock_pmc):
        """Test that a stored baseline without a counter value is skipped"""
        pmc = mock_pmc.return_value
        pmc.available = True
        pmc.read_slp_s0_residency.return_value = 2500000
        self.validator.pmc_core = None
        self.validator.db.get_s0ix_baseline.return_value = (
            None,
            {"S0i3.0": 100},
        )
        result = self.validator.capture_intel_s0ix_residency()
        self.assertEqual(result, 0)
        self.assertEqual(self.validator.s0ix_residency, 0)
        self.validator.db.record_cycle_data.assert_not_called()

    @patch("amd_debug.validator.intel.IntelPmcCore")
    def test_capture_intel_s0ix_residency_no_pmc(self, mock_pmc):
        """Test that the residency is 0 without a PMC core"""
        mock_pmc.return_value.available = False
        self.validator.pmc_core = None
        result = self.validator.capture_intel_s0ix_residency()
        self.assertEqual(result, 0)
        self.validator.db.record_cycle_data.assert_not_called()

    def test_capture_intel_s0ix_residency(self):
        """Test that the residency delta is calculated"""
        pmc = MagicMock()
        pmc.read_slp_s0_residency.return_value = 2500000
        self.validator.pmc_core = pmc
        self.validator.s0ix_residency_before = 1000000
        result = self.validator.capture_intel_s0ix_residency()
        self.assertEqual(result, 1.5)
        self.assertEqual(self.validator.s0ix_residency, 1.5)
        self.validator.db.record_cycle_data.assert_called_once_with(
            "Spent 1.50 seconds in S0ix", "💤"
        )

    def test_capture_intel_s0ix_residency_unreadable(self):
        """Test that the residency is 0 when the counter can't be read"""
        pmc = MagicMock()
        pmc.read_slp_s0_residency.return_value = None
        self.validator.pmc_core = pmc
        self.validator.s0ix_residency_before = 1000000
        result = self.validator.capture_intel_s0ix_residency()
        self.assertEqual(result, 0)
        self.validator.db.record_cycle_data.assert_not_called()

    def test_capture_intel_s0ix_residency_wrapped(self):
        """Test that a wrapped counter results in 0"""
        pmc = MagicMock()
        pmc.read_slp_s0_residency.return_value = 500
        self.validator.pmc_core = pmc
        self.validator.s0ix_residency_before = 1000000
        result = self.validator.capture_intel_s0ix_residency()
        self.assertEqual(result, 0)
        self.validator.db.record_cycle_data.assert_not_called()

    def test_capture_intel_substate_delta_no_before(self):
        """Test that no delta is captured without a baseline"""
        self.validator.capture_intel_substate_delta()
        self.validator.db.record_debug.assert_not_called()

    @patch("amd_debug.validator.intel.IntelPmcCore")
    def test_capture_intel_substate_delta_no_pmc(self, mock_pmc):
        """Test that no delta is captured without a PMC core"""
        mock_pmc.return_value.available = False
        self.validator.pmc_core = None
        self.validator.s0ix_substates_before = {"S0i3.0": 0}
        self.validator.capture_intel_substate_delta()
        self.validator.db.record_debug.assert_not_called()

    def test_capture_intel_substate_delta(self):
        """Test that the substate residency delta is captured"""
        pmc = MagicMock()
        pmc.read_substate_residencies.return_value = {"S0i2.0": 10, "S0i3.0": 240}
        self.validator.pmc_core = pmc
        self.validator.s0ix_substates_before = {"S0i2.0": 4, "S0i3.0": 100}
        self.validator.capture_intel_substate_delta()
        debug = self.validator.db.record_debug.call_args[0][0]
        self.assertIn("S0i2.0: 6", debug)
        self.assertIn("S0i3.0: 140", debug)

    def test_capture_intel_substate_delta_no_data(self):
        """Test that no delta is captured when there is no data"""
        pmc = MagicMock()
        pmc.read_substate_residencies.return_value = {}
        self.validator.pmc_core = pmc
        self.validator.s0ix_substates_before = {"S0i2.0": 4}
        self.validator.capture_intel_substate_delta()
        self.validator.db.record_debug.assert_not_called()

    @patch("amd_debug.validator.intel.IntelPmcCore")
    def test_capture_intel_s0ix_blockers_no_pmc(self, mock_pmc):
        """Test that no blockers are captured without a PMC core"""
        mock_pmc.return_value.available = False
        self.validator.pmc_core = None
        self.validator.capture_intel_s0ix_blockers()
        self.validator.db.record_debug.assert_not_called()

    def test_capture_intel_s0ix_blockers_no_requirements(self):
        """Test that no blockers are captured without requirements data"""
        pmc = MagicMock()
        pmc.read_substate_requirements.return_value = ""
        self.validator.pmc_core = pmc
        self.validator.capture_intel_s0ix_blockers()
        self.validator.db.record_debug.assert_not_called()

    def test_capture_intel_s0ix_blockers(self):
        """Test that the S0ix blockers are captured"""
        pmc = MagicMock()
        pmc.read_substate_requirements.return_value = (
            "                                     Element |    S0i2.0 | Status\n"
            "pmc0:                       PMC OPI S0i2.0 |  Required |      No\n"
        )
        self.validator.pmc_core = pmc
        self.validator.capture_intel_s0ix_blockers()
        debug = self.validator.db.record_debug.call_args[0][0]
        self.assertIn("PMC OPI S0i2.0", debug)


if __name__ == "__main__":
    unittest.main()

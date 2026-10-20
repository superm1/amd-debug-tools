#!/usr/bin/python3
# SPDX-License-Identifier: MIT

"""
This module contains unit tests for the Intel platform support functions in
the amd-debug-tools package.
"""

import logging
import unittest
from unittest.mock import patch

from amd_debug.intel import (
    get_dmc_firmware_status,
    get_dmc_info_path,
    get_intel_graphics_driver,
    get_lps0_disabled,
    intel_pmc_core_loaded,
    IntelPmcCore,
    parse_substate_requirements,
    parse_substate_residencies,
    S0IX_SUBSTATES,
)

SUBSTATE_RESIDENCIES = """pmc0        Substate     Residency
          S0i2.0              0
          S0i2.1              0
          S0i2.2            120
          S0i3.0            240
"""

SUBSTATE_REQUIREMENTS = """                                     Element |    S0i2.0 |    S0i2.1 | Status | Live Status
pmc0:                       PMC OPI S0i2.0 |  Required |           |      No |          No
pmc0:                PMC OPI S0i2.0 Dis |           |  Required |      No |          No
"""


class TestParseSubstateResidencies(unittest.TestCase):
    """Unit tests for the parse_substate_residencies helper"""

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(filename="/dev/null", level=logging.DEBUG)

    def test_parse_substate_residencies(self):
        """Test that the residency counters are parsed"""
        residencies = parse_substate_residencies(SUBSTATE_RESIDENCIES)
        self.assertEqual(residencies["S0i2.0"], 0)
        self.assertEqual(residencies["S0i2.1"], 0)
        self.assertEqual(residencies["S0i2.2"], 120)
        self.assertEqual(residencies["S0i3.0"], 240)

    def test_parse_substate_residencies_empty(self):
        """Test that an empty file produces no residencies"""
        self.assertEqual(parse_substate_residencies(""), {})

    def test_parse_substate_residencies_ignores_header(self):
        """Test that the header line is ignored"""
        residencies = parse_substate_residencies(SUBSTATE_RESIDENCIES)
        self.assertNotIn("Substate", residencies)
        self.assertNotIn("pmc0", residencies)

    def test_parse_substate_residencies_ignores_unknown_substates(self):
        """Test that unknown substate names are ignored"""
        residencies = parse_substate_residencies("          S0i9.9            100\n")
        self.assertEqual(residencies, {})

    def test_parse_substate_residencies_ignores_invalid_values(self):
        """Test that non-numeric residency values are ignored"""
        residencies = parse_substate_residencies("          S0i2.0           abc\n")
        self.assertEqual(residencies, {})

    def test_parse_substate_residencies_ignores_malformed_lines(self):
        """Test that lines without exactly two fields are ignored"""
        residencies = parse_substate_residencies("S0i2.0\nS0i2.1 1 2\n")
        self.assertEqual(residencies, {})

    def test_all_substates_are_known(self):
        """Test that the list of known substates is complete"""
        self.assertIn("S0i2.0", S0IX_SUBSTATES)
        self.assertIn("S0i3.4", S0IX_SUBSTATES)


class TestParseSubstateRequirements(unittest.TestCase):
    """Unit tests for the parse_substate_requirements helper"""

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(filename="/dev/null", level=logging.DEBUG)

    def test_parse_substate_requirements(self):
        """Test that the blockers are parsed"""
        blockers = parse_substate_requirements(SUBSTATE_REQUIREMENTS)
        self.assertEqual(len(blockers), 2)
        self.assertEqual(blockers[0][0], "PMC OPI S0i2.0")
        self.assertEqual(blockers[0][1], ["Required"])
        self.assertEqual(blockers[1][0], "PMC OPI S0i2.0 Dis")

    def test_parse_substate_requirements_empty(self):
        """Test that an empty file produces no blockers"""
        self.assertEqual(parse_substate_requirements(""), [])

    def test_parse_substate_requirements_ignores_header(self):
        """Test that the header line is ignored"""
        blockers = parse_substate_requirements(SUBSTATE_REQUIREMENTS)
        for element, _required in blockers:
            self.assertNotEqual(element, "Element")

    def test_parse_substate_requirements_ignores_not_required(self):
        """Test that elements that aren't required are ignored"""
        contents = "pmc0:  Some IP |         |         |      No |          No\n"
        self.assertEqual(parse_substate_requirements(contents), [])

    def test_parse_substate_requirements_ignores_lines_without_pipes(self):
        """Test that lines without a pipe are ignored"""
        self.assertEqual(parse_substate_requirements("garbage\n"), [])

    def test_parse_substate_requirements_strips_pmc_prefix(self):
        """Test that the pmcN prefix is stripped from element names"""
        contents = "pmc1:  Some IP |  Required |           |      No |          No\n"
        blockers = parse_substate_requirements(contents)
        self.assertEqual(blockers[0][0], "Some IP")


class TestIntelPmcCore(unittest.TestCase):
    """Unit tests for the IntelPmcCore class"""

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(filename="/dev/null", level=logging.DEBUG)

    @patch("amd_debug.intel.read_file")
    @patch("amd_debug.intel.os.path.exists")
    @patch("amd_debug.intel.os.path.isdir")
    def test_available(self, mock_isdir, mock_exists, mock_read_file):
        """Test that the PMC core is detected as available"""
        mock_isdir.return_value = True
        mock_exists.return_value = True
        mock_read_file.return_value = "1234"
        pmc = IntelPmcCore()
        self.assertTrue(pmc.available)

    @patch("amd_debug.intel.read_file")
    @patch("amd_debug.intel.os.path.exists")
    @patch("amd_debug.intel.os.path.isdir")
    def test_not_available(self, mock_isdir, mock_exists, mock_read_file):
        """Test that the PMC core is detected as unavailable"""
        mock_isdir.return_value = False
        mock_exists.return_value = False
        pmc = IntelPmcCore()
        self.assertFalse(pmc.available)

    @patch("amd_debug.intel.read_file")
    @patch("amd_debug.intel.os.path.exists")
    @patch("amd_debug.intel.os.path.isdir")
    def test_read_slp_s0_residency(self, mock_isdir, mock_exists, mock_read_file):
        """Test that the SLP_S0 residency is read"""
        mock_isdir.return_value = True
        mock_exists.return_value = True
        mock_read_file.return_value = "123456\n"
        pmc = IntelPmcCore()
        self.assertEqual(pmc.read_slp_s0_residency(), 123456)

    @patch("amd_debug.intel.read_file")
    @patch("amd_debug.intel.os.path.exists")
    @patch("amd_debug.intel.os.path.isdir")
    def test_read_slp_s0_residency_missing(
        self, mock_isdir, mock_exists, mock_read_file
    ):
        """Test that a missing SLP_S0 residency returns None"""
        mock_isdir.return_value = True
        mock_exists.return_value = False
        pmc = IntelPmcCore()
        self.assertIsNone(pmc.read_slp_s0_residency())

    @patch("amd_debug.intel.read_file")
    @patch("amd_debug.intel.os.path.exists")
    @patch("amd_debug.intel.os.path.isdir")
    def test_read_slp_s0_residency_invalid(
        self, mock_isdir, mock_exists, mock_read_file
    ):
        """Test that an invalid SLP_S0 residency returns None"""
        mock_isdir.return_value = True
        mock_exists.return_value = True
        mock_read_file.return_value = "not a number"
        pmc = IntelPmcCore()
        self.assertIsNone(pmc.read_slp_s0_residency())

    @patch("amd_debug.intel.read_file")
    @patch("amd_debug.intel.os.path.exists")
    @patch("amd_debug.intel.os.path.isdir")
    def test_read_slp_s0_residency_unreadable(
        self, mock_isdir, mock_exists, mock_read_file
    ):
        """Test that an unreadable SLP_S0 residency returns None"""
        mock_isdir.return_value = True
        mock_exists.return_value = True
        mock_read_file.side_effect = PermissionError
        pmc = IntelPmcCore()
        self.assertIsNone(pmc.read_slp_s0_residency())

    @patch("amd_debug.intel.read_file")
    @patch("amd_debug.intel.os.path.exists")
    @patch("amd_debug.intel.os.path.isdir")
    def test_read_substate_residencies(self, mock_isdir, mock_exists, mock_read_file):
        """Test that the substate residencies are read"""
        mock_isdir.return_value = True
        mock_exists.return_value = True
        mock_read_file.return_value = SUBSTATE_RESIDENCIES
        pmc = IntelPmcCore()
        residencies = pmc.read_substate_residencies()
        self.assertEqual(residencies["S0i2.2"], 120)
        self.assertEqual(residencies["S0i3.0"], 240)

    @patch("amd_debug.intel.read_file")
    @patch("amd_debug.intel.os.path.exists")
    @patch("amd_debug.intel.os.path.isdir")
    def test_read_substate_residencies_missing(
        self, mock_isdir, mock_exists, mock_read_file
    ):
        """Test that missing substate residencies return an empty dict"""
        mock_isdir.return_value = True
        mock_exists.return_value = False
        pmc = IntelPmcCore()
        self.assertEqual(pmc.read_substate_residencies(), {})

    @patch("amd_debug.intel.read_file")
    @patch("amd_debug.intel.os.path.exists")
    @patch("amd_debug.intel.os.path.isdir")
    def test_read_substate_requirements(self, mock_isdir, mock_exists, mock_read_file):
        """Test that the substate requirements are read"""
        mock_isdir.return_value = True
        mock_exists.return_value = True
        mock_read_file.return_value = SUBSTATE_REQUIREMENTS
        pmc = IntelPmcCore()
        self.assertEqual(pmc.read_substate_requirements(), SUBSTATE_REQUIREMENTS)

    @patch("amd_debug.intel.read_file")
    @patch("amd_debug.intel.os.path.exists")
    @patch("amd_debug.intel.os.path.isdir")
    def test_read_substate_requirements_missing(
        self, mock_isdir, mock_exists, mock_read_file
    ):
        """Test that missing substate requirements return an empty string"""
        mock_isdir.return_value = True
        mock_exists.return_value = False
        pmc = IntelPmcCore()
        self.assertEqual(pmc.read_substate_requirements(), "")

    @patch("amd_debug.intel.read_file")
    @patch("amd_debug.intel.os.path.exists")
    @patch("amd_debug.intel.os.path.isdir")
    def test_read_substate_status_registers(
        self, mock_isdir, mock_exists, mock_read_file
    ):
        """Test that the substate status registers are read"""
        mock_isdir.return_value = True
        mock_exists.return_value = True
        mock_read_file.return_value = "STATUS"
        pmc = IntelPmcCore()
        self.assertEqual(pmc.read_substate_status_registers(), "STATUS")

    @patch("amd_debug.intel.read_file")
    @patch("amd_debug.intel.os.path.exists")
    @patch("amd_debug.intel.os.path.isdir")
    def test_read_substate_status_registers_missing(
        self, mock_isdir, mock_exists, mock_read_file
    ):
        """Test that missing status registers return an empty string"""
        mock_isdir.return_value = True
        mock_exists.return_value = False
        pmc = IntelPmcCore()
        self.assertEqual(pmc.read_substate_status_registers(), "")

    @patch("amd_debug.intel.read_file")
    @patch("amd_debug.intel.os.path.exists")
    @patch("amd_debug.intel.os.path.isdir")
    def test_read_substate_live_status_registers(
        self, mock_isdir, mock_exists, mock_read_file
    ):
        """Test that the live status registers are read"""
        mock_isdir.return_value = True
        mock_exists.return_value = True
        mock_read_file.return_value = "LIVE_STATUS"
        pmc = IntelPmcCore()
        self.assertEqual(pmc.read_substate_live_status_registers(), "LIVE_STATUS")

    @patch("amd_debug.intel.read_file")
    @patch("amd_debug.intel.os.path.exists")
    @patch("amd_debug.intel.os.path.isdir")
    def test_read_substate_live_status_registers_missing(
        self, mock_isdir, mock_exists, mock_read_file
    ):
        """Test that missing live status registers return an empty string"""
        mock_isdir.return_value = True
        mock_exists.return_value = False
        pmc = IntelPmcCore()
        self.assertEqual(pmc.read_substate_live_status_registers(), "")

    @patch("amd_debug.intel.read_file")
    @patch("amd_debug.intel.os.path.exists")
    @patch("amd_debug.intel.os.path.isdir")
    def test_capture(self, mock_isdir, mock_exists, mock_read_file):
        """Test that capture gathers all of the data"""
        mock_isdir.return_value = True
        mock_exists.return_value = True
        mock_read_file.return_value = SUBSTATE_RESIDENCIES
        pmc = IntelPmcCore()
        pmc.capture()
        self.assertEqual(pmc.substate_residencies["S0i2.2"], 120)
        self.assertEqual(pmc.substate_requirements, SUBSTATE_RESIDENCIES)
        self.assertEqual(pmc.substate_status_registers, SUBSTATE_RESIDENCIES)
        self.assertEqual(pmc.substate_live_status_registers, SUBSTATE_RESIDENCIES)


class TestIntelGraphics(unittest.TestCase):
    """Unit tests for the Intel graphics helpers"""

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(filename="/dev/null", level=logging.DEBUG)

    @patch("amd_debug.intel.os.path.exists")
    def test_get_intel_graphics_driver_i915(self, mock_exists):
        """Test that the i915 driver is detected"""
        mock_exists.side_effect = lambda p: p.endswith("/i915")
        self.assertEqual(get_intel_graphics_driver(), "i915")

    @patch("amd_debug.intel.os.path.exists")
    def test_get_intel_graphics_driver_xe(self, mock_exists):
        """Test that the xe driver is detected"""
        mock_exists.side_effect = lambda p: p.endswith("/xe")
        self.assertEqual(get_intel_graphics_driver(), "xe")

    @patch("amd_debug.intel.os.path.exists")
    def test_get_intel_graphics_driver_none(self, mock_exists):
        """Test that no Intel graphics driver is detected"""
        mock_exists.return_value = False
        self.assertEqual(get_intel_graphics_driver(), "")

    @patch("amd_debug.intel.read_file")
    @patch("amd_debug.intel.os.path.exists")
    @patch("amd_debug.intel.os.path.isdir")
    @patch("amd_debug.intel.os.listdir")
    def test_get_dmc_info_path(
        self, mock_listdir, mock_isdir, mock_exists, mock_read_file
    ):
        """Test that the DMC info path is found"""
        mock_isdir.return_value = True
        mock_listdir.return_value = ["0", "1"]
        mock_exists.side_effect = lambda p: p.endswith("dri/0/i915_dmc_info")
        self.assertEqual(get_dmc_info_path(), "/sys/kernel/debug/dri/0/i915_dmc_info")

    @patch("amd_debug.intel.read_file")
    @patch("amd_debug.intel.os.path.exists")
    @patch("amd_debug.intel.os.path.isdir")
    @patch("amd_debug.intel.os.listdir")
    def test_get_dmc_info_path_missing(
        self, mock_listdir, mock_isdir, mock_exists, mock_read_file
    ):
        """Test that a missing DMC info path returns an empty string"""
        mock_isdir.return_value = True
        mock_listdir.return_value = ["0"]
        mock_exists.return_value = False
        self.assertEqual(get_dmc_info_path(), "")

    @patch("amd_debug.intel.read_file")
    @patch("amd_debug.intel.os.path.exists")
    @patch("amd_debug.intel.os.path.isdir")
    @patch("amd_debug.intel.os.listdir")
    def test_get_dmc_info_path_no_dri(
        self, mock_listdir, mock_isdir, mock_exists, mock_read_file
    ):
        """Test that a missing dri directory returns an empty string"""
        mock_isdir.return_value = False
        self.assertEqual(get_dmc_info_path(), "")

    @patch("amd_debug.intel.read_file")
    @patch("amd_debug.intel.os.path.exists")
    @patch("amd_debug.intel.os.path.isdir")
    @patch("amd_debug.intel.os.listdir")
    def test_get_dmc_firmware_status(
        self, mock_listdir, mock_isdir, mock_exists, mock_read_file
    ):
        """Test that the DMC firmware status is parsed"""
        mock_isdir.return_value = True
        mock_listdir.return_value = ["0"]
        mock_exists.side_effect = lambda p: p.endswith("i915_dmc_info")
        mock_read_file.return_value = (
            "DMC state:                 0000\n"
            "DMC firmware:              4.11\n"
            "fw loaded:                 yes\n"
        )
        status = get_dmc_firmware_status()
        self.assertEqual(status["fw loaded"], "yes")
        self.assertEqual(status["DMC firmware"], "4.11")

    @patch("amd_debug.intel.read_file")
    @patch("amd_debug.intel.os.path.exists")
    @patch("amd_debug.intel.os.path.isdir")
    @patch("amd_debug.intel.os.listdir")
    def test_get_dmc_firmware_status_no_file(
        self, mock_listdir, mock_isdir, mock_exists, mock_read_file
    ):
        """Test that no DMC firmware status is returned when there's no file"""
        mock_isdir.return_value = True
        mock_listdir.return_value = ["0"]
        mock_exists.return_value = False
        self.assertEqual(get_dmc_firmware_status(), {})

    @patch("amd_debug.intel.read_file")
    @patch("amd_debug.intel.os.path.exists")
    @patch("amd_debug.intel.os.path.isdir")
    @patch("amd_debug.intel.os.listdir")
    def test_get_dmc_firmware_status_unreadable(
        self, mock_listdir, mock_isdir, mock_exists, mock_read_file
    ):
        """Test that an unreadable DMC file returns no status"""
        mock_isdir.return_value = True
        mock_listdir.return_value = ["0"]
        mock_exists.side_effect = lambda p: p.endswith("i915_dmc_info")
        mock_read_file.side_effect = PermissionError
        self.assertEqual(get_dmc_firmware_status(), {})


class TestLps0(unittest.TestCase):
    """Unit tests for the LPS0 helpers"""

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(filename="/dev/null", level=logging.DEBUG)

    @patch("amd_debug.intel.read_file")
    @patch("amd_debug.intel.os.path.exists")
    def test_get_lps0_disabled(self, mock_exists, mock_read_file):
        """Test that a disabled LPS0 interface is detected"""
        mock_exists.return_value = True
        mock_read_file.return_value = "Y"
        self.assertTrue(get_lps0_disabled())

    @patch("amd_debug.intel.read_file")
    @patch("amd_debug.intel.os.path.exists")
    def test_get_lps0_enabled(self, mock_exists, mock_read_file):
        """Test that an enabled LPS0 interface is detected"""
        mock_exists.return_value = True
        mock_read_file.return_value = "N"
        self.assertFalse(get_lps0_disabled())

    @patch("amd_debug.intel.read_file")
    @patch("amd_debug.intel.os.path.exists")
    def test_get_lps0_missing(self, mock_exists, mock_read_file):
        """Test that a missing parameter is not reported as either state"""
        mock_exists.return_value = False
        self.assertIsNone(get_lps0_disabled())
        mock_read_file.assert_not_called()

    @patch("amd_debug.intel.read_file")
    @patch("amd_debug.intel.os.path.exists")
    def test_get_lps0_unreadable(self, mock_exists, mock_read_file):
        """Test that an unreadable parameter is not reported as either state"""
        mock_exists.return_value = True
        mock_read_file.side_effect = PermissionError
        self.assertIsNone(get_lps0_disabled())

    @patch("amd_debug.intel.os.path.exists")
    def test_intel_pmc_core_loaded(self, mock_exists):
        """Test that the intel_pmc_core driver is detected"""
        mock_exists.side_effect = lambda p: p.endswith("/intel_pmc_core")
        self.assertTrue(intel_pmc_core_loaded())

    @patch("amd_debug.intel.os.path.exists")
    def test_intel_pmc_core_not_loaded(self, mock_exists):
        """Test that a missing intel_pmc_core driver is detected"""
        mock_exists.return_value = False
        self.assertFalse(intel_pmc_core_loaded())


if __name__ == "__main__":
    unittest.main()

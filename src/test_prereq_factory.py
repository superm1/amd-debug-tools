#!/usr/bin/python3
# SPDX-License-Identifier: MIT

"""
This module contains unit tests for the prerequisite validator factory in
the amd-debug-tools package.
"""

import logging
import unittest
from unittest.mock import patch

from amd_debug.prereq import get_validator, get_validator_class
from amd_debug.prereq.amd import AmdPrerequisiteValidator
from amd_debug.prereq.base import PrerequisiteValidator
from amd_debug.prereq.intel import IntelPrerequisiteValidator
from amd_debug.cpu import VENDOR_AMD, VENDOR_INTEL


class TestGetValidatorClass(unittest.TestCase):
    """Unit tests for the get_validator_class helper"""

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(filename="/dev/null", level=logging.DEBUG)

    def test_get_validator_class_intel(self):
        """Test that Intel gets the Intel validator"""
        self.assertEqual(get_validator_class(VENDOR_INTEL), IntelPrerequisiteValidator)

    def test_get_validator_class_amd(self):
        """Test that AMD gets the AMD validator"""
        self.assertEqual(get_validator_class(VENDOR_AMD), AmdPrerequisiteValidator)

    def test_get_validator_class_unknown(self):
        """Test that an unknown vendor gets the base validator"""
        self.assertEqual(get_validator_class("SomeVendor"), PrerequisiteValidator)

    def test_get_validator_class_empty(self):
        """Test that an empty vendor gets the base validator"""
        self.assertEqual(get_validator_class(""), PrerequisiteValidator)

    def test_intel_validator_is_a_base_validator(self):
        """Test that the Intel validator extends the base validator"""
        self.assertTrue(issubclass(IntelPrerequisiteValidator, PrerequisiteValidator))

    def test_amd_validator_is_a_base_validator(self):
        """Test that the AMD validator extends the base validator"""
        self.assertTrue(issubclass(AmdPrerequisiteValidator, PrerequisiteValidator))

    def test_intel_vendor_checks_are_not_overridden(self):
        """Test that the NVIDIA mixin doesn't shadow the Intel vendor checks"""
        self.assertEqual(
            IntelPrerequisiteValidator.vendor_checks.__qualname__,
            "IntelPrerequisiteValidator.vendor_checks",
        )

    def test_amd_vendor_checks_are_not_overridden(self):
        """Test that the NVIDIA mixin doesn't shadow the AMD vendor checks"""
        self.assertEqual(
            AmdPrerequisiteValidator.vendor_checks.__qualname__,
            "AmdPrerequisiteValidator.vendor_checks",
        )

    def test_intel_vendor_info_is_not_overridden(self):
        """Test that the NVIDIA mixin doesn't shadow the Intel vendor info"""
        self.assertEqual(
            IntelPrerequisiteValidator.vendor_info.__qualname__,
            "IntelPrerequisiteValidator.vendor_info",
        )

    def test_amd_vendor_info_is_not_overridden(self):
        """Test that the NVIDIA mixin doesn't shadow the AMD vendor info"""
        self.assertEqual(
            AmdPrerequisiteValidator.vendor_info.__qualname__,
            "AmdPrerequisiteValidator.vendor_info",
        )


class TestGetValidator(unittest.TestCase):
    """Unit tests for the get_validator helper"""

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(filename="/dev/null", level=logging.DEBUG)

    @patch("amd_debug.prereq.base.SleepDatabase")
    @patch("amd_debug.prereq.base.is_root", return_value=True)
    @patch("amd_debug.prereq.base.get_kernel_log")
    @patch("amd_debug.prereq.get_cpu_info")
    def test_get_validator_intel(self, mock_cpu_info, _mock_log, _mock_root, _mock_db):
        """Test that an Intel system gets the Intel validator"""
        mock_cpu_info.return_value.vendor = VENDOR_INTEL
        validator = get_validator(tool_debug=False)
        self.assertIsInstance(validator, IntelPrerequisiteValidator)

    @patch("amd_debug.prereq.base.SleepDatabase")
    @patch("amd_debug.prereq.base.is_root", return_value=True)
    @patch("amd_debug.prereq.base.get_kernel_log")
    @patch("amd_debug.prereq.get_cpu_info")
    def test_get_validator_amd(self, mock_cpu_info, _mock_log, _mock_root, _mock_db):
        """Test that an AMD system gets the AMD validator"""
        mock_cpu_info.return_value.vendor = VENDOR_AMD
        validator = get_validator(tool_debug=False)
        self.assertIsInstance(validator, AmdPrerequisiteValidator)

    @patch("amd_debug.prereq.base.SleepDatabase")
    @patch("amd_debug.prereq.base.is_root", return_value=True)
    @patch("amd_debug.prereq.base.get_kernel_log")
    @patch("amd_debug.prereq.get_cpu_info")
    def test_get_validator_unknown(
        self, mock_cpu_info, _mock_log, _mock_root, _mock_db
    ):
        """Test that an unknown vendor gets the base validator"""
        mock_cpu_info.return_value.vendor = "SomeVendor"
        validator = get_validator(tool_debug=False)
        self.assertEqual(type(validator), PrerequisiteValidator)


if __name__ == "__main__":
    unittest.main()

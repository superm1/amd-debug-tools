#!/usr/bin/python3
# SPDX-License-Identifier: MIT

"""
This module contains unit tests for the acpi functions in the amd-debug-tools package.
"""
from unittest.mock import patch, mock_open, call

import logging
import unittest
import sys
import os

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from amd_debug.acpi import search_acpi_tables, AcpicaTracer, ACPI_METHOD


class TestAcpi(unittest.TestCase):
    """Test acpi functions"""

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(filename="/dev/null", level=logging.DEBUG)

    def test_search_acpi_tables(self):
        """Test search_acpi_tables function"""
        pattern = "test_pattern"
        bad_pattern = "bad_pattern"
        mock_listdir = ["ABA", "SSDT1", "DSDT2", "SSDT3"]
        mock_file_content = b"test_pattern"

        with patch("os.listdir", return_value=mock_listdir), patch(
            "builtins.open", mock_open(read_data=mock_file_content)
        ):
            result = search_acpi_tables(pattern)
            self.assertTrue(result)

        with patch("os.listdir", return_value=mock_listdir), patch(
            "builtins.open", mock_open(read_data=mock_file_content)
        ):
            result = search_acpi_tables(bad_pattern)
            self.assertFalse(result)

        with patch("os.listdir", return_value=["OTHER1", "OTHER2"]), patch(
            "builtins.open", mock_open(read_data=b"no_match")
        ):
            result = search_acpi_tables(pattern)
            self.assertFalse(result)

    def test_acpica_tracer_missing_bios(self):
        """Test AcpicaTracer class when ACPI tracing is not supported"""

        mock_listdir = ["SSDT1", "DSDT2", "SSDT3"]

        with patch("os.listdir", return_value=mock_listdir), patch(
            "builtins.open", mock_open(read_data=b"foo")
        ), patch("os.path.exists", return_value=True):

            tracer = AcpicaTracer()
            self.assertTrue(tracer.supported)

            self.assertFalse(tracer.trace_bios())

    def test_acpica_tracer(self):
        """Test AcpicaTracer class"""

        mock_listdir = ["SSDT1", "DSDT2", "SSDT3"]
        mock_file_content = bytes(ACPI_METHOD, "utf-8")

        with patch("os.listdir", return_value=mock_listdir), patch(
            "builtins.open", mock_open(read_data=mock_file_content)
        ), patch("os.path.exists", return_value=True):

            tracer = AcpicaTracer()
            self.assertTrue(tracer.supported)

            self.assertTrue(tracer.trace_notify())
            self.assertTrue(tracer.trace_bios())
            self.assertTrue(tracer.disable())
            self.assertTrue(tracer.restore())

    def test_acpica_trace_no_acpi_debug(self):
        """Test AcpicaTracer class when ACPI tracing is not supported"""
        with patch("os.path.exists", return_value=False), patch(
            "builtins.open", mock_open(read_data="foo")
        ):
            tracer = AcpicaTracer()
            self.assertFalse(tracer.supported)

            self.assertFalse(tracer.trace_notify())
            self.assertFalse(tracer.trace_bios())
            self.assertFalse(tracer.disable())
            self.assertFalse(tracer.restore())

#!/usr/bin/python3
# SPDX-License-Identifier: MIT

import os
import logging
from amd_debug.common import BIT, read_file

ACPI_METHOD = "M460"


def search_acpi_tables(pattern):
    """Search for a pattern in ACPI tables"""
    p = os.path.join("/", "sys", "firmware", "acpi", "tables")

    for fn in os.listdir(p):
        if not fn.startswith("SSDT") and not fn.startswith("DSDT"):
            continue
        fp = os.path.join(p, fn)
        with open(fp, "rb") as file:
            content = file.read()
            if pattern.encode() in content:
                return True
    return False


class AcpicaTracer:
    """Class for ACPI tracing"""

    def __init__(self):
        self.acpi_base = os.path.join("/", "sys", "module", "acpi", "parameters")
        keys = [
            "trace_debug_layer",
            "trace_debug_level",
            "trace_method_name",
            "trace_state",
        ]
        self.original = {}
        self.supported = False
        for key in keys:
            fname = os.path.join(self.acpi_base, key)
            if not os.path.exists(fname):
                logging.debug("ACPI Notify() debugging not available")
                return
            v = read_file(fname)
            if v and v != "(null)":
                self.original[key] = v
        self.supported = True

    def _write_expected(self, expected):
        for key, value in expected.items():
            p = os.path.join(self.acpi_base, key)
            if isinstance(value, int):
                t = str(int(value))
            else:
                t = value
            with open(p, "w", encoding="utf-8") as w:
                w.write(t)

    def trace_notify(self):
        """Trace notify events"""
        if not self.supported:
            return False
        expected = {
            "trace_debug_layer": BIT(2),
            "trace_debug_level": BIT(2),
            "trace_state": "enable",
        }
        self._write_expected(expected)
        logging.debug("Enabled ACPI debugging for ACPI_LV_INFO/ACPI_EVENTS")
        return True

    def trace_bios(self):
        """Trace BIOS events"""
        if not self.supported:
            return False
        if not search_acpi_tables(ACPI_METHOD):
            logging.debug(
                "will not work on this system: ACPI tables do not contain %s",
                ACPI_METHOD,
            )
            return False
        expected = {
            "trace_debug_layer": BIT(7),
            "trace_debug_level": BIT(4),
            "trace_method_name": f"\\{ACPI_METHOD}",
            "trace_state": "method",
        }
        self._write_expected(expected)
        logging.debug("Enabled ACPI debugging for BIOS")
        return True

    def disable(self):
        """Disable ACPI tracing"""
        if not self.supported:
            return False
        expected = {
            "trace_state": "disable",
        }
        self._write_expected(expected)
        return True

    def restore(self):
        """Restore original ACPI tracing settings"""
        if not self.supported:
            return False
        self._write_expected(self.original)
        return True

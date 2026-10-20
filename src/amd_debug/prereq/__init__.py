# SPDX-License-Identifier: MIT

"""
This module contains the s2idle prerequisite validator.

The checks that are meaningful for s2idle differ between CPU vendors, so
the validator is split into a vendor independent base class and vendor
specific subclasses.
"""

from amd_debug.prereq.amd import AmdPrerequisiteValidator


def get_validator(tool_debug: bool):
    """Get a prerequisite validator suitable for the running system"""
    return AmdPrerequisiteValidator(tool_debug)


__all__ = [
    "get_validator",
]

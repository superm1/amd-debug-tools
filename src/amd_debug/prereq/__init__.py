# SPDX-License-Identifier: MIT

"""
This module contains the s2idle prerequisite validator.

The checks that are meaningful for s2idle differ between CPU vendors, so
the validator is split into a vendor independent base class and vendor
specific subclasses.  The :func:`get_validator` helper returns the
appropriate validator for the running system.
"""

from amd_debug.cpu import get_cpu_info, VENDOR_AMD, VENDOR_INTEL


def get_validator_class(vendor: str):
    """Get the prerequisite validator class for a given CPU vendor

    An unknown vendor falls back to the AMD validator, which only applies
    the checks that are valid for all platforms.
    """
    if vendor == VENDOR_INTEL:
        from amd_debug.prereq.intel import (  # pylint: disable=import-outside-toplevel
            IntelPrerequisiteValidator,
        )

        return IntelPrerequisiteValidator
    if vendor == VENDOR_AMD:
        from amd_debug.prereq.amd import (  # pylint: disable=import-outside-toplevel
            AmdPrerequisiteValidator,
        )

        return AmdPrerequisiteValidator
    from amd_debug.prereq.base import (  # pylint: disable=import-outside-toplevel
        PrerequisiteValidator,
    )

    return PrerequisiteValidator


def get_validator(tool_debug: bool):
    """Get a prerequisite validator suitable for the running system"""
    vendor = get_cpu_info().vendor
    return get_validator_class(vendor)(tool_debug)


__all__ = [
    "get_validator",
    "get_validator_class",
]

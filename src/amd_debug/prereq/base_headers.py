# SPDX-License-Identifier: MIT

"""
This module contains the header strings used by the s2idle prerequisite
validator.

These are kept in their own module so that the various check mixins can
share them without creating circular imports.
"""


class Headers:
    """Headers for the script"""

    NvmeSimpleSuspend = "platform quirk: setting simple suspend"
    RootError = "Must be executed by root user"
    BrokenPrerequisites = "Your system does not meet s2idle prerequisites!"
    ExplanationReport = "Explanations for your system"

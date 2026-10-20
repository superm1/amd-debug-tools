# SPDX-License-Identifier: MIT

"""
This module contains the header strings used by the sleep validator.

These are kept in their own module so that the various helper mixins can
share them without creating circular imports.
"""


class Headers:
    """Header strings for the debug output"""

    Irq1Workaround = "Disabling IRQ1 wakeup source to avoid platform firmware bug"
    WokeFromIrq = "Woke up from IRQ"
    LastCycleResults = "Results from last s2idle cycle"
    CycleCount = "Suspend cycle"
    SuspendDuration = "Suspend timer programmed for"

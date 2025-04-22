#!/usr/bin/python3
# SPDX-License-Identifier: MIT

"""
This module contains unit tests for the failure functions in the amd-debug-tools package.
"""

from unittest.mock import patch, call

import logging
import unittest
import sys
import os

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import amd_debug.failures


class TestFailures(unittest.TestCase):
    """Test failure functions"""

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(filename="/dev/null", level=logging.DEBUG)

    @patch("builtins.print")
    def test_failures(self, mocked_print):
        """Test failure functions"""

        cls = amd_debug.failures.RtcAlarmWrong()
        self.assertEqual(
            cls.get_description(), "rtc_cmos is not configured to use ACPI alarm"
        )
        self.assertEqual(
            str(cls),
            "Some problems can occur during wakeup cycles if the HPET RTC "
            "emulation is used to wake systems. This can manifest in unexpected "
            "wakeups or high power consumption.For more information on this failure "
            "see:https://github.com/systemd/systemd/issues/24279",
        )
        cls = amd_debug.failures.MissingAmdgpu()
        self.assertEqual(cls.get_description(), "AMDGPU driver is missing")
        cls = amd_debug.failures.MissingAmdgpuFirmware(["foo", "bar"])
        self.assertEqual(cls.get_description(), "AMDGPU firmware is missing")
        cls = amd_debug.failures.AmdgpuPpFeatureMask()
        self.assertEqual(cls.get_description(), "AMDGPU ppfeaturemask changed")
        cls = amd_debug.failures.MissingAmdPmc()
        self.assertEqual(cls.get_description(), "AMD-PMC driver is missing")
        cls = amd_debug.failures.MissingThunderbolt()
        self.assertEqual(cls.get_description(), "thunderbolt driver is missing")
        cls = amd_debug.failures.MissingXhciHcd()
        self.assertEqual(cls.get_description(), "xhci_hcd driver is missing")
        cls = amd_debug.failures.MissingDriver("4")
        self.assertEqual(cls.get_description(), "4 driver is missing")
        cls = amd_debug.failures.AcpiBiosError("5")
        self.assertEqual(cls.get_description(), "ACPI BIOS Errors detected")
        cls = amd_debug.failures.UnsupportedModel()
        self.assertEqual(cls.get_description(), "Unsupported CPU model")
        cls = amd_debug.failures.UserNvmeConfiguration()
        self.assertEqual(cls.get_description(), "NVME ACPI support is disabled")
        cls = amd_debug.failures.AcpiNvmeStorageD3Enable("foo", 2)
        self.assertEqual(cls.get_description(), "foo missing ACPI attributes")
        cls = amd_debug.failures.DevSlpHostIssue()
        self.assertEqual(
            cls.get_description(), "AHCI controller doesn't support DevSlp"
        )
        cls = amd_debug.failures.DevSlpDiskIssue()
        self.assertEqual(cls.get_description(), "SATA disk doesn't support DevSlp")
        cls = amd_debug.failures.SleepModeWrong()
        self.assertEqual(
            cls.get_description(),
            "The system hasn't been configured for Modern Standby in BIOS setup",
        )
        cls = amd_debug.failures.DeepSleep()
        self.assertEqual(
            cls.get_description(),
            "The kernel command line is asserting the system to use deep sleep",
        )
        cls = amd_debug.failures.FadtWrong()
        self.assertEqual(
            cls.get_description(),
            "The kernel didn't emit a message that low power idle was supported",
        )
        cls = amd_debug.failures.Irq1Workaround()
        self.assertEqual(
            cls.get_description(),
            "The wakeup showed an IRQ1 wakeup source, which might be a platform firmware bug",
        )
        cls = amd_debug.failures.KernelRingBufferWrapped()
        self.assertEqual(cls.get_description(), "Kernel ringbuffer has wrapped")
        cls = amd_debug.failures.AmdHsmpBug()
        self.assertEqual(cls.get_description(), "amd-hsmp built in to kernel")
        cls = amd_debug.failures.WCN6855Bug()
        self.assertEqual(
            cls.get_description(),
            "The firmware loaded for the WCN6855 causes spurious wakeups",
        )
        cls = amd_debug.failures.I2CHidBug("touchpad", "block")
        self.assertEqual(
            cls.get_description(),
            "The touchpad device has been reported to cause high power consumption and spurious wakeups",
        )
        cls = amd_debug.failures.SpuriousWakeup(1, 0)
        self.assertEqual(
            cls.get_description(), "Userspace wasn't asleep at least 0:00:01"
        )
        cls = amd_debug.failures.LowHardwareSleepResidency(5, 30)
        self.assertEqual(
            cls.get_description(), "System had low hardware sleep residency"
        )
        cls = amd_debug.failures.MSRFailure()
        self.assertEqual(cls.get_description(), "PC6 or CC6 state disabled")
        cls = amd_debug.failures.TaintedKernel()
        self.assertEqual(cls.get_description(), "Kernel is tainted")
        cls = amd_debug.failures.DMArNotEnabled()
        self.assertEqual(cls.get_description(), "Pre-boot DMA protection disabled")
        cls = amd_debug.failures.MissingIommuACPI("foo")
        self.assertEqual(cls.get_description(), "Device foo missing from ACPI tables")
        cls = amd_debug.failures.MissingIommuPolicy("foo")
        self.assertEqual(
            cls.get_description(), "Device foo does not have IOMMU policy applied"
        )
        cls = amd_debug.failures.IommuPageFault("foo")
        self.assertEqual(cls.get_description(), "Page fault reported for foo")
        cls = amd_debug.failures.SMTNotEnabled()
        self.assertEqual(cls.get_description(), "SMT is not enabled")
        cls = amd_debug.failures.ASpmWrong()
        self.assertEqual(cls.get_description(), "ASPM is overridden")
        cls = amd_debug.failures.UnservicedGpio()
        self.assertEqual(cls.get_description(), "GPIO interrupt is not serviced")
        cls = amd_debug.failures.DmiNotSetup()
        self.assertEqual(cls.get_description(), "DMI data was not scanned")
        cls = amd_debug.failures.LimitedCores(10, 7)
        self.assertEqual(cls.get_description(), "CPU cores have been limited")
        cls = amd_debug.failures.RogAllyOldMcu(1, 2)
        self.assertEqual(cls.get_description(), "Rog Ally MCU firmware is too old")
        os.environ["TERM"] = "dumb"
        cls = amd_debug.failures.RogAllyMcuPowerSave()
        self.assertEqual(cls.get_description(), "Rog Ally MCU power save is disabled")
        failure = "The MCU powersave feature is disabled which will cause problems with the controller after suspend/resume."
        self.assertEqual(str(cls), failure)
        cls.get_failure()
        mocked_print.assert_has_calls(
            [
                call("🚦 Rog Ally MCU power save is disabled"),
                call(failure),
            ]
        )

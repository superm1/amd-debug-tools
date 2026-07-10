#!/usr/bin/python3
# SPDX-License-Identifier: MIT

"""
This module contains unit tests for the validator functions in the amd-debug-tools package.
"""

from unittest.mock import patch, mock_open, Mock, MagicMock

import os
import logging
import subprocess
import unittest
import math
from datetime import datetime, timedelta

from amd_debug.validator import (
    pm_debugging,
    soc_needs_irq1_wa,
    SleepValidator,
    toggle_pm_debug,
)


class TestValidatorHelpers(unittest.TestCase):
    """Test validator Helper functions"""

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(filename="/dev/null", level=logging.DEBUG)

    def test_soc_needs_irq1_wa(self):
        """Test if the SOC should apply an IRQ1 workaround"""
        ret = soc_needs_irq1_wa(0x17, 0x68, "1.2.3")
        self.assertTrue(ret)
        ret = soc_needs_irq1_wa(0x17, 0x69, "1.2.3")
        self.assertFalse(ret)
        ret = soc_needs_irq1_wa(0x19, 0x51, "64.65.0")
        self.assertFalse(ret)
        ret = soc_needs_irq1_wa(0x19, 0x50, "64.65.0")
        self.assertTrue(ret)
        ret = soc_needs_irq1_wa(0x19, 0x50, "64.66.0")
        self.assertFalse(ret)

    def test_pm_debugging(self):
        """Test pm_debugging decorator"""

        @pm_debugging
        def test_function():
            return "Test function executed"

        # Mock /sys/power/pm_debug_messages existing and all ACPI existing
        with patch("amd_debug.validator.open", new_callable=mock_open, read_data="0") as mock_file:
            handlers = (
                mock_file.return_value,
                mock_open(read_data="0").return_value,
                mock_open(read_data="0").return_value,
                mock_open(read_data="0").return_value,
            )
            mock_open.side_effect = handlers
            result = test_function()
            self.assertEqual(result, "Test function executed")

        # Mock /sys/power/pm_debug_messages missing
        with patch(
            "amd_debug.validator.open", side_effect=FileNotFoundError("not found")
        ) as mock_file:
            with self.assertRaises(FileNotFoundError):
                result = test_function()


class TestValidator(unittest.TestCase):
    """Test validator functions"""

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(filename="/dev/null", level=logging.DEBUG)

    @patch("amd_debug.validator.SleepDatabase")
    @patch("subprocess.run")
    def setUp(self, _db_mock, _mock_run):
        """Set up a mock context for testing"""
        self.validator = SleepValidator(tool_debug=True, bios_debug=False)

    def test_capture_running_compositors(self):
        """Test capture_running_compositors method"""
        with patch("glob.glob", return_value=["/proc/1234", "/proc/5678"]), patch(
            "os.path.exists", return_value=True
        ), patch(
            "os.readlink", side_effect=["/usr/bin/kwin_wayland", "/usr/bin/gnome-shell"]
        ), patch.object(
            self.validator.db, "record_debug"
        ) as mock_record_debug:
            self.validator.capture_running_compositors()
            mock_record_debug.assert_any_call("kwin_wayland compositor is running")
            mock_record_debug.assert_any_call("gnome-shell compositor is running")

    def test_capture_power_profile(self):
        """Test capture_power_profile method"""
        with patch("os.path.exists", return_value=True), patch(
            "subprocess.check_output",
            return_value=b"Performance\nBalanced\nPower Saver",
        ), patch.object(self.validator.db, "record_debug") as mock_record_debug:
            self.validator.capture_power_profile()
            mock_record_debug.assert_any_call("Power Profiles:")
            mock_record_debug.assert_any_call("│ Performance")
            mock_record_debug.assert_any_call("│ Balanced")
            mock_record_debug.assert_any_call("└─Power Saver")

    def test_capture_battery(self):
        """Test capture_battery method"""
        with patch.object(
            self.validator.batteries, "get_batteries", return_value=["BAT0"]
        ), patch.object(
            self.validator.batteries, "get_energy", return_value=50000
        ), patch.object(
            self.validator.batteries, "get_energy_full", return_value=60000
        ), patch.object(
            self.validator.db, "record_debug"
        ) as mock_record_debug, patch.object(
            self.validator.db, "record_battery_energy"
        ) as mock_record_battery_energy:
            self.validator.capture_battery()
            mock_record_debug.assert_called_with("BAT0 energy level is 50000 µWh")
            mock_record_battery_energy.assert_called_with("BAT0", 50000, 60000, "W")

    def test_check_rtc_cmos(self):
        """Test check_rtc_cmos method"""
        with patch(
            "os.path.join",
            return_value="/sys/module/rtc_cmos/parameters/use_acpi_alarm",
        ), patch("builtins.open", mock_open(read_data="N")), patch.object(
            self.validator.db, "record_cycle_data"
        ) as mock_record_cycle_data:
            self.validator.check_rtc_cmos()
            mock_record_cycle_data.assert_called_with(
                "`rtc_cmos` not configured to use ACPI alarm", "🚦"
            )

    def test_capture_wake_sources(self):
        """Test capture_wake_sources method"""
        mock_pyudev = patch.object(self.validator, "pyudev").start()
        mock_record_debug = patch.object(self.validator.db, "record_debug").start()
        mock_read_file = patch("amd_debug.validator.read_file").start()
        mock_os_path_exists = patch("os.path.exists").start()

        # Mock wakeup devices
        mock_wakeup_device = mock_pyudev.list_devices.return_value = [
            unittest.mock.Mock(
                sys_path="/sys/devices/pci0000:00/0000:00:14.0",
                find_parent=lambda subsystem, **kwargs: None,
            )
        ]

        # Mock wakeup file existence and content
        mock_os_path_exists.return_value = True
        mock_read_file.return_value = "enabled"

        # Mock device properties
        mock_wakeup_device[0].properties = {"PCI_CLASS": "0x0c0330"}
        mock_wakeup_device[0].sys_path = "/sys/devices/pci0000:00/0000:00:14.0"

        self.validator.capture_wake_sources()

        # Validate debug messages
        mock_record_debug.assert_any_call(
            "Wakeup Source|Linux Device|Status\n|/sys/devices/pci0000:00/0000:00:14.0|enabled\n"
        )

        # Stop patches
        patch.stopall()

    def test_capture_lid(self):
        """Test capture_lid method"""
        with patch("os.walk", return_value=[("/", [], ["lid0", "lid1"])]), patch(
            "os.path.join", side_effect=lambda *args: "/".join(args)
        ), patch(
            "amd_debug.validator.read_file",
            side_effect=["state: open", "state: closed"],
        ), patch.object(
            self.validator.db, "record_debug"
        ) as mock_record_debug:
            self.validator.capture_lid()
            mock_record_debug.assert_any_call("ACPI Lid (//lid0): open")
            mock_record_debug.assert_any_call("ACPI Lid (//lid1): closed")

    def test_capture_wakeup_irq_data(self):
        """Test capture_wakeup_irq_data method"""
        with patch("os.path.join", side_effect=lambda *args: "/".join(args)), patch(
            "amd_debug.validator.read_file",
            side_effect=[
                "123",  # IRQ number
                "chip_name_mock",  # Chip name
                "irq_name_mock",  # IRQ name
                "hw_mock",  # Hardware IRQ
                "actions_mock",  # Actions
            ],
        ), patch.object(self.validator.db, "record_debug") as mock_record_debug:
            result = self.validator.capture_wakeup_irq_data()
            self.assertTrue(result)
            mock_record_debug.assert_called_once_with(
                "Woke up from IRQ 123 (chip_name_mock hw_mock-irq_name_mock actions_mock)"
            )

    def test_capture_thermal(self):
        """Test capture_thermal method"""
        # Mock pyudev devices
        mock_pyudev = patch.object(self.validator, "pyudev").start()
        mock_record_debug = patch.object(self.validator.db, "record_debug").start()
        mock_record_prereq = patch.object(self.validator.db, "record_prereq").start()
        mock_read_file = patch("amd_debug.validator.read_file").start()
        mock_os_listdir = patch("os.listdir").start()

        # Mock thermal devices
        mock_device = unittest.mock.Mock()
        mock_device.device_path = "/devices/LNXTHERM:00"
        mock_device.sys_path = "/sys/devices/LNXTHERM:00"
        mock_pyudev.list_devices.return_value = [mock_device]

        # Mock thermal zone files
        mock_read_file.side_effect = [
            "45000",  # Current temperature in millidegrees
            "critical",  # Trip point 0 type
            "50000",  # Trip point 0 temperature in millidegrees
        ]
        mock_os_listdir.return_value = ["trip_point_0_type", "trip_point_0_temp"]

        # Call the method
        result = self.validator.capture_thermal()

        # Validate debug messages
        mock_record_debug.assert_any_call("Thermal zones")
        mock_record_debug.assert_any_call("└─LNXTHERM:00")
        mock_record_debug.assert_any_call("  \t temp: 45.0°C")
        mock_record_debug.assert_any_call("  \t critical trip: 50.0°C")

        # Ensure no prereq was recorded since temp < trip
        mock_record_prereq.assert_not_called()

        # Stop patches
        patch.stopall()

    def test_capture_input_wakeup_count(self):
        """Test capture_input_wakeup_count method"""
        # Mock pyudev devices
        mock_pyudev = patch.object(self.validator, "pyudev").start()
        mock_record_debug = patch.object(self.validator.db, "record_debug").start()
        mock_read_file = patch("amd_debug.validator.read_file").start()
        mock_os_path_exists = patch("os.path.exists").start()

        # Mock input devices
        mock_device = unittest.mock.Mock()
        mock_device.sys_path = "/sys/devices/input0"
        mock_device.parent = None
        mock_pyudev.list_devices.return_value = [mock_device]

        # Mock wakeup file existence and content
        mock_os_path_exists.side_effect = (
            lambda path: "wakeup" in path or "wakeup_count" in path
        )
        mock_read_file.side_effect = ["5"]  # Wakeup count

        # Set initial wakeup count
        self.validator.wakeup_count = {"/sys/devices/input0": "3"}

        # Call the method
        self.validator.capture_input_wakeup_count()

        # Validate debug messages
        mock_record_debug.assert_called_once_with(
            "Woke up from input source /sys/devices/input0 (3->5)"
        )

        # Stop patches
        patch.stopall()

    def test_capture_hw_sleep_suspend_stats(self):
        """Test capture_hw_sleep stats method"""
        # Case 1: Suspend stats file exists and contains valid data
        with patch(
            "os.path.exists", side_effect=lambda path: "suspend_stats" in path
        ), patch("amd_debug.validator.read_file", return_value="1000000"), patch.object(
            self.validator.db, "record_cycle_data"
        ) as mock_record_cycle_data:
            result = self.validator.capture_hw_sleep()
            self.assertTrue(result)
            self.assertEqual(self.validator.hw_sleep_duration, 1.0)
            mock_record_cycle_data.assert_not_called()

    def test_capture_hw_sleep_smu_fw_info(self):
        """Test capture_hw_sleep smu_fw_info method"""
        # Case 2: Suspend stats file does not exist, fallback to smu_fw_info
        with patch(
            "os.path.exists", side_effect=lambda path: "suspend_stats" not in path
        ), patch(
            "amd_debug.validator.read_file",
            side_effect=[
                "Last S0i3 Status: Success\nTime (in us) in S0i3: 2000000",  # smu_fw_info content
            ],
        ), patch.object(
            self.validator.db, "record_cycle_data"
        ) as mock_record_cycle_data:
            result = self.validator.capture_hw_sleep()
            self.assertTrue(result)
            self.assertEqual(self.validator.hw_sleep_duration, 2.0)
            mock_record_cycle_data.assert_not_called()

    def test_capture_hw_sleep_smu_fw_info_lockdown(self):
        """Test capture_hw_sleep smu_fw_info method while locked down"""
        # Case 3: PermissionError while reading smu_fw_info with lockdown enabled
        self.validator.lockdown = True
        with patch("os.path.exists", return_value=False), patch(
            "amd_debug.validator.read_file", side_effect=PermissionError
        ), patch.object(
            self.validator.db, "record_cycle_data"
        ) as mock_record_cycle_data:
            result = self.validator.capture_hw_sleep()
            self.assertFalse(result)
            mock_record_cycle_data.assert_called_once_with(
                "Unable to gather hardware sleep data with lockdown engaged", "🚦"
            )

    def test_capture_hw_sleep_smu_fw_info_missing(self):
        """Test capture_hw_sleep smu_fw_info missing method"""
        # Case 4: FileNotFoundError while reading smu_fw_info
        self.validator.lockdown = False
        with patch("os.path.exists", return_value=False), patch(
            "amd_debug.validator.read_file", side_effect=FileNotFoundError
        ), patch.object(self.validator.db, "record_debug") as mock_record:
            result = self.validator.capture_hw_sleep()
            self.assertFalse(result)
            mock_record.assert_called_once_with(
                "HW sleep statistics file /sys/kernel/debug/amd_pmc/smu_fw_info is missing"
            )

    def test_capture_amdgpu_ips_status(self):
        """Test capture_amdgpu_ips_status method"""
        # Mock pyudev devices
        mock_pyudev = patch.object(self.validator, "pyudev").start()
        mock_record_debug = patch.object(self.validator.db, "record_debug").start()
        mock_read_file = patch("amd_debug.validator.read_file").start()
        mock_os_path_exists = patch("os.path.exists").start()

        # Mock PCI devices
        mock_device = unittest.mock.Mock()
        mock_device.properties = {
            "PCI_ID": "1002:abcd",
            "PCI_SLOT_NAME": "0000:01:00.0",
        }
        mock_pyudev.list_devices.return_value = [mock_device]

        # Case 1: IPS status file exists and is readable
        mock_os_path_exists.return_value = True
        mock_read_file.return_value = "IPS Enabled\nIPS Level: 2"

        self.validator.capture_amdgpu_ips_status()

        # Validate debug messages
        mock_record_debug.assert_any_call("IPS status")
        mock_record_debug.assert_any_call("│ IPS Enabled")
        mock_record_debug.assert_any_call("└─IPS Level: 2")

        # Case 2: IPS status file does not exist
        mock_os_path_exists.return_value = False
        self.validator.capture_amdgpu_ips_status()

        # Case 3: PermissionError while reading IPS status file
        mock_os_path_exists.return_value = True
        mock_read_file.side_effect = PermissionError
        self.validator.lockdown = True
        self.validator.capture_amdgpu_ips_status()
        mock_record_debug.assert_any_call(
            "Unable to gather IPS state data due to kernel lockdown."
        )

        # Case 4: PermissionError without lockdown
        self.validator.lockdown = False
        self.validator.capture_amdgpu_ips_status()
        mock_record_debug.assert_any_call("Failed to read IPS state data")

        # Stop patches
        patch.stopall()

    def test_analyze_kernel_log(self):
        """Test analyze_kernel_log method"""
        # Mock kernel log lines
        mock_kernel_log_lines = [
            "Timekeeping suspended for 123456 us",
            "Successfully transitioned to state lps0 ms entry",
            "Triggering wakeup from IRQ 5",
            "ACPI BIOS Error (bug): Something went wrong",
            "Event logged [IO_PAGE_FAULT device=0000:00:0c.0 domain=0x0000 address=0x7e800000 flags=0x0050]",
            "Dispatching Notify on [UBTC] (Device) Value 0x80 (Status Change)",
        ]

        # Mock kernel log processing
        mock_process_callback = patch.object(
            self.validator.kernel_log, "process_callback"
        ).start()
        mock_process_callback.side_effect = lambda callback: [
            callback(line, 7) for line in mock_kernel_log_lines
        ]

        # Mock database recording
        mock_record_cycle_data = patch.object(
            self.validator.db, "record_cycle_data"
        ).start()
        mock_record_debug = patch.object(self.validator.db, "record_debug").start()

        # Call the method
        self.validator.analyze_kernel_log()

        # Validate recorded cycle data
        mock_record_cycle_data.assert_any_call("Hardware sleep cycle count: 1", "💤")
        mock_record_cycle_data.assert_any_call("ACPI BIOS errors found", "❌")
        mock_record_cycle_data.assert_any_call("Page faults found", "❌")
        mock_record_cycle_data.assert_any_call(
            "Notify devices ['UBTC'] found during suspend", "💤"
        )

        # Validate recorded debug messages
        mock_record_debug.assert_any_call("Used Microsoft uPEP GUID in LPS0 _DSM")
        mock_record_debug.assert_any_call("Triggering wakeup from IRQ 5", 7)

        # Stop patches
        patch.stopall()

    def test_prep(self):
        """Test prep method"""
        with patch("amd_debug.validator.datetime") as mock_datetime, patch.object(
            self.validator.kernel_log, "seek_tail"
        ) as mock_seek_tail, patch.object(
            self.validator.db, "start_cycle"
        ) as mock_start_cycle, patch.object(
            self.validator, "capture_battery"
        ) as mock_capture_battery, patch.object(
            self.validator, "check_gpes"
        ) as mock_check_gpes, patch.object(
            self.validator, "capture_lid"
        ) as mock_capture_lid, patch.object(
            self.validator, "capture_command_line"
        ) as mock_capture_command_line, patch.object(
            self.validator, "capture_wake_sources"
        ) as mock_capture_wake_sources, patch.object(
            self.validator, "capture_running_compositors"
        ) as mock_capture_running_compositors, patch.object(
            self.validator, "capture_power_profile"
        ) as mock_capture_power_profile, patch.object(
            self.validator, "capture_amdgpu_ips_status"
        ) as mock_capture_amdgpu_ips_status, patch.object(
            self.validator, "capture_thermal"
        ) as mock_capture_thermal, patch.object(
            self.validator, "capture_input_wakeup_count"
        ) as mock_capture_input_wakeup_count, patch.object(
            self.validator.acpica, "trace_bios"
        ) as mock_trace_bios, patch.object(
            self.validator.acpica, "trace_notify"
        ) as mock_trace_notify, patch.object(
            self.validator.db, "record_cycle"
        ) as mock_record_cycle:

            # Mock datetime
            mock_datetime.now.return_value = "mocked_datetime"

            # Set bios_debug to True and test
            self.validator.bios_debug = True
            self.validator.prep()
            mock_seek_tail.assert_called_once()
            mock_start_cycle.assert_called_once_with("mocked_datetime")
            mock_capture_battery.assert_called_once()
            mock_check_gpes.assert_called_once()
            mock_capture_lid.assert_called_once()
            mock_capture_command_line.assert_called_once()
            mock_capture_wake_sources.assert_called_once()
            mock_capture_running_compositors.assert_called_once()
            mock_capture_power_profile.assert_called_once()
            mock_capture_amdgpu_ips_status.assert_called_once()
            mock_capture_thermal.assert_called_once()
            mock_capture_input_wakeup_count.assert_called_once()
            mock_trace_bios.assert_called_once()
            mock_trace_notify.assert_not_called()
            mock_record_cycle.assert_called_once()

            # Reset mocks
            mock_seek_tail.reset_mock()
            mock_start_cycle.reset_mock()
            mock_capture_battery.reset_mock()
            mock_check_gpes.reset_mock()
            mock_capture_lid.reset_mock()
            mock_capture_command_line.reset_mock()
            mock_capture_wake_sources.reset_mock()
            mock_capture_running_compositors.reset_mock()
            mock_capture_power_profile.reset_mock()
            mock_capture_amdgpu_ips_status.reset_mock()
            mock_capture_thermal.reset_mock()
            mock_capture_input_wakeup_count.reset_mock()
            mock_trace_bios.reset_mock()
            mock_trace_notify.reset_mock()
            mock_record_cycle.reset_mock()

            # Set bios_debug to False and test
            self.validator.bios_debug = False
            self.validator.prep()
            mock_seek_tail.assert_called_once()
            mock_start_cycle.assert_called_once_with("mocked_datetime")
            mock_capture_battery.assert_called_once()
            mock_check_gpes.assert_called_once()
            mock_capture_lid.assert_called_once()
            mock_capture_command_line.assert_called_once()
            mock_capture_wake_sources.assert_called_once()
            mock_capture_running_compositors.assert_called_once()
            mock_capture_power_profile.assert_called_once()
            mock_capture_amdgpu_ips_status.assert_called_once()
            mock_capture_thermal.assert_called_once()
            mock_capture_input_wakeup_count.assert_called_once()
            mock_trace_bios.assert_not_called()
            mock_trace_notify.assert_called_once()
            mock_record_cycle.assert_called_once()

    def test_post(self):
        """Test post method"""
        with patch.object(
            self.validator, "analyze_kernel_log"
        ) as mock_analyze_kernel_log, patch.object(
            self.validator, "capture_wakeup_irq_data"
        ) as mock_capture_wakeup_irq_data, patch.object(
            self.validator, "check_gpes"
        ) as mock_check_gpes, patch.object(
            self.validator, "capture_lid"
        ) as mock_capture_lid, patch.object(
            self.validator, "check_rtc_cmos"
        ) as mock_check_rtc_cmos, patch.object(
            self.validator, "capture_hw_sleep"
        ) as mock_capture_hw_sleep, patch.object(
            self.validator, "capture_battery"
        ) as mock_capture_battery, patch.object(
            self.validator, "capture_amdgpu_ips_status"
        ) as mock_capture_amdgpu_ips_status, patch.object(
            self.validator, "capture_thermal"
        ) as mock_capture_thermal, patch.object(
            self.validator, "capture_input_wakeup_count"
        ) as mock_capture_input_wakeup_count, patch.object(
            self.validator.acpica, "restore"
        ) as mock_acpica_restore, patch.object(
            self.validator.db, "record_cycle"
        ) as mock_record_cycle:

            # Set mock return values
            mock_analyze_kernel_log.return_value = None
            mock_capture_wakeup_irq_data.return_value = None
            mock_check_gpes.return_value = None
            mock_capture_lid.return_value = None
            mock_check_rtc_cmos.return_value = None
            mock_capture_hw_sleep.return_value = None
            mock_capture_battery.return_value = None
            mock_capture_amdgpu_ips_status.return_value = None
            mock_capture_thermal.return_value = None
            mock_capture_input_wakeup_count.return_value = None
            mock_acpica_restore.return_value = None

            # Set attributes for record_cycle
            self.validator.requested_duration = 60
            self.validator.active_gpios = ["GPIO1"]
            self.validator.wakeup_irqs = ["5"]
            self.validator.kernel_duration = 1.5
            self.validator.hw_sleep_duration = 1.0

            # Call the method
            self.validator.post()

            # Assert all checks were called
            mock_analyze_kernel_log.assert_called_once()
            mock_capture_wakeup_irq_data.assert_called_once()
            mock_check_gpes.assert_called_once()
            mock_capture_lid.assert_called_once()
            mock_check_rtc_cmos.assert_called_once()
            mock_capture_hw_sleep.assert_called_once()
            mock_capture_battery.assert_called_once()
            mock_capture_amdgpu_ips_status.assert_called_once()
            mock_capture_thermal.assert_called_once()
            mock_capture_input_wakeup_count.assert_called_once()
            mock_acpica_restore.assert_called_once()

            # Assert record_cycle was called with correct arguments
            mock_record_cycle.assert_called_once_with(
                self.validator.requested_duration,
                ",".join(str(gpio) for gpio in self.validator.active_gpios),
                ",".join(str(irq) for irq in self.validator.wakeup_irqs),
                int(self.validator.kernel_duration),
                int(self.validator.hw_sleep_duration),
            )

    def test_program_wakealarm(self):
        """Test program_wakealarm method"""
        # Mock pyudev devices
        mock_pyudev = patch.object(self.validator, "pyudev").start()
        _mock_record_debug = patch.object(self.validator.db, "record_debug").start()
        mock_print_color = patch("amd_debug.validator.print_color").start()
        mock_open_file = patch("builtins.open", mock_open()).start()

        # Case 1: RTC device exists
        mock_device = unittest.mock.Mock()
        mock_device.sys_path = "/sys/class/rtc/rtc0"
        mock_pyudev.list_devices.return_value = [mock_device]
        self.validator.requested_duration = 60

        self.validator.program_wakealarm()

        # Validate file writes
        mock_open_file.assert_any_call(
            "/sys/class/rtc/rtc0/wakealarm", "w", encoding="utf-8"
        )
        mock_open_file().write.assert_any_call("0")
        mock_open_file().write.assert_any_call("+60\n")

        # Case 2: No RTC device found
        mock_pyudev.list_devices.return_value = []
        self.validator.program_wakealarm()

        # Validate print_color call
        mock_print_color.assert_called_once_with(
            "No RTC device found, please manually wake system", "🚦"
        )

        # Stop patches
        patch.stopall()

    @patch("amd_debug.validator.SleepReport")
    @patch("amd_debug.validator.print_color")
    def test_report_cycle(self, mock_print_color, mock_sleep_report):
        """Test report_cycle method"""
        # Mock SleepReport instance
        mock_report_instance = mock_sleep_report.return_value
        mock_report_instance.run.return_value = None

        # Set attributes for the test
        self.validator.last_suspend = "mocked_last_suspend"
        self.validator.display_debug = True

        # Call the method
        self.validator.report_cycle()

        # Assert print_color was called with correct arguments
        mock_print_color.assert_called_once_with("Results from last s2idle cycle", "🗣️")

        # Assert SleepReport was instantiated with correct arguments
        mock_sleep_report.assert_called_once_with(
            since="mocked_last_suspend",
            until="mocked_last_suspend",
            fname=None,
            fmt="stdout",
            tool_debug=True,
            report_debug=False,
        )

        # Assert run method of SleepReport was called
        mock_report_instance.run.assert_called_once_with(inc_prereq=False)

    @patch("amd_debug.validator.run_countdown")
    @patch("amd_debug.validator.random.randint")
    @patch("amd_debug.validator.datetime")
    @patch.object(SleepValidator, "prep")
    @patch.object(SleepValidator, "program_wakealarm")
    @patch.object(SleepValidator, "suspend_system")
    @patch.object(SleepValidator, "post")
    @patch.object(SleepValidator, "unlock_session")
    @patch.object(SleepValidator, "report_cycle")
    @patch("amd_debug.validator.print_color")
    def test_run(
        self,
        _mock_print_color,
        mock_report_cycle,
        mock_unlock_session,
        mock_post,
        mock_suspend_system,
        mock_program_wakealarm,
        mock_prep,
        mock_datetime,
        mock_randint,
        mock_run_countdown,
    ):
        """Test the run method"""
        # Mock datetime
        mock_datetime.now.return_value = datetime(2023, 1, 1, 12, 0, 0)

        # Mock suspend_system to return True
        mock_suspend_system.return_value = True

        # Test case 1: count is 0
        result = self.validator.run(
            duration=10, count=0, wait=5, rand=False, logind=False
        )
        self.assertTrue(result)

        # Test case 2: logind is True
        self.validator.run(duration=10, count=1, wait=5, rand=False, logind=True)
        self.assertTrue(self.validator.logind)

        # Test case 3: Randomized test
        mock_randint.side_effect = [7, 3]  # Random duration and wait
        self.validator.run(duration=10, count=1, wait=5, rand=True, logind=False)
        mock_randint.assert_any_call(4, 10)
        mock_randint.assert_any_call(1, 5)
        mock_run_countdown.assert_any_call("Suspending system", math.ceil(3 / 2))
        mock_run_countdown.assert_any_call("Collecting data", math.ceil(3 / 2))
        mock_prep.assert_called()
        mock_program_wakealarm.assert_called()
        mock_suspend_system.assert_called()
        mock_post.assert_called()
        mock_report_cycle.assert_called()
        mock_unlock_session.assert_called()

        # Test case 4: Randomized test, but too short of a duration
        result = self.validator.run(
            duration=4, count=1, wait=5, rand=True, logind=False
        )
        self.assertFalse(result)
        mock_report_cycle.assert_called()

        # Test case 5: Multiple cycles
        self.validator.run(duration=10, count=2, wait=5, rand=False, logind=False)
        self.assertEqual(mock_prep.call_count, 4)  # Includes previous calls
        self.assertEqual(mock_program_wakealarm.call_count, 4)
        self.assertEqual(mock_suspend_system.call_count, 4)
        self.assertEqual(mock_post.call_count, 4)
        self.assertEqual(mock_report_cycle.call_count, 5)
        self.assertEqual(mock_unlock_session.call_count, 3)

        # Test case 6: suspend_system fails
        mock_suspend_system.return_value = False
        result = self.validator.run(
            duration=10, count=1, wait=5, rand=False, logind=False
        )
        self.assertFalse(result)
        mock_report_cycle.assert_called()

    @patch("os.path.exists")
    @patch("builtins.open", new_callable=mock_open, read_data="3")
    @patch("os.write")
    @patch("os.open")
    @patch("os.close")
    def test_suspend_system_sysfs_success(
        self,
        mock_os_close,
        mock_os_open,
        mock_os_write,
        _mock_open_file,
        mock_path_exists,
    ):
        """Test suspend_system method using sysfs interface with success"""
        # Mock wakeup_count file existence
        mock_path_exists.side_effect = lambda path: "wakeup_count" in path

        # Mock os.open and os.write
        mock_os_open.return_value = 3
        mock_os_write.return_value = None

        # Call the method
        result = self.validator.suspend_system()

        # Assert the method returned True
        self.assertTrue(result)

        # Assert os.open and os.write were called
        mock_os_open.assert_called_once_with(
            "/sys/power/state", os.O_WRONLY | os.O_SYNC
        )
        mock_os_write.assert_called_once_with(3, b"mem")
        mock_os_close.assert_called_once_with(3)

    @patch("os.path.exists")
    @patch("builtins.open", new_callable=mock_open, read_data="3")
    @patch("os.write")
    @patch("os.open")
    @patch("os.close")
    def test_suspend_system_sysfs_failure(
        self,
        mock_os_close,
        mock_os_open,
        mock_os_write,
        _mock_open_file,
        mock_path_exists,
    ):
        """Test suspend_system method using sysfs interface with failure"""
        # Mock wakeup_count file existence
        mock_path_exists.side_effect = lambda path: "wakeup_count" in path

        # Mock os.open to raise OSError
        mock_os_open.return_value = 3
        mock_os_write.side_effect = OSError("Failed to write to state")

        # Call the method
        result = self.validator.suspend_system()

        # Assert the method returned False
        self.assertFalse(result)

        # Assert os.open and os.write were called
        mock_os_open.assert_called_once_with(
            "/sys/power/state", os.O_WRONLY | os.O_SYNC
        )
        mock_os_write.assert_called_once_with(3, b"mem")
        mock_os_close.assert_called_once_with(3)

    @patch("os.path.exists")
    @patch("builtins.open", new_callable=mock_open)
    @patch("os.write")
    @patch("os.open")
    @patch("os.close")
    def test_suspend_system_sysfs_no_wakeup_count(
        self,
        mock_os_close,
        mock_os_open,
        mock_os_write,
        _mock_open_file,
        mock_path_exists,
    ):
        """Test suspend_system method using sysfs interface with no wakeup_count file"""
        # Mock wakeup_count file does not exist
        mock_path_exists.return_value = False

        # Mock os.open and os.write
        mock_os_open.return_value = 3
        mock_os_write.return_value = None

        # Call the method
        result = self.validator.suspend_system()

        # Assert the method returned True
        self.assertTrue(result)

        # Assert os.open and os.write were called
        mock_os_open.assert_called_once_with(
            "/sys/power/state", os.O_WRONLY | os.O_SYNC
        )
        mock_os_write.assert_called_once_with(3, b"mem")
        mock_os_close.assert_called_once_with(3)

    @patch("os.path.exists")
    @patch("os.open")
    @patch("os.write")
    @patch("os.close")
    def test_toggle_nvidia_file_not_exists(
        self, mock_close, mock_write, mock_open, mock_exists
    ):
        """Test toggle_nvidia returns True if NVIDIA suspend file does not exist"""
        mock_exists.return_value = False
        result = self.validator.toggle_nvidia(b"suspend")
        self.assertTrue(result)
        mock_open.assert_not_called()
        mock_write.assert_not_called()
        mock_close.assert_not_called()

    @patch("os.path.exists")
    @patch("os.open")
    @patch("os.write")
    @patch("os.close")
    def test_toggle_nvidia_success(
        self, mock_close, mock_write, mock_open, mock_exists
    ):
        """Test toggle_nvidia writes value and returns True on success"""
        mock_exists.return_value = True
        mock_open.return_value = 42
        mock_write.return_value = None
        with patch.object(self.validator.db, "record_debug") as mock_record_debug:
            result = self.validator.toggle_nvidia(b"suspend")
            self.assertTrue(result)
            mock_open.assert_called_once_with(
                "/proc/driver/nvidia/suspend", os.O_WRONLY | os.O_SYNC
            )
            mock_write.assert_called_once_with(42, b"suspend")
            mock_close.assert_called_once_with(42)
            mock_record_debug.assert_called_once_with(
                "Wrote b'suspend' to NVIDIA driver"
            )

    @patch("os.path.exists")
    @patch("os.open")
    @patch("os.write")
    @patch("os.close")
    def test_toggle_nvidia_oserror(
        self, mock_close, mock_write, mock_open, mock_exists
    ):
        """Test toggle_nvidia handles OSError and returns False"""
        mock_exists.return_value = True
        mock_open.return_value = 99
        mock_write.side_effect = OSError("write error")
        with patch.object(
            self.validator.db, "record_cycle_data"
        ) as mock_record_cycle_data:
            result = self.validator.toggle_nvidia(b"resume")
            self.assertFalse(result)
            mock_open.assert_called_once_with(
                "/proc/driver/nvidia/suspend", os.O_WRONLY | os.O_SYNC
            )
            mock_write.assert_called_once_with(99, b"resume")
            mock_close.assert_called_once_with(99)
            mock_record_cycle_data.assert_called_once()

    def test_toggle_pm_debug(self):
        """toggle_pm_debug opens and writes '1' or '0'"""
        m = mock_open()
        with patch("amd_debug.validator.open", m, create=True):
            toggle_pm_debug(True)
            m().write.assert_called_with("1")
        m = mock_open()
        with patch("amd_debug.validator.open", m, create=True):
            toggle_pm_debug(False)
            m().write.assert_called_with("0")

    def test_capture_running_compositors_skips_missing_exe(self):
        """capture_running_compositors skips processes without exe link"""
        with patch("glob.glob", return_value=["/proc/100", "/proc/200"]), patch(
            "os.path.exists", side_effect=lambda p: p == "/proc/200/exe"
        ), patch("os.readlink", return_value="/usr/bin/hyprland"), patch.object(
            self.validator.db, "record_debug"
        ) as mock_record:
            self.validator.capture_running_compositors()
            mock_record.assert_called_once_with("hyprland compositor is running")

    def test_capture_power_profile_called_process_error(self):
        """capture_power_profile records debug on CalledProcessError"""
        err = subprocess.CalledProcessError(1, "powerprofilesctl", output=b"oops")
        with patch("os.path.exists", return_value=True), patch(
            "subprocess.check_output", side_effect=err
        ), patch.object(self.validator.db, "record_debug") as mock_record:
            self.validator.capture_power_profile()
            mock_record.assert_called_once()
            self.assertIn("Failed to run", mock_record.call_args[0][0])

    def test_capture_power_rails_empty(self):
        """capture_power_rails returns early when no rails detected"""
        self.validator.power_rails.rails = []
        with patch.object(
            self.validator.db, "record_power_rail_energy"
        ) as mock_record:
            self.validator.capture_power_rails()
            mock_record.assert_not_called()

    def test_capture_power_rails_oserror(self):
        """capture_power_rails records debug when rail read raises OSError"""
        rail = MagicMock(label="VDDCR_CPU", energy_scale=1.0)
        rail.read_energy_raw.side_effect = OSError("nope")
        self.validator.power_rails.rails = [rail]
        with patch.object(self.validator.db, "record_debug") as mock_record:
            self.validator.capture_power_rails()
            mock_record.assert_called_once()
            self.assertIn("Failed to read VDDCR_CPU", mock_record.call_args[0][0])

    def test_check_gpes_tracks_changes(self):
        """check_gpes reads gpe files and reports increases"""
        # populate prior counts so a change is detected
        self.validator.gpes = {"gpe01": 1}
        m = mock_open(read_data="2")
        with patch(
            "os.walk",
            return_value=[("/sys/firmware/acpi/interrupts", [], ["gpe01", "gpe_all", "irq"])],
        ), patch("amd_debug.validator.open", m, create=True), patch.object(
            self.validator.db, "record_debug"
        ) as mock_record:
            self.validator.check_gpes()
        mock_record.assert_called_once()
        self.assertIn("gpe01 increased from 1 to 2", mock_record.call_args[0][0])
        self.assertEqual(self.validator.gpes["gpe01"], 2)

    def test_capture_wakeup_irq_data_oserror(self):
        """capture_wakeup_irq_data silently handles OSError"""
        with patch(
            "amd_debug.validator.read_file", side_effect=OSError("no irq")
        ), patch.object(self.validator.db, "record_debug") as mock_record:
            self.assertTrue(self.validator.capture_wakeup_irq_data())
            mock_record.assert_not_called()

    def test_capture_thermal_no_devices(self):
        """capture_thermal returns early when no thermal devs found"""
        with patch.object(
            self.validator.pyudev, "list_devices", return_value=[]
        ), patch.object(self.validator.db, "record_debug") as mock_record:
            self.assertIsNone(self.validator.capture_thermal())
            mock_record.assert_not_called()

    def test_capture_thermal_past_trip(self):
        """capture_thermal records prereq when above trip point"""
        dev = MagicMock(
            device_path="/devices/LNXTHERM:01", sys_path="/sys/devices/LNXTHERM:01"
        )
        with patch.object(self.validator.pyudev, "list_devices", return_value=[dev]), \
             patch(
                 "amd_debug.validator.read_file",
                 side_effect=["90000", "critical", "50000"],
             ), \
             patch("os.listdir", return_value=["trip_point_0_type", "trip_point_0_temp"]), \
             patch.object(self.validator.db, "record_debug"), \
             patch.object(self.validator.db, "record_prereq") as mock_prereq:
            result = self.validator.capture_thermal()
        self.assertFalse(result)
        mock_prereq.assert_called_once()

    def test_capture_input_wakeup_count_walks_parents(self):
        """capture_input_wakeup_count walks parent devices to find wakeup_count"""
        parent = MagicMock(sys_path="/sys/devices/usb1")
        parent.parent = None
        child = MagicMock(sys_path="/sys/devices/input0")
        child.parent = parent

        def _exists(path):
            return path.startswith("/sys/devices/usb1/")

        with patch.object(
            self.validator.pyudev, "list_devices", return_value=[child]
        ), patch("os.path.exists", side_effect=_exists), patch(
            "amd_debug.validator.read_file", return_value="7"
        ):
            self.validator.capture_input_wakeup_count()
        self.assertEqual(self.validator.wakeup_count, {"/sys/devices/usb1": "7"})

    def test_capture_input_wakeup_count_no_change(self):
        """Unchanged wakeup_count does not produce a debug record"""
        child = MagicMock(sys_path="/sys/devices/input0")
        child.parent = None
        with patch.object(
            self.validator.pyudev, "list_devices", return_value=[child]
        ), patch("os.path.exists", return_value=True), patch(
            "amd_debug.validator.read_file", return_value="5"
        ), patch.object(self.validator.db, "record_debug") as mock_record:
            self.validator.wakeup_count = {"/sys/devices/input0": "5"}
            self.validator.capture_input_wakeup_count()
            mock_record.assert_not_called()

    def test_capture_command_line(self):
        """capture_command_line records the kernel command line"""
        with patch(
            "amd_debug.validator.get_kernel_command_line", return_value="quiet x=1"
        ), patch.object(self.validator.db, "record_debug") as mock_record:
            self.validator.capture_command_line()
            mock_record.assert_called_once_with("/proc/cmdline: quiet x=1")

    def test_analyze_kernel_log_line_bios_returns_early(self):
        """sscanf_bios_args returning True (no string) short-circuits debug log"""
        with patch(
            "amd_debug.validator.sscanf_bios_args", return_value=True
        ), patch.object(self.validator.db, "record_debug") as mock_record:
            # pylint: disable=protected-access
            self.validator._analyze_kernel_log_line("ex_trace_point: stuff", 6)
            mock_record.assert_not_called()

    def test_analyze_kernel_log_line_branches(self):
        """Cover all branch arms in _analyze_kernel_log_line"""
        with patch.object(self.validator.db, "record_debug"):
            # _DSM AMD (no Microsoft GUID)
            self.validator._analyze_kernel_log_line(  # pylint: disable=protected-access
                "ACPI: _DSM function 0 invoked", 7
            )
            self.assertTrue(self.validator.upep)
            self.assertFalse(self.validator.upep_microsoft)
            # _DSM Microsoft
            self.validator._analyze_kernel_log_line(  # pylint: disable=protected-access
                "ACPI: _DSM function 7 invoked", 7
            )
            self.assertTrue(self.validator.upep_microsoft)
            # Last suspend in deepest state
            self.validator._analyze_kernel_log_line(  # pylint: disable=protected-access
                "Last suspend in deepest state for 1500000us", 7
            )
            self.assertGreater(self.validator.hw_sleep_duration, 1.4)
            # SMU idlemask
            self.validator._analyze_kernel_log_line(  # pylint: disable=protected-access
                "SMU idlemask s0i3 0xabc", 7
            )
            self.assertIn("0xabc", self.validator.idle_masks)
            # GPIO active
            self.validator._analyze_kernel_log_line(  # pylint: disable=protected-access
                "GPIO 42 is active", 7
            )
            self.assertIn("42", self.validator.active_gpios)
            # IRQ1 workaround marker
            from amd_debug.validator import Headers as VH
            self.validator._analyze_kernel_log_line(VH.Irq1Workaround, 7)  # pylint: disable=protected-access
            self.assertTrue(self.validator.irq1_workaround)
            # Successfully transitioned (AMD GUID)
            self.validator._analyze_kernel_log_line(  # pylint: disable=protected-access
                "Successfully transitioned to state foo", 7
            )

    def test_analyze_kernel_log_idle_mask_bit_change(self):
        """analyze_kernel_log records idle mask bit changes"""
        self.validator.idle_masks = ["0x3", "0x1"]  # bit 1 cleared
        with patch.object(
            self.validator.kernel_log, "process_callback"
        ), patch.object(self.validator.db, "record_debug") as mock_record, patch.object(
            self.validator.db, "record_cycle_data"
        ):
            self.validator.analyze_kernel_log()
        # bit 1 changed (0x2)
        self.assertTrue(
            any("Idle mask bit 1" in c.args[0] for c in mock_record.call_args_list)
        )

    def test_analyze_kernel_log_irq1_workaround_used(self):
        """IRQ1 in wakeup with workaround marker records the workaround note"""
        self.validator.cpu_family = 0x17
        self.validator.cpu_model = 0x68
        self.validator.smu_version = "1.0.0"
        self.validator.wakeup_irqs = [1]
        self.validator.irq1_workaround = True
        with patch.object(self.validator.kernel_log, "process_callback"), patch.object(
            self.validator.db, "record_cycle_data"
        ) as mock_record_cycle, patch.object(self.validator.db, "record_debug"):
            self.validator.analyze_kernel_log()
        self.assertTrue(
            any(
                "Kernel workaround for IRQ1" in c.args[0]
                for c in mock_record_cycle.call_args_list
            )
        )

    def test_analyze_kernel_log_irq1_no_workaround(self):
        """IRQ1 in wakeup without workaround appends Irq1Workaround failure"""
        self.validator.cpu_family = 0x17
        self.validator.cpu_model = 0x68
        self.validator.smu_version = "1.0.0"
        self.validator.wakeup_irqs = [1]
        self.validator.irq1_workaround = False
        before = len(self.validator.failures)
        with patch.object(self.validator.kernel_log, "process_callback"), patch.object(
            self.validator.db, "record_cycle_data"
        ), patch.object(self.validator.db, "record_debug"):
            self.validator.analyze_kernel_log()
        self.assertEqual(len(self.validator.failures), before + 1)

    @patch("amd_debug.validator.print_color")
    def test_analyze_duration_short_success(self, mock_print):
        """Userspace duration above minimum, short cycle skips hw% check"""
        t0 = datetime(2025, 1, 1, 0, 0, 0)
        t1 = t0 + timedelta(seconds=20)
        # requested=10 -> min=9s; userspace=20s ok; <60s -> symbol is always ✅
        self.validator.analyze_duration(t0, t1, 10, kernel=15, hw=10)
        # No SpuriousWakeup or LowHardwareSleepResidency failure
        self.assertEqual(self.validator.failures, [])
        self.assertTrue(mock_print.called)

    @patch("amd_debug.validator.print_color")
    def test_analyze_duration_spurious(self, _mock_print):
        """Userspace woke too early -> SpuriousWakeup recorded"""
        from amd_debug.failures import SpuriousWakeup
        t0 = datetime(2025, 1, 1, 0, 0, 0)
        t1 = t0 + timedelta(seconds=1)
        self.validator.failures = []
        self.validator.analyze_duration(t0, t1, requested=10, kernel=1, hw=0)
        self.assertTrue(
            any(isinstance(f, SpuriousWakeup) for f in self.validator.failures)
        )

    @patch("amd_debug.validator.print_color")
    def test_analyze_duration_low_hw_residency(self, _mock_print):
        """Long cycle with low hw% -> LowHardwareSleepResidency recorded"""
        from amd_debug.failures import LowHardwareSleepResidency
        t0 = datetime(2025, 1, 1, 0, 0, 0)
        t1 = t0 + timedelta(seconds=120)
        self.validator.failures = []
        self.validator.analyze_duration(t0, t1, requested=60, kernel=110, hw=10)
        self.assertTrue(
            any(
                isinstance(f, LowHardwareSleepResidency)
                for f in self.validator.failures
            )
        )

    def test_unlock_session_no_logind(self):
        """unlock_session with logind=False short-circuits to True"""
        self.validator.logind = False
        self.assertTrue(self.validator.unlock_session())

    def test_systemd_pre_hook(self):
        """systemd_pre_hook calls prep, sync, and enables pm_debug"""
        with patch.object(self.validator, "prep") as mock_prep, patch.object(
            self.validator.db, "sync"
        ) as mock_sync, patch(
            "amd_debug.validator.toggle_pm_debug"
        ) as mock_toggle:
            self.validator.systemd_pre_hook()
            mock_prep.assert_called_once()
            mock_sync.assert_called_once()
            mock_toggle.assert_called_once_with(True)

    def test_systemd_post_hook(self):
        """systemd_post_hook restores state and runs post-processing"""
        with patch.object(self.validator, "post") as mock_post, patch.object(
            self.validator.db, "sync"
        ) as mock_sync, patch.object(
            self.validator.db, "get_last_cycle", return_value=("20250101000000",)
        ), patch.object(
            self.validator.db, "start_cycle"
        ) as mock_start_cycle, patch.object(
            self.validator.kernel_log, "seek_tail"
        ) as mock_seek_tail, patch(
            "amd_debug.validator.toggle_pm_debug"
        ) as mock_toggle:
            self.validator.systemd_post_hook()
            mock_toggle.assert_called_once_with(False)
            mock_seek_tail.assert_called_once()
            mock_start_cycle.assert_called_once()
            mock_post.assert_called_once()
            mock_sync.assert_called_once()

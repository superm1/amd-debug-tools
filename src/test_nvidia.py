#!/usr/bin/python3
# SPDX-License-Identifier: MIT

"""
This module contains unit tests for the NVIDIA driver support functions in
the amd-debug-tools package.
"""

import logging
import os
import unittest
from unittest.mock import patch

from amd_debug.nvidia import (
    DYNAMIC_PM_PARAM,
    GC6_NOT_SUPPORTED,
    GC6_SUPPORTED,
    NvidiaGpu,
    S0IX_DISABLED,
    S0IX_ENABLED,
    S0IX_NOT_SUPPORTED,
    S0IX_PARAM,
    S0IX_SUPPORTED,
    S0IX_THRESHOLD_PARAM,
    get_driver_version,
    get_module_params,
    get_nvidia_gpus,
    get_s0ix_param,
    parse_module_param_value,
    parse_power_file,
    s0ix_param_enabled,
    suspend_units_enabled,
    systemd_unit_enabled,
    systemd_unit_installed,
)

POWER_FILE = """Runtime D3 status:          Enabled
Tegra iGPU Rail-Gating:     Disabled
Video Memory:               Active

GPU Hardware Support:
 Video Memory Self Refresh: Supported
 Video Memory Off:          Not Supported

S0ix Power Management:
 Platform Support:          Supported
 Status:                    Enabled

Notebook Dynamic Boost:     Not Supported
"""


class TestParsePowerFile(unittest.TestCase):
    """Unit tests for the parse_power_file helper"""

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(filename="/dev/null", level=logging.DEBUG)

    def test_parse_power_file_full(self):
        """Test parsing a complete NVIDIA power file"""
        gpu = parse_power_file(POWER_FILE)
        self.assertEqual(gpu.runtime_d3, "Enabled")
        self.assertEqual(gpu.video_memory, "Active")
        self.assertEqual(gpu.video_memory_self_refresh, GC6_SUPPORTED)
        self.assertEqual(gpu.video_memory_off, GC6_NOT_SUPPORTED)
        self.assertEqual(gpu.s0ix_platform_support, S0IX_SUPPORTED)
        self.assertEqual(gpu.s0ix_status, S0IX_ENABLED)
        self.assertEqual(gpu.dynamic_boost, "Not Supported")

    def test_parse_power_file_empty(self):
        """Test parsing an empty NVIDIA power file"""
        gpu = parse_power_file("")
        self.assertEqual(gpu.runtime_d3, "")
        self.assertEqual(gpu.video_memory, "")
        self.assertEqual(gpu.video_memory_self_refresh, "")
        self.assertEqual(gpu.video_memory_off, "")
        self.assertEqual(gpu.s0ix_platform_support, "")
        self.assertEqual(gpu.s0ix_status, "")
        self.assertEqual(gpu.dynamic_boost, "")

    def test_parse_power_file_ignores_unknown_keys(self):
        """Test that unknown keys in the power file are ignored"""
        gpu = parse_power_file("Some Future Key:  Value\n")
        self.assertEqual(gpu.runtime_d3, "")
        self.assertEqual(gpu.s0ix_status, "")

    def test_parse_power_file_ignores_lines_without_colon(self):
        """Test that lines without a colon are ignored"""
        gpu = parse_power_file("no colon here\nStatus:   Disabled\n")
        self.assertEqual(gpu.s0ix_status, S0IX_DISABLED)

    def test_parse_power_file_s0ix_not_supported(self):
        """Test parsing a power file for a GPU without S0ix support"""
        gpu = parse_power_file(
            "S0ix Power Management:\n"
            " Platform Support:          Not Supported\n"
            " Status:                    Disabled\n"
        )
        self.assertEqual(gpu.s0ix_platform_support, S0IX_NOT_SUPPORTED)
        self.assertEqual(gpu.s0ix_status, S0IX_DISABLED)
        self.assertFalse(gpu.s0ix_supported)
        self.assertFalse(gpu.s0ix_enabled)

    def test_parse_power_file_s0ix_enabled(self):
        """Test parsing a power file for a GPU with S0ix enabled"""
        gpu = parse_power_file(
            "S0ix Power Management:\n"
            " Platform Support:          Supported\n"
            " Status:                    Enabled\n"
        )
        self.assertTrue(gpu.s0ix_supported)
        self.assertTrue(gpu.s0ix_enabled)

    def test_parse_power_file_missing_s0ix_section(self):
        """Test parsing a power file without an S0ix section"""
        gpu = parse_power_file("Runtime D3 status:          Enabled\n")
        self.assertFalse(gpu.s0ix_supported)
        self.assertFalse(gpu.s0ix_enabled)


class TestNvidiaGpu(unittest.TestCase):
    """Unit tests for the NvidiaGpu class"""

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(filename="/dev/null", level=logging.DEBUG)

    def test_s0ix_supported(self):
        """Test the s0ix_supported property"""
        gpu = NvidiaGpu("0000:01:00.0")
        gpu.s0ix_platform_support = S0IX_SUPPORTED
        self.assertTrue(gpu.s0ix_supported)

    def test_s0ix_not_supported(self):
        """Test the s0ix_supported property when unsupported"""
        gpu = NvidiaGpu("0000:01:00.0")
        gpu.s0ix_platform_support = S0IX_NOT_SUPPORTED
        self.assertFalse(gpu.s0ix_supported)

    def test_s0ix_enabled(self):
        """Test the s0ix_enabled property"""
        gpu = NvidiaGpu("0000:01:00.0")
        gpu.s0ix_status = S0IX_ENABLED
        self.assertTrue(gpu.s0ix_enabled)

    def test_s0ix_disabled(self):
        """Test the s0ix_enabled property when disabled"""
        gpu = NvidiaGpu("0000:01:00.0")
        gpu.s0ix_status = S0IX_DISABLED
        self.assertFalse(gpu.s0ix_enabled)

    def test_str(self):
        """Test the string representation of a GPU"""
        gpu = NvidiaGpu("0000:01:00.0")
        self.assertEqual(str(gpu), "NVIDIA GPU 0000:01:00.0")


class TestGetNvidiaGpus(unittest.TestCase):
    """Unit tests for the get_nvidia_gpus helper"""

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(filename="/dev/null", level=logging.DEBUG)

    @patch("amd_debug.nvidia.read_file")
    @patch("amd_debug.nvidia.os.path.exists")
    @patch("amd_debug.nvidia.os.path.isdir")
    @patch("amd_debug.nvidia.os.listdir")
    def test_get_nvidia_gpus(
        self, mock_listdir, mock_isdir, mock_exists, mock_read_file
    ):
        """Test that GPUs are discovered from /proc/driver/nvidia/gpus"""
        mock_isdir.return_value = True
        mock_listdir.return_value = ["0000:01:00.0"]
        mock_exists.return_value = True
        mock_read_file.return_value = POWER_FILE

        gpus = get_nvidia_gpus()
        self.assertEqual(len(gpus), 1)
        self.assertEqual(gpus[0].bdf, "0000:01:00.0")
        self.assertEqual(gpus[0].s0ix_status, S0IX_ENABLED)

    @patch("amd_debug.nvidia.os.path.isdir")
    def test_get_nvidia_gpus_no_driver(self, mock_isdir):
        """Test that no GPUs are found when the driver isn't loaded"""
        mock_isdir.return_value = False
        gpus = get_nvidia_gpus()
        self.assertEqual(gpus, [])

    @patch("amd_debug.nvidia.read_file")
    @patch("amd_debug.nvidia.os.path.exists")
    @patch("amd_debug.nvidia.os.path.isdir")
    @patch("amd_debug.nvidia.os.listdir")
    def test_get_nvidia_gpus_skips_missing_power_file(
        self, mock_listdir, mock_isdir, mock_exists, mock_read_file
    ):
        """Test that GPUs without a power file are skipped"""
        mock_isdir.return_value = True
        mock_listdir.return_value = ["0000:01:00.0"]
        mock_exists.return_value = False
        gpus = get_nvidia_gpus()
        self.assertEqual(gpus, [])
        mock_read_file.assert_not_called()

    @patch("amd_debug.nvidia.read_file")
    @patch("amd_debug.nvidia.os.path.exists")
    @patch("amd_debug.nvidia.os.path.isdir")
    @patch("amd_debug.nvidia.os.listdir")
    def test_get_nvidia_gpus_unreadable_power_file(
        self, mock_listdir, mock_isdir, mock_exists, mock_read_file
    ):
        """Test that GPUs with an unreadable power file are skipped"""
        mock_isdir.return_value = True
        mock_listdir.return_value = ["0000:01:00.0"]
        mock_exists.return_value = True
        mock_read_file.side_effect = PermissionError
        gpus = get_nvidia_gpus()
        self.assertEqual(gpus, [])

    @patch("amd_debug.nvidia.read_file")
    @patch("amd_debug.nvidia.os.path.exists")
    @patch("amd_debug.nvidia.os.path.isdir")
    @patch("amd_debug.nvidia.os.listdir")
    def test_get_nvidia_gpus_multiple(
        self, mock_listdir, mock_isdir, mock_exists, mock_read_file
    ):
        """Test that multiple GPUs are discovered"""
        mock_isdir.return_value = True
        mock_listdir.return_value = ["0000:01:00.0", "0000:02:00.0"]
        mock_exists.return_value = True
        mock_read_file.return_value = POWER_FILE
        gpus = get_nvidia_gpus()
        self.assertEqual(len(gpus), 2)
        self.assertEqual(gpus[0].bdf, "0000:01:00.0")
        self.assertEqual(gpus[1].bdf, "0000:02:00.0")


class TestGetModuleParams(unittest.TestCase):
    """Unit tests for the module parameter helpers"""

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(filename="/dev/null", level=logging.DEBUG)

    @patch("amd_debug.nvidia.read_file")
    @patch("amd_debug.nvidia.os.path.exists")
    def test_get_module_params(self, mock_exists, mock_read_file):
        """Test that module parameters are parsed"""
        mock_exists.return_value = True
        mock_read_file.return_value = (
            "EnableS0ixPowerManagement: 1\n"
            "NVreg_DynamicPowerManagement: 0x03\n"
        )
        params = get_module_params()
        self.assertEqual(params[S0IX_PARAM], "1")
        self.assertEqual(params[DYNAMIC_PM_PARAM], "0x03")

    @patch("amd_debug.nvidia.os.path.exists")
    def test_get_module_params_no_driver(self, mock_exists):
        """Test that no parameters are returned when the driver isn't loaded"""
        mock_exists.return_value = False
        params = get_module_params()
        self.assertEqual(params, {})

    @patch("amd_debug.nvidia.read_file")
    @patch("amd_debug.nvidia.os.path.exists")
    def test_get_module_params_unreadable(self, mock_exists, mock_read_file):
        """Test that no parameters are returned when the file is unreadable"""
        mock_exists.return_value = True
        mock_read_file.side_effect = PermissionError
        params = get_module_params()
        self.assertEqual(params, {})

    @patch("amd_debug.nvidia.read_file")
    @patch("amd_debug.nvidia.os.path.exists")
    def test_get_module_params_ignores_malformed(self, mock_exists, mock_read_file):
        """Test that lines without a colon are ignored"""
        mock_exists.return_value = True
        mock_read_file.return_value = (
            "malformed line\nEnableS0ixPowerManagement: 0\n"
        )
        params = get_module_params()
        self.assertEqual(params[S0IX_PARAM], "0")

    @patch("amd_debug.nvidia.read_file")
    @patch("amd_debug.nvidia.os.path.exists")
    def test_get_s0ix_param(self, mock_exists, mock_read_file):
        """Test that the S0ix parameter is found"""
        mock_exists.return_value = True
        mock_read_file.return_value = "EnableS0ixPowerManagement: 1\n"
        self.assertEqual(get_s0ix_param(), "1")

    @patch("amd_debug.nvidia.read_file")
    @patch("amd_debug.nvidia.os.path.exists")
    def test_get_s0ix_param_prefixed(self, mock_exists, mock_read_file):
        """Test that the prefixed parameter name is still found

        Older drivers report the parameter with the NVreg_ prefix that it
        is registered with on the kernel command line.
        """
        mock_exists.return_value = True
        mock_read_file.return_value = "NVreg_EnableS0ixPowerManagement: 1\n"
        self.assertEqual(get_s0ix_param(), "1")

    @patch("amd_debug.nvidia.read_file")
    @patch("amd_debug.nvidia.os.path.exists")
    def test_get_s0ix_param_missing(self, mock_exists, mock_read_file):
        """Test that a missing S0ix parameter returns an empty string"""
        mock_exists.return_value = True
        mock_read_file.return_value = "NVreg_DynamicPowerManagement: 0x03\n"
        self.assertEqual(get_s0ix_param(), "")

    @patch("amd_debug.nvidia.read_file")
    @patch("amd_debug.nvidia.os.path.exists")
    def test_s0ix_param_enabled(self, mock_exists, mock_read_file):
        """Test that the S0ix parameter is detected as enabled"""
        mock_exists.return_value = True
        mock_read_file.return_value = "EnableS0ixPowerManagement: 1\n"
        self.assertTrue(s0ix_param_enabled())

    @patch("amd_debug.nvidia.read_file")
    @patch("amd_debug.nvidia.os.path.exists")
    def test_s0ix_param_disabled(self, mock_exists, mock_read_file):
        """Test that the S0ix parameter is detected as disabled"""
        mock_exists.return_value = True
        mock_read_file.return_value = "EnableS0ixPowerManagement: 0\n"
        self.assertFalse(s0ix_param_enabled())


class TestParseModuleParamValue(unittest.TestCase):
    """Unit tests for the parse_module_param_value helper"""

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(filename="/dev/null", level=logging.DEBUG)

    def test_parse_module_param_value(self):
        """Test that a parameter value is found"""
        contents = (
            "EnableS0ixPowerManagement: 1\n"
            "NVreg_S0ixPowerManagementVideoMemoryThreshold: 256\n"
        )
        self.assertEqual(parse_module_param_value(contents, S0IX_PARAM), "1")
        self.assertEqual(
            parse_module_param_value(contents, S0IX_THRESHOLD_PARAM), "256"
        )

    def test_parse_module_param_value_missing(self):
        """Test that a missing parameter returns an empty string"""
        self.assertEqual(parse_module_param_value("nothing here\n", S0IX_PARAM), "")

    def test_parse_module_param_value_not_prefix_match(self):
        """Test that a parameter name must match completely"""
        contents = "NotEnableS0ixPowerManagement: 1\n"
        self.assertEqual(parse_module_param_value(contents, S0IX_PARAM), "")

    def test_parse_module_param_value_preserve_video_memory(self):
        """Test that the video memory preservation parameter can be parsed

        The parameter is parsed by the generic helper, but the tool
        deliberately does not check or enforce it.
        """
        contents = "NVreg_PreserveVideoMemoryAllocations: 1\n"
        self.assertEqual(
            parse_module_param_value(contents, "NVreg_PreserveVideoMemoryAllocations"),
            "1",
        )


class TestGetDriverVersion(unittest.TestCase):
    """Unit tests for the get_driver_version helper"""

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(filename="/dev/null", level=logging.DEBUG)

    @patch("amd_debug.nvidia.read_file")
    @patch("amd_debug.nvidia.os.path.exists")
    def test_get_driver_version(self, mock_exists, mock_read_file):
        """Test that the driver version is read"""
        mock_exists.return_value = True
        mock_read_file.return_value = "NVIDIA 570.172.08  Thu Aug  8 01:00:00 UTC 2024"
        self.assertIn("570.172.08", get_driver_version())

    @patch("amd_debug.nvidia.os.path.exists")
    def test_get_driver_version_no_driver(self, mock_exists):
        """Test that no version is returned when the driver isn't loaded"""
        mock_exists.return_value = False
        self.assertEqual(get_driver_version(), "")

    @patch("amd_debug.nvidia.read_file")
    @patch("amd_debug.nvidia.os.path.exists")
    def test_get_driver_version_unreadable(self, mock_exists, mock_read_file):
        """Test that no version is returned when the file is unreadable"""
        mock_exists.return_value = True
        mock_read_file.side_effect = PermissionError
        self.assertEqual(get_driver_version(), "")


class TestSystemdUnits(unittest.TestCase):
    """Unit tests for the systemd unit helpers"""

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(filename="/dev/null", level=logging.DEBUG)

    @patch("amd_debug.nvidia.os.path.exists")
    def test_systemd_unit_installed(self, mock_exists):
        """Test that an installed systemd unit is detected"""
        mock_exists.return_value = True
        self.assertTrue(systemd_unit_installed("nvidia-suspend.service"))

    @patch("amd_debug.nvidia.os.path.exists")
    def test_systemd_unit_not_installed(self, mock_exists):
        """Test that a missing systemd unit is detected"""
        mock_exists.return_value = False
        self.assertFalse(systemd_unit_installed("nvidia-suspend.service"))

    @patch("amd_debug.nvidia.subprocess.run")
    def test_systemd_unit_enabled(self, mock_run):
        """Test that an enabled systemd unit is detected"""
        mock_run.return_value.returncode = 0
        self.assertTrue(systemd_unit_enabled("nvidia-suspend.service"))

    @patch("amd_debug.nvidia.subprocess.run")
    def test_systemd_unit_not_enabled(self, mock_run):
        """Test that a disabled systemd unit is detected"""
        mock_run.return_value.returncode = 1
        self.assertFalse(systemd_unit_enabled("nvidia-suspend.service"))

    @patch("amd_debug.nvidia.subprocess.run", side_effect=FileNotFoundError)
    def test_systemd_unit_enabled_no_systemctl(self, mock_run):
        """Test that a missing systemctl is handled"""
        self.assertFalse(systemd_unit_enabled("nvidia-suspend.service"))

    @patch("amd_debug.nvidia.subprocess.run")
    def test_systemd_unit_enabled_timeout(self, mock_run):
        """Test that a systemctl timeout is handled"""
        import subprocess as sp

        mock_run.side_effect = sp.TimeoutExpired("systemctl", 10)
        self.assertFalse(systemd_unit_enabled("nvidia-suspend.service"))

    @patch("amd_debug.nvidia.subprocess.run")
    def test_systemd_unit_enabled_uses_timeout(self, mock_run):
        """Test that the systemctl call is bounded by a timeout"""
        mock_run.return_value.returncode = 0
        systemd_unit_enabled("nvidia-suspend.service")
        self.assertEqual(mock_run.call_args[1]["timeout"], 10)

    @patch("amd_debug.nvidia.systemd_unit_enabled")
    @patch("amd_debug.nvidia.systemd_unit_installed")
    def test_suspend_units_enabled(self, mock_installed, mock_enabled):
        """Test that enabled suspend units are detected"""
        mock_installed.return_value = True
        mock_enabled.return_value = True
        self.assertTrue(suspend_units_enabled())

    @patch("amd_debug.nvidia.systemd_unit_enabled")
    @patch("amd_debug.nvidia.systemd_unit_installed")
    def test_suspend_units_not_enabled(self, mock_installed, mock_enabled):
        """Test that disabled suspend units are detected"""
        mock_installed.return_value = True
        mock_enabled.return_value = False
        self.assertFalse(suspend_units_enabled())

    @patch("amd_debug.nvidia.systemd_unit_enabled")
    @patch("amd_debug.nvidia.systemd_unit_installed")
    def test_suspend_units_not_installed(self, mock_installed, mock_enabled):
        """Test that missing suspend units are detected"""
        mock_installed.return_value = False
        self.assertFalse(suspend_units_enabled())
        mock_enabled.assert_not_called()


if __name__ == "__main__":
    unittest.main()

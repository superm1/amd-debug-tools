#!/usr/bin/python3
# SPDX-License-Identifier: MIT

"""
This module contains unit tests for the NVIDIA driver prerequisite
functions in the amd-debug-tools package.
"""

import logging
import unittest
from unittest.mock import patch, MagicMock

from amd_debug.prereq.nvidia import NvidiaChecks
from amd_debug.failures import (
    NvidiaS0ixDisabled,
    NvidiaS0ixUnsupported,
)
from amd_debug.nvidia import (
    KERNEL_NOTIFIERS_PARAM,
    POWERD_UNIT,
    S0IX_DISABLED,
    S0IX_ENABLED,
    S0IX_NOT_SUPPORTED,
    S0IX_PARAM,
    S0IX_SUPPORTED,
    SUSPEND_UNITS,
)


class FakeNvidiaChecks(NvidiaChecks):
    """Minimal stand-in for the prerequisite validator"""

    def __init__(self):
        self.db = MagicMock()
        self.failures = []


class TestNvidiaChecks(unittest.TestCase):
    """Unit tests for the NVIDIA prerequisite checks"""

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(filename="/dev/null", level=logging.DEBUG)

    def setUp(self):
        """Set up a mock context for testing"""
        self.validator = FakeNvidiaChecks()

    def _make_gpu(self, supported=True, enabled=True, self_refresh="Supported"):
        """Build a fake NVIDIA GPU object"""
        gpu = MagicMock()
        gpu.bdf = "0000:01:00.0"
        gpu.s0ix_supported = supported
        gpu.s0ix_status = S0IX_ENABLED if enabled else S0IX_DISABLED
        gpu.video_memory_self_refresh = self_refresh
        gpu.runtime_d3 = "Enabled"
        gpu.video_memory = "Active"
        gpu.video_memory_off = "Supported"
        gpu.s0ix_platform_support = S0IX_SUPPORTED if supported else S0IX_NOT_SUPPORTED
        gpu.dynamic_boost = "Not Supported"
        return gpu

    @patch("amd_debug.prereq.nvidia.get_s0ix_param")
    @patch("amd_debug.prereq.nvidia.get_nvidia_gpus")
    def test_check_nvidia_s0ix_no_gpus(self, mock_gpus, mock_param):
        """Test that no check is performed without an NVIDIA GPU"""
        mock_gpus.return_value = []
        result = self.validator.check_nvidia_s0ix()
        self.assertTrue(result)
        mock_param.assert_not_called()

    @patch("amd_debug.prereq.nvidia.get_s0ix_param")
    @patch("amd_debug.prereq.nvidia.get_nvidia_gpus")
    def test_check_nvidia_s0ix_platform_unsupported(self, mock_gpus, mock_param):
        """Test that a platform without S0ix support is not a failure"""
        mock_gpus.return_value = [self._make_gpu(supported=False)]
        result = self.validator.check_nvidia_s0ix()
        self.assertTrue(result)
        self.assertEqual(self.validator.failures, [])

    @patch("amd_debug.prereq.nvidia.get_s0ix_param")
    @patch("amd_debug.prereq.nvidia.get_nvidia_gpus")
    def test_check_nvidia_s0ix_param_missing(self, mock_gpus, mock_param):
        """Test that a missing S0ix module parameter is a failure"""
        mock_gpus.return_value = [self._make_gpu()]
        mock_param.return_value = ""
        result = self.validator.check_nvidia_s0ix()
        self.assertFalse(result)
        self.assertTrue(
            any(isinstance(f, NvidiaS0ixDisabled) for f in self.validator.failures)
        )

    @patch("amd_debug.prereq.nvidia.get_s0ix_param")
    @patch("amd_debug.prereq.nvidia.get_nvidia_gpus")
    def test_check_nvidia_s0ix_param_disabled(self, mock_gpus, mock_param):
        """Test that a disabled S0ix module parameter is a failure"""
        mock_gpus.return_value = [self._make_gpu()]
        mock_param.return_value = "0"
        result = self.validator.check_nvidia_s0ix()
        self.assertFalse(result)
        self.assertTrue(
            any(isinstance(f, NvidiaS0ixDisabled) for f in self.validator.failures)
        )

    @patch("amd_debug.prereq.nvidia.get_s0ix_param")
    @patch("amd_debug.prereq.nvidia.get_nvidia_gpus")
    def test_check_nvidia_s0ix_param_enabled(self, mock_gpus, mock_param):
        """Test that an enabled S0ix module parameter passes"""
        mock_gpus.return_value = [self._make_gpu()]
        mock_param.return_value = "1"
        result = self.validator.check_nvidia_s0ix()
        self.assertTrue(result)
        self.assertEqual(self.validator.failures, [])

    @patch("amd_debug.nvidia.get_module_params")
    @patch("amd_debug.prereq.nvidia.get_s0ix_param")
    @patch("amd_debug.prereq.nvidia.get_nvidia_gpus")
    def test_check_nvidia_s0ix_ignores_preserve_video_memory(
        self, mock_gpus, mock_param, mock_params
    ):
        """Test that the video memory preservation parameter is not checked

        Setting NVreg_PreserveVideoMemoryAllocations to 1 prevents some
        hardware from entering D3cold, so the tool must not check or
        enforce it.  The default of 0 is the correct value.
        """
        mock_gpus.return_value = [self._make_gpu()]
        mock_param.return_value = "1"
        mock_params.return_value = {
            "NVreg_EnableS0ixPowerManagement": "1",
            "NVreg_PreserveVideoMemoryAllocations": "1",
        }
        result = self.validator.check_nvidia_s0ix()
        self.assertTrue(result)
        self.assertEqual(self.validator.failures, [])
        # The parameter must not be read by the checks at all
        mock_params.assert_not_called()

    @patch("amd_debug.prereq.nvidia.get_s0ix_param")
    @patch("amd_debug.prereq.nvidia.get_nvidia_gpus")
    def test_check_nvidia_s0ix_gpu_disabled(self, mock_gpus, mock_param):
        """Test that a GPU with S0ix disabled is a failure"""
        mock_gpus.return_value = [self._make_gpu(enabled=False)]
        mock_param.return_value = "1"
        result = self.validator.check_nvidia_s0ix()
        self.assertFalse(result)
        self.assertTrue(
            any(isinstance(f, NvidiaS0ixDisabled) for f in self.validator.failures)
        )

    @patch("amd_debug.prereq.nvidia.get_s0ix_param")
    @patch("amd_debug.prereq.nvidia.get_nvidia_gpus")
    def test_check_nvidia_s0ix_gpu_unknown_status(self, mock_gpus, mock_param):
        """Test that an unknown S0ix status is not a failure"""
        gpu = self._make_gpu()
        gpu.s0ix_status = "?"
        mock_gpus.return_value = [gpu]
        mock_param.return_value = "1"
        result = self.validator.check_nvidia_s0ix()
        self.assertTrue(result)
        self.assertEqual(self.validator.failures, [])

    @patch("amd_debug.prereq.nvidia.get_nvidia_gpus")
    def test_check_nvidia_video_memory_no_gpus(self, mock_gpus):
        """Test that no check is performed without an NVIDIA GPU"""
        mock_gpus.return_value = []
        result = self.validator.check_nvidia_video_memory()
        self.assertTrue(result)

    @patch("amd_debug.prereq.nvidia.get_nvidia_gpus")
    def test_check_nvidia_video_memory_supported(self, mock_gpus):
        """Test that a GPU with self refresh support passes"""
        mock_gpus.return_value = [self._make_gpu(self_refresh="Supported")]
        result = self.validator.check_nvidia_video_memory()
        self.assertTrue(result)
        self.assertEqual(self.validator.failures, [])

    @patch("amd_debug.prereq.nvidia.get_nvidia_gpus")
    def test_check_nvidia_video_memory_not_supported(self, mock_gpus):
        """Test that a GPU without self refresh support is a failure"""
        mock_gpus.return_value = [self._make_gpu(self_refresh="Not Supported")]
        result = self.validator.check_nvidia_video_memory()
        self.assertFalse(result)
        self.assertTrue(
            any(isinstance(f, NvidiaS0ixUnsupported) for f in self.validator.failures)
        )

    @patch("amd_debug.prereq.nvidia.get_nvidia_gpus")
    def test_check_nvidia_video_memory_unknown(self, mock_gpus):
        """Test that an unknown self refresh support is not a failure"""
        mock_gpus.return_value = [self._make_gpu(self_refresh="?")]
        result = self.validator.check_nvidia_video_memory()
        self.assertTrue(result)
        self.assertEqual(self.validator.failures, [])

    @patch("amd_debug.prereq.nvidia.get_nvidia_gpus")
    def test_check_nvidia_video_memory_platform_unsupported(self, mock_gpus):
        """Test that the self refresh check is skipped without S0ix support"""
        mock_gpus.return_value = [
            self._make_gpu(supported=False, self_refresh="Not Supported")
        ]
        result = self.validator.check_nvidia_video_memory()
        self.assertTrue(result)
        self.assertEqual(self.validator.failures, [])

    @patch("amd_debug.prereq.nvidia.SUSPEND_UNITS")
    @patch("amd_debug.prereq.nvidia.get_nvidia_gpus")
    def test_check_nvidia_suspend_units_no_gpus(self, mock_gpus, mock_units):
        """Test that no check is performed without an NVIDIA GPU"""
        mock_gpus.return_value = []
        result = self.validator.check_nvidia_suspend_units()
        self.assertTrue(result)

    @patch("amd_debug.prereq.nvidia.get_module_params", return_value={})
    @patch("amd_debug.prereq.nvidia.get_nvidia_gpus")
    def test_check_nvidia_suspend_units_missing(self, mock_gpus, _mock_params):
        """Test that missing systemd units are an improvement, not a failure

        The kernel sleep notifiers are the preferred method for notifying
        the driver of the suspend and resume events, so the legacy systemd
        units are reported as a possible improvement rather than an error.
        """
        mock_gpus.return_value = [self._make_gpu()]
        with patch.object(
            self.validator, "_systemd_unit_exists", return_value=True
        ), patch.object(self.validator, "_systemd_unit_enabled", return_value=False):
            result = self.validator.check_nvidia_suspend_units()
        self.assertTrue(result)
        self.assertEqual(self.validator.failures, [])

    @patch(
        "amd_debug.prereq.nvidia.get_module_params",
        return_value={KERNEL_NOTIFIERS_PARAM: "1"},
    )
    @patch("amd_debug.prereq.nvidia.get_nvidia_gpus")
    def test_check_nvidia_suspend_units_kernel_notifiers(
        self, mock_gpus, _mock_params
    ):
        """Test that the kernel sleep notifiers are the preferred method

        When the driver handles the notifications itself the systemd units
        are not needed and the unit checks are not run at all.
        """
        mock_gpus.return_value = [self._make_gpu()]
        with patch.object(
            self.validator, "_systemd_unit_exists", return_value=True
        ) as mock_exists, patch.object(
            self.validator, "_systemd_unit_enabled", return_value=True
        ) as mock_enabled:
            result = self.validator.check_nvidia_suspend_units()
        self.assertTrue(result)
        self.assertEqual(self.validator.failures, [])
        mock_exists.assert_not_called()
        mock_enabled.assert_not_called()

    @patch("amd_debug.prereq.nvidia.get_module_params", return_value={})
    @patch("amd_debug.prereq.nvidia.get_nvidia_gpus")
    def test_check_nvidia_suspend_units_enabled(self, mock_gpus, _mock_params):
        """Test that enabled systemd units pass"""
        mock_gpus.return_value = [self._make_gpu()]
        with patch.object(
            self.validator, "_systemd_unit_exists", return_value=True
        ), patch.object(self.validator, "_systemd_unit_enabled", return_value=True):
            result = self.validator.check_nvidia_suspend_units()
        self.assertTrue(result)
        self.assertEqual(self.validator.failures, [])

    @patch("amd_debug.prereq.nvidia.get_module_params", return_value={})
    @patch("amd_debug.prereq.nvidia.get_nvidia_gpus")
    def test_check_nvidia_suspend_units_not_installed(
        self, mock_gpus, _mock_params
    ):
        """Test that units which aren't installed are not a failure"""
        mock_gpus.return_value = [self._make_gpu()]
        with patch.object(self.validator, "_systemd_unit_exists", return_value=False):
            result = self.validator.check_nvidia_suspend_units()
        self.assertTrue(result)
        self.assertEqual(self.validator.failures, [])

    @patch("amd_debug.prereq.nvidia.get_nvidia_gpus")
    def test_check_nvidia_powerd_no_gpus(self, mock_gpus):
        """Test that no check is performed without an NVIDIA GPU"""
        mock_gpus.return_value = []
        result = self.validator.check_nvidia_powerd()
        self.assertTrue(result)

    @patch("amd_debug.prereq.nvidia.get_nvidia_gpus")
    def test_check_nvidia_powerd_not_installed(self, mock_gpus):
        """Test that a missing nvidia-powerd is not a failure"""
        mock_gpus.return_value = [self._make_gpu()]
        with patch.object(self.validator, "_systemd_unit_exists", return_value=False):
            result = self.validator.check_nvidia_powerd()
        self.assertTrue(result)
        self.assertEqual(self.validator.failures, [])

    @patch("amd_debug.prereq.nvidia.get_nvidia_gpus")
    def test_check_nvidia_powerd_not_enabled(self, mock_gpus):
        """Test that a disabled nvidia-powerd is not a failure"""
        mock_gpus.return_value = [self._make_gpu()]
        with patch.object(
            self.validator, "_systemd_unit_exists", return_value=True
        ), patch.object(self.validator, "_systemd_unit_enabled", return_value=False):
            result = self.validator.check_nvidia_powerd()
        self.assertTrue(result)
        self.assertEqual(self.validator.failures, [])

    @patch("amd_debug.prereq.nvidia.get_nvidia_gpus")
    def test_check_nvidia_powerd_enabled(self, mock_gpus):
        """Test that an enabled nvidia-powerd passes"""
        mock_gpus.return_value = [self._make_gpu()]
        with patch.object(
            self.validator, "_systemd_unit_exists", return_value=True
        ), patch.object(self.validator, "_systemd_unit_enabled", return_value=True):
            result = self.validator.check_nvidia_powerd()
        self.assertTrue(result)
        self.assertEqual(self.validator.failures, [])

    @patch("amd_debug.prereq.nvidia.get_nvidia_gpus")
    def test_capture_nvidia_power(self, mock_gpus):
        """Test that the NVIDIA power state is captured"""
        mock_gpus.return_value = [self._make_gpu()]
        self.validator.capture_nvidia_power()
        self.validator.db.record_debug.assert_called_once()
        debug = self.validator.db.record_debug.call_args[0][0]
        self.assertIn("0000:01:00.0", debug)
        self.assertIn("S0ix Status: Enabled", debug)

    @patch("amd_debug.prereq.nvidia.get_nvidia_gpus")
    def test_capture_nvidia_power_no_gpus(self, mock_gpus):
        """Test that nothing is captured without an NVIDIA GPU"""
        mock_gpus.return_value = []
        self.validator.capture_nvidia_power()
        self.validator.db.record_debug.assert_not_called()

    def test_systemd_unit_enabled(self):
        """Test that the systemd unit enabled check works"""
        with patch("amd_debug.nvidia.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            self.assertTrue(self.validator._systemd_unit_enabled("foo.service"))
            mock_run.assert_called_once_with(
                ["systemctl", "is-enabled", "foo.service"],
                check=False,
                capture_output=True,
                timeout=10,
            )

    def test_systemd_unit_enabled_not(self):
        """Test that a disabled systemd unit is detected"""
        with patch("amd_debug.nvidia.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            self.assertFalse(self.validator._systemd_unit_enabled("foo.service"))

    def test_systemd_unit_enabled_no_systemctl(self):
        """Test that a missing systemctl is handled"""
        with patch(
            "amd_debug.nvidia.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            self.assertFalse(self.validator._systemd_unit_enabled("foo.service"))

    def test_systemd_unit_enabled_timeout(self):
        """Test that a systemctl timeout is handled"""
        import subprocess as sp

        with patch(
            "amd_debug.nvidia.subprocess.run",
            side_effect=sp.TimeoutExpired("systemctl", 10),
        ):
            self.assertFalse(self.validator._systemd_unit_enabled("foo.service"))

    def test_systemd_unit_exists(self):
        """Test that the systemd unit exists check works"""
        with patch("amd_debug.nvidia.os.path.exists", return_value=True):
            self.assertTrue(self.validator._systemd_unit_exists("foo.service"))

    def test_systemd_unit_not_exists(self):
        """Test that a missing systemd unit is detected"""
        with patch("amd_debug.nvidia.os.path.exists", return_value=False):
            self.assertFalse(self.validator._systemd_unit_exists("foo.service"))


if __name__ == "__main__":
    unittest.main()

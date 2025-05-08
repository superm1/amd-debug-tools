#!/usr/bin/python3
# SPDX-License-Identifier: MIT

"""
This module contains unit tests for the installer functions in the amd-debug-tools package.
"""
from unittest.mock import patch, mock_open

import logging
import unittest
import sys
import os

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from amd_debug.installer import Installer


class TestInstaller(unittest.TestCase):
    """Test installer functions"""

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(filename="/dev/null", level=logging.DEBUG)

    def setUp(self):
        self.installer = Installer(tool_debug=False)

    @patch("builtins.print")
    @patch("shutil.copy", return_value=None)
    @patch("os.chmod", return_value=None)
    @patch("builtins.open")
    @patch("subprocess.call", return_value=0)
    def test_install_hook(
        self, _mock_call, _mock_open, _mock_chmod, _mock_shutil, _mock_print
    ):
        """Test install hook function"""
        self.installer.install()

    @patch("builtins.print")
    @patch("shutil.copy", return_value=None)
    @patch("os.chmod", return_value=None)
    @patch("builtins.open")
    @patch("subprocess.call", return_value=0)
    def test_install_hook_missing_path(
        self, _mock_call, _mock_open, _mock_chmod, _mock_shutil, _mock_print
    ):
        """Test install hook function, but some paths are missing"""
        with patch("os.path.exists", return_value=False):
            self.installer.install()

    @patch("builtins.print")
    @patch("os.remove", return_value=None)
    @patch("builtins.open")
    @patch("amd_debug.installer.get_distro", return_value="ubuntu")
    @patch("subprocess.call", return_value=0)
    def test_remove_hook(
        self, _mock_call, _mock_get_distro, _mock_open, _mock_remove, _mock_print
    ):
        """Test remove hook function"""
        with patch("os.path.exists", return_value=True):
            self.installer.remove()

    @patch("builtins.print")
    @patch("os.path.exists", return_value=False)
    @patch("subprocess.call", return_value=0)
    def test_remove_hook_missing_path(self, _mock_call, _mock_exists, _mock_print):
        """Test remove hook function when the file is missing"""
        self.installer.remove()

    @patch("builtins.print")
    @patch("subprocess.call", return_value=0)
    def test_already_installed_iasl(self, _mock_call, _mock_print):
        """Test that an already installed iasl is found"""
        self.installer.set_requirements("iasl")
        ret = self.installer.install_dependencies()
        self.assertTrue(ret)

    @patch("builtins.print")
    @patch("amd_debug.installer.get_distro", return_value="ubuntu")
    @patch("os.execvp", return_value=None)
    @patch("subprocess.check_call", return_value=0)
    @patch("subprocess.call", return_value=1)
    def test_install_iasl_ubuntu(
        self, _mock_call, _mock_check_call, _mock_distro, _fake_sudo, _mock_print
    ):
        """Test install requirements function"""
        self.installer.set_requirements("iasl")
        ret = self.installer.install_dependencies()
        _mock_check_call.assert_called_once_with(["apt", "install", "acpica-tools"])
        self.assertTrue(ret)

    @patch("builtins.print")
    @patch("amd_debug.installer.get_distro", return_value="fedora")
    @patch(
        "builtins.open", new_callable=mock_open, read_data="VARIANT_ID=workstation\n"
    )
    @patch("os.execvp", return_value=None)
    @patch("subprocess.check_call", return_value=0)
    @patch("subprocess.call", return_value=1)
    def test_install_iasl_fedora(
        self,
        _mock_call,
        _mock_check_call,
        _mock_variant,
        _mock_distro,
        _fake_sudo,
        _mock_print,
    ):
        """Test install requirements function"""
        self.installer.set_requirements("iasl")
        ret = self.installer.install_dependencies()
        _mock_check_call.assert_called_once_with(
            ["dnf", "install", "-y", "acpica-tools"]
        )
        self.assertTrue(ret)

    @patch("builtins.print")
    @patch("amd_debug.installer.get_distro", return_value="ubuntu")
    @patch("os.execvp", return_value=None)
    @patch("subprocess.check_call", return_value=0)
    @patch("subprocess.call", return_value=1)
    def test_install_ethtool_ubuntu(
        self, _mock_call, _mock_check_call, _mock_distro, _fake_sudo, _mock_print
    ):
        """Test install requirements function"""
        self.installer.set_requirements("ethtool")
        ret = self.installer.install_dependencies()
        _mock_check_call.assert_called_once_with(["apt", "install", "ethtool"])
        self.assertTrue(ret)

    @patch("builtins.print")
    @patch("amd_debug.installer.get_distro", return_value="fedora")
    @patch(
        "builtins.open", new_callable=mock_open, read_data="VARIANT_ID=workstation\n"
    )
    @patch("os.execvp", return_value=None)
    @patch("subprocess.check_call", return_value=0)
    @patch("subprocess.call", return_value=1)
    def test_install_ethtool_fedora(
        self,
        _mock_call,
        _mock_check_call,
        _mock_variant,
        _mock_distro,
        _fake_sudo,
        _mock_print,
    ):
        """Test install requirements function"""
        self.installer.set_requirements("ethtool")
        ret = self.installer.install_dependencies()
        _mock_check_call.assert_called_once_with(["dnf", "install", "-y", "ethtool"])
        self.assertTrue(ret)

    @patch("builtins.print")
    @patch("amd_debug.installer.get_distro", return_value="arch")
    @patch("os.execvp", return_value=None)
    @patch("subprocess.check_call", return_value=0)
    @patch("subprocess.call", return_value=1)
    def test_install_ethtool_arch(
        self,
        _mock_call,
        _mock_check_call,
        _mock_distro,
        _fake_sudo,
        _mock_print,
    ):
        """Test install requirements function"""
        self.installer.set_requirements("ethtool")
        ret = self.installer.install_dependencies()
        _mock_check_call.assert_called_once_with(["pacman", "-Sy", "ethtool"])
        self.assertTrue(ret)

    @patch("builtins.print")
    @patch("os.path.exists", return_value=False)
    @patch("os.execvp", return_value=None)
    @patch("amd_debug.installer.get_distro", return_value="gentoo")
    @patch("subprocess.call", return_value=1)
    def test_install_iasl_gentoo(
        self, _mock_call, _mock_distro, _fake_sudo, _mock_exists, _mock_print
    ):
        """Test install requirements function"""
        self.installer.set_requirements("iasl", "ethtool")
        ret = self.installer.install_dependencies()
        self.assertFalse(ret)

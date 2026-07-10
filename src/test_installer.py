#!/usr/bin/python3
# SPDX-License-Identifier: MIT

"""
This module contains unit tests for the installer functions in the amd-debug-tools package.
"""
from unittest.mock import patch, mock_open, MagicMock

import logging
import subprocess
import sys
import unittest

from amd_debug.installer import (
    Installer,
    DistroPackage,
    FwupdPackage,
    EdidDecodePackage,
    install_dep_superset,
    parse_args,
    show_install_message,
)


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
    @patch("os.makedirs", return_value=None)
    def test_install_hook(
        self,
        _mock_mkdir,
        _mock_call,
        _mock_open,
        _mock_chmod,
        _mock_shutil,
        _mock_print,
    ):
        """Test install hook function"""
        self.installer.install()

    @patch("builtins.print")
    @patch("shutil.copy", return_value=None)
    @patch("os.chmod", return_value=None)
    @patch("builtins.open")
    @patch("subprocess.call", return_value=0)
    @patch("os.makedirs", return_value=None)
    def test_install_hook_missing_path(
        self,
        _mock_mkdir,
        _mock_call,
        _mock_open,
        _mock_chmod,
        _mock_shutil,
        _mock_print,
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
    @patch("amd_debug.installer.get_distro", return_value="fedora")
    @patch("builtins.open", new_callable=mock_open, read_data="VARIANT_ID=kde\n")
    @patch("os.execvp", return_value=None)
    @patch("subprocess.check_call", return_value=0)
    @patch("subprocess.call", return_value=1)
    def test_install_iasl_fedora_kde(
        self,
        _mock_call,
        _mock_check_call,
        _mock_variant,
        _mock_distro,
        _fake_sudo,
        _mock_print,
    ):
        """Test install requirements function on Fedora KDE"""
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
    @patch("amd_debug.installer.get_distro", return_value="fedora")
    @patch("builtins.open", new_callable=mock_open, read_data="VARIANT_ID=kde\n")
    @patch("os.execvp", return_value=None)
    @patch("subprocess.check_call", return_value=0)
    @patch("subprocess.call", return_value=1)
    def test_install_ethtool_fedora_kde(
        self,
        _mock_call,
        _mock_check_call,
        _mock_variant,
        _mock_distro,
        _fake_sudo,
        _mock_print,
    ):
        """Test install requirements function on Fedora KDE"""
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
        self.assertTrue(ret)

    @patch("builtins.print")
    @patch("amd_debug.installer.get_distro", return_value="ubuntu")
    @patch("os.execvp", return_value=None)
    @patch("subprocess.check_call", return_value=0)
    @patch("subprocess.call", return_value=1)
    def test_install_edid_decode_ubuntu(
        self, _mock_call, _mock_check_call, _mock_distro, _fake_sudo, _mock_print
    ):
        """Test install requirements function for edid-decode on Ubuntu"""
        self.installer.set_requirements("edid-decode")
        ret = self.installer.install_dependencies()
        _mock_check_call.assert_called_once_with(
            ["apt", "install", "libdisplay-info-bin"]
        )
        self.assertTrue(ret)

    @patch("builtins.print")
    @patch("amd_debug.installer.get_distro", return_value="fedora")
    @patch(
        "builtins.open", new_callable=mock_open, read_data="VARIANT_ID=workstation\n"
    )
    @patch("os.execvp", return_value=None)
    @patch("subprocess.check_call", return_value=0)
    @patch("subprocess.call", return_value=1)
    def test_install_edid_decode_fedora(
        self,
        _mock_call,
        _mock_check_call,
        _mock_variant,
        _mock_distro,
        _fake_sudo,
        _mock_print,
    ):
        """Test install requirements function for edid-decode on Fedora"""
        self.installer.set_requirements("edid-decode")
        ret = self.installer.install_dependencies()
        _mock_check_call.assert_called_once_with(
            ["dnf", "install", "-y", "libdisplay-info-tools"]
        )
        self.assertTrue(ret)

    @patch("builtins.print")
    @patch("amd_debug.installer.get_distro", return_value="fedora")
    @patch("builtins.open", new_callable=mock_open, read_data="VARIANT_ID=kde\n")
    @patch("os.execvp", return_value=None)
    @patch("subprocess.check_call", return_value=0)
    @patch("subprocess.call", return_value=1)
    def test_install_edid_decode_fedora_kde(
        self,
        _mock_call,
        _mock_check_call,
        _mock_variant,
        _mock_distro,
        _fake_sudo,
        _mock_print,
    ):
        """Test install requirements function for edid-decode on Fedora KDE"""
        self.installer.set_requirements("edid-decode")
        ret = self.installer.install_dependencies()
        _mock_check_call.assert_called_once_with(
            ["dnf", "install", "-y", "libdisplay-info-tools"]
        )
        self.assertTrue(ret)

    @patch("builtins.print")
    @patch("amd_debug.installer.get_distro", return_value="arch")
    @patch("os.execvp", return_value=None)
    @patch("subprocess.check_call", return_value=0)
    @patch("subprocess.call", return_value=1)
    def test_install_edid_decode_arch(
        self,
        _mock_call,
        _mock_check_call,
        _mock_distro,
        _fake_sudo,
        _mock_print,
    ):
        """Test install requirements function for edid-decode on Arch"""
        self.installer.set_requirements("edid-decode")
        ret = self.installer.install_dependencies()
        _mock_check_call.assert_called_once_with(["pacman", "-Sy", "libdisplay-info"])
        self.assertTrue(ret)

    @patch("builtins.print")
    @patch("os.path.exists", return_value=False)
    @patch("os.execvp", return_value=None)
    @patch("amd_debug.installer.get_distro", return_value="gentoo")
    @patch("subprocess.call", return_value=1)
    def test_install_edid_decode_gentoo(
        self, _mock_call, _mock_distro, _fake_sudo, _mock_exists, _mock_print
    ):
        """Test install requirements function for edid-decode on unsupported distro"""
        self.installer.set_requirements("edid-decode")
        ret = self.installer.install_dependencies()
        self.assertTrue(ret)

    @patch("builtins.print")
    @patch("os.path.exists", return_value=False)
    @patch("os.execvp", return_value=None)
    @patch("amd_debug.installer.get_distro", return_value="gentoo")
    @patch("subprocess.call", return_value=255)
    def test_install_edid_decode_present(
        self, _mock_call, _mock_distro, _fake_sudo, _mock_exists, _mock_print
    ):
        """Test install requirements function for edid-decode on unsupported distro"""
        self.installer.set_requirements("edid-decode")
        ret = self.installer.install_dependencies()
        self.assertTrue(ret)

    @patch("builtins.print")
    @patch("subprocess.call", side_effect=FileNotFoundError())
    @patch("amd_debug.installer.get_distro", return_value="gentoo")
    @patch("os.path.exists", return_value=False)
    @patch("os.execvp", return_value=None)
    def test_install_iasl_missing_filenotfound(
        self, _execvp, _exists, _distro, _call, _print
    ):
        """When iasl binary is missing entirely (FileNotFoundError) installer still tries"""
        self.installer.set_requirements("iasl")
        self.assertTrue(self.installer.install_dependencies())

    @patch("builtins.print")
    @patch("subprocess.call", side_effect=FileNotFoundError())
    @patch("amd_debug.installer.get_distro", return_value="gentoo")
    @patch("os.path.exists", return_value=False)
    @patch("os.execvp", return_value=None)
    def test_install_ethtool_missing_filenotfound(
        self, _execvp, _exists, _distro, _call, _print
    ):
        """When ethtool binary is missing (FileNotFoundError) installer still tries"""
        self.installer.set_requirements("ethtool")
        self.assertTrue(self.installer.install_dependencies())

    @patch("builtins.print")
    @patch("subprocess.call", side_effect=FileNotFoundError())
    @patch("amd_debug.installer.get_distro", return_value="gentoo")
    @patch("os.path.exists", return_value=False)
    @patch("os.execvp", return_value=None)
    def test_install_edid_decode_both_missing(
        self, _execvp, _exists, _distro, _call, _print
    ):
        """Both di-edid-decode and edid-decode missing; falls into install path"""
        self.installer.set_requirements("edid-decode")
        self.assertTrue(self.installer.install_dependencies())

    @patch("builtins.print")
    @patch("os.execvp", return_value=None)
    def test_install_pyudev_present(self, _execvp, _print):
        """pyudev already importable; no install needed"""
        self.installer.set_requirements("pyudev")
        self.assertTrue(self.installer.install_dependencies())

    @patch("builtins.print")
    @patch("os.execvp", return_value=None)
    def test_install_packaging_present(self, _execvp, _print):
        """packaging already importable"""
        self.installer.set_requirements("packaging")
        self.assertTrue(self.installer.install_dependencies())

    @patch("builtins.print")
    @patch("os.execvp", return_value=None)
    def test_install_pandas_present(self, _execvp, _print):
        """pandas already importable"""
        self.installer.set_requirements("pandas")
        self.assertTrue(self.installer.install_dependencies())

    @patch("builtins.print")
    @patch("os.execvp", return_value=None)
    def test_install_tabulate_present(self, _execvp, _print):
        """tabulate already importable"""
        self.installer.set_requirements("tabulate")
        self.assertTrue(self.installer.install_dependencies())

    @patch("builtins.print")
    @patch("os.execvp", return_value=None)
    def test_install_jinja2_present(self, _execvp, _print):
        """jinja2 already importable"""
        self.installer.set_requirements("jinja2")
        self.assertTrue(self.installer.install_dependencies())

    @patch("builtins.print")
    @patch("os.execvp", return_value=None)
    def test_install_seaborn_present(self, _execvp, _print):
        """seaborn already importable"""
        self.installer.set_requirements("seaborn")
        self.assertTrue(self.installer.install_dependencies())

    @patch("amd_debug.installer.print_color")
    @patch("amd_debug.installer.get_distro", return_value="ubuntu")
    @patch("amd_debug.installer.relaunch_sudo")
    def test_distro_package_no_deb_returns_false(
        self, _sudo, _distro, _print
    ):
        """Ubuntu install path returns False when deb name is missing"""
        pkg = DistroPackage(deb=None, rpm="x", arch="x", message="msg")
        self.assertFalse(pkg.install())

    @patch("amd_debug.installer.print_color")
    @patch("amd_debug.installer.read_file", return_value="VARIANT_ID=workstation\n")
    @patch("amd_debug.installer.get_distro", return_value="fedora")
    @patch("amd_debug.installer.relaunch_sudo")
    def test_distro_package_no_rpm_returns_false(
        self, _sudo, _distro, _read, _print
    ):
        """Fedora install path returns False when rpm name is missing"""
        pkg = DistroPackage(deb="x", rpm=None, arch="x", message="msg")
        self.assertFalse(pkg.install())

    @patch("amd_debug.installer.print_color")
    @patch("amd_debug.installer.read_file", return_value="VARIANT_ID=server\n")
    @patch("amd_debug.installer.get_distro", return_value="fedora")
    @patch("amd_debug.installer.relaunch_sudo")
    def test_distro_package_fedora_wrong_variant(
        self, _sudo, _distro, _read, _print
    ):
        """Fedora install path returns False when variant isn't workstation/kde"""
        pkg = DistroPackage(deb="x", rpm="x", arch="x", message="msg")
        self.assertFalse(pkg.install())

    @patch("amd_debug.installer.print_color")
    @patch("amd_debug.installer.get_distro", return_value="arch")
    @patch("amd_debug.installer.relaunch_sudo")
    def test_distro_package_no_arch_returns_false(self, _sudo, _distro, _print):
        """Arch install path returns False when arch name is missing"""
        pkg = DistroPackage(deb="x", rpm="x", arch=None, message="msg")
        self.assertFalse(pkg.install())

    @patch("amd_debug.installer.print_color")
    @patch("amd_debug.installer.fatal_error")
    @patch(
        "amd_debug.installer.subprocess.check_call",
        side_effect=subprocess.CalledProcessError(1, "apt"),
    )
    @patch("amd_debug.installer.get_distro", return_value="ubuntu")
    @patch("amd_debug.installer.relaunch_sudo")
    def test_distro_package_install_failure_calls_fatal(
        self, _sudo, _distro, _call, mock_fatal, _print
    ):
        """check_call failure triggers fatal_error"""
        pkg = DistroPackage(deb="x", rpm="x", arch="x", message="msg")
        self.assertTrue(pkg.install())
        mock_fatal.assert_called_once()

    def test_show_install_message(self):
        """show_install_message formats and prints"""
        with patch("amd_debug.installer.print_color") as mock_pc:
            show_install_message("Thing missing")
            mock_pc.assert_called_once()
            self.assertIn("Thing missing", mock_pc.call_args[0][0])
            self.assertIn("Attempting to install", mock_pc.call_args[0][0])

    def test_parse_args_tool_debug(self):
        """parse_args parses --tool-debug"""
        with patch("sys.argv", ["installer", "--tool-debug"]):
            args = parse_args()
        self.assertTrue(args.tool_debug)

    @patch("amd_debug.installer.show_log_info")
    @patch("amd_debug.installer.Installer")
    @patch("amd_debug.installer.parse_args")
    def test_install_dep_superset_success(
        self, mock_parse, mock_installer_cls, _mock_show
    ):
        """install_dep_superset returns None on success"""
        mock_parse.return_value = MagicMock(tool_debug=False)
        mock_tool = MagicMock()
        mock_tool.install_dependencies.return_value = True
        mock_installer_cls.return_value = mock_tool
        self.assertIsNone(install_dep_superset())
        mock_tool.set_requirements.assert_called_once()

    @patch("amd_debug.installer.show_log_info")
    @patch("amd_debug.installer.Installer")
    @patch("amd_debug.installer.parse_args")
    def test_install_dep_superset_failure(
        self, mock_parse, mock_installer_cls, _mock_show
    ):
        """install_dep_superset returns 1 when dependencies fail to install"""
        mock_parse.return_value = MagicMock(tool_debug=False)
        mock_tool = MagicMock()
        mock_tool.install_dependencies.return_value = False
        mock_installer_cls.return_value = mock_tool
        self.assertEqual(install_dep_superset(), 1)

    def test_installer_fwupd_import_error(self):
        """Installer sets fwupd=False when gi.repository.Fwupd import fails"""
        # Simulate ImportError when importing gi by removing/setting None
        with patch.dict(sys.modules, {"gi": None}):
            tool = Installer(tool_debug=False)
            self.assertFalse(tool.fwupd)

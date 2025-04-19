#!/usr/bin/python3
# SPDX-License-Identifier: MIT

import os
import subprocess
from amd_debug.common import print_color, get_distro, read_file, systemd_in_use

# test if pip can be used to install anything
try:
    import pip as _

    PIP = True
except ModuleNotFoundError:
    PIP = False

# used for various version comparison
try:
    from packaging import version as _

    VERSION = True
except ModuleNotFoundError:
    VERSION = False


class Headers:  # pylint: disable=too-few-public-methods
    """Headers for the script"""

    MissingPyudev = "Udev access library `pyudev` is missing"
    MissingPackaging = "Python library `packaging` is missing"
    MissingIasl = "ACPI extraction tool `iasl` is missing"
    MissingJournald = "Python systemd/journald module is missing"
    MissingPandas = "Data library `pandas` is missing"
    MissingTabulate = "Data library `tabulate` is missing"
    MissingEthtool = "Ethtool is missing"
    InstallAction = "Attempting to install"


class DistroPackage:
    """Base class for distro packages"""

    def __init__(self, deb, rpm, arch, pip):
        self.deb = deb
        self.rpm = rpm
        self.arch = arch
        self.pip = pip

    def install(self):
        """Install the package for a given distro"""
        dist = get_distro()
        if dist in ("ubuntu", "debian"):
            if not self.deb:
                return False
            installer = ["apt", "install", self.deb]
        elif dist == "fedora":
            if not self.rpm:
                return False
            release = read_file("/usr/lib/os-release")
            variant = None
            for line in release.split("\n"):
                if line.startswith("VARIANT_ID"):
                    variant = line.split("=")[-1]
            if variant != "workstation":
                return False
            installer = ["dnf", "install", "-y", self.rpm]
        elif dist == "arch" or os.path.exists("/etc/arch-release"):
            if not self.arch:
                return False
            installer = ["pacman", "-Sy", self.arch]
        else:
            if not PIP or not self.pip:
                return False
            installer = ["python3", "-m", "pip", "install", "--upgrade", self.pip]

        subprocess.check_call(installer)
        return True


class PyUdevPackage(DistroPackage):
    """Pyudev package"""

    def __init__(self):
        super().__init__(
            deb="python3-pyudev",
            rpm="python3-pyudev",
            arch="python-pyudev",
            pip="pyudev",
        )


class IaslPackage(DistroPackage):
    """Iasl package"""

    def __init__(
        self,
    ):
        super().__init__(
            deb="acpica-tools", rpm="acpica-tools", arch="acpica", pip=None
        )


class PackagingPackage(DistroPackage):
    """Packaging package"""

    def __init__(self):
        super().__init__(
            deb="python3-packaging",
            rpm=None,
            arch="python-packaging",
            pip="python3-setuptools",
        )


class JournaldPackage(DistroPackage):
    """Journald package"""

    def __init__(self):
        super().__init__(
            deb="python3-systemd",
            rpm="python3-pyudev",
            arch="python-systemd",
            pip=None,
        )


class EthtoolPackage(DistroPackage):
    """Ethtool package"""

    def __init__(self):
        super().__init__(
            deb="ethtool",
            rpm="ethtool",
            arch="ethtool",
            pip=None,
        )


class PandasPackage(DistroPackage):
    """Class for handling the pandas package"""

    def __init__(self):
        super().__init__(
            deb="python3-pandas",
            rpm="python3-pandas",
            arch="python-pandas",
            pip="pandas",
        )


class TabulatePackage(DistroPackage):
    """Class for handling the tabulate package"""

    def __init__(self):
        super().__init__(
            deb="python3-tabulate",
            rpm="python3-tabulate",
            arch="python-tabulate",
            pip="tabulate",
        )


class Installer:
    """Installer class"""

    def show_install_message(self, message):
        """Show an install message"""
        action = Headers.InstallAction
        message = f"{message}. {action}."
        print_color(message, "👀")

    def __init__(self, base=""):
        self.base = base
        self.systemd = systemd_in_use()
        self.systemd_path = os.path.join(
            self.base, "/", "lib", "systemd", "system-sleep"
        )

        # for fetching acpi tables
        try:
            self.iasl = subprocess.call(["iasl", "-v"], stdout=subprocess.DEVNULL) == 0
        except subprocess.CalledProcessError:
            self.iasl = False
        except FileNotFoundError:
            self.iasl = False

        # for analyzing devices
        try:
            from pyudev import Context  # pylint: disable=import-outside-toplevel

            self.pyudev = Context()
        except ModuleNotFoundError:
            self.pyudev = False

        # for checking WoL
        try:
            _ = subprocess.call(["ethtool", "-h"], stdout=subprocess.DEVNULL) == 0
            self.ethtool = True
        except FileNotFoundError:
            self.ethtool = False

        # add checks for cysystemd
        try:
            from cysystemd.reader import (
                JournalReader as _,
            )  # pylint: disable=import-outside-toplevel

            self.journald = True
        except ModuleNotFoundError:
            self.journald = False

        # add checks for python-systemd
        if not self.journald:
            try:
                from systemd import (
                    journal as _,
                )  # pylint: disable=import-outside-toplevel

                self.journald = True
            except ModuleNotFoundError:
                self.journald = False
        self.requirements = []

        # for checking for pandas
        try:
            from pandas import DataFrame as _  # pylint: disable=import-outside-toplevel

            self.pandas = True
        except ModuleNotFoundError:
            self.pandas = False
        except ImportError:
            self.pandas = False

        # for checking for tabulate
        try:
            from tabulate import (
                tabulate as _,
            )  # pylint: disable=import-outside-toplevel

            self.tabulate = True
        except ModuleNotFoundError:
            self.tabulate = False

    def set_requirements(self, *args):
        """Set the requirements for the installer"""
        self.requirements = args

    def install_dependencies(self) -> bool:
        """Install the dependencies"""
        if "iasl" in self.requirements and not self.iasl:
            self.show_install_message(Headers.MissingIasl)
            package = IaslPackage()
            if not package.install():
                return False
        if "pyudev" in self.requirements and not self.pyudev:
            self.show_install_message(Headers.MissingPyudev)
            package = PyUdevPackage()
            if not package.install():
                return False
        if "packaging" in self.requirements and not VERSION:
            self.show_install_message(Headers.MissingPackaging)
            package = PackagingPackage()
            if not package.install():
                return False
        if "ethtool" in self.requirements and not self.ethtool:
            self.show_install_message(Headers.MissingEthtool)
            package = EthtoolPackage()
            if not package.install():
                return False
        if "journald" in self.requirements and not self.journald:
            self.show_install_message(Headers.MissingJournald)
            package = JournaldPackage()
            if not package.install():
                return False
        if "pandas" in self.requirements and not self.pandas:
            self.show_install_message(Headers.MissingPandas)
            package = PandasPackage()
            if not package.install():
                return False
        if "tabulate" in self.requirements and not self.tabulate:
            self.show_install_message(Headers.MissingTabulate)
            package = TabulatePackage()
            if not package.install():
                return False

        return True

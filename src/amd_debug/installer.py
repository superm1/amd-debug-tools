#!/usr/bin/python3
# SPDX-License-Identifier: MIT

import argparse
import os
import shutil
import subprocess
from amd_debug.common import (
    print_color,
    get_distro,
    read_file,
    systemd_in_use,
    show_log_info,
    fatal_error,
    relaunch_sudo,
    AmdTool,
)


class Headers:  # pylint: disable=too-few-public-methods
    """Headers for the script"""

    MissingIasl = "ACPI extraction tool `iasl` is missing"
    MissingEthtool = "Ethtool is missing"
    InstallAction = "Attempting to install"
    MissingFwupd = "Firmware update library `fwupd` is missing"
    MissingPyudev = "Udev access library `pyudev` is missing"
    MissingPackaging = "Python library `packaging` is missing"
    MissingPandas = "Data library `pandas` is missing"
    MissingTabulate = "Data library `tabulate` is missing"
    MissingJinja2 = "Template library `jinja2` is missing"
    MissingSeaborn = "Data visualization library `seaborn` is missing"


class DistroPackage:
    """Base class for distro packages"""

    def __init__(self, deb, rpm, arch, message):
        self.deb = deb
        self.rpm = rpm
        self.arch = arch
        self.message = message

    def install(self):
        """Install the package for a given distro"""
        relaunch_sudo()
        show_install_message(self.message)
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
            return False

        try:
            subprocess.check_call(installer)
        except subprocess.CalledProcessError as e:
            fatal_error(e)
        return True


class PyUdevPackage(DistroPackage):
    """Pyudev package"""

    def __init__(self):
        super().__init__(
            deb="python3-pyudev",
            rpm="python3-pyudev",
            arch="python-pyudev",
            message=Headers.MissingPyudev,
        )


class PackagingPackage(DistroPackage):
    """Packaging package"""

    def __init__(self):
        super().__init__(
            deb="python3-packaging",
            rpm=None,
            arch="python-packaging",
            message=Headers.MissingPackaging,
        )


class PandasPackage(DistroPackage):
    """Class for handling the pandas package"""

    def __init__(self):
        super().__init__(
            deb="python3-pandas",
            rpm="python3-pandas",
            arch="python-pandas",
            message=Headers.MissingPandas,
        )


class TabulatePackage(DistroPackage):
    """Class for handling the tabulate package"""

    def __init__(self):
        super().__init__(
            deb="python3-tabulate",
            rpm="python3-tabulate",
            arch="python-tabulate",
            message=Headers.MissingTabulate,
        )


class Jinja2Package(DistroPackage):
    """Class for handling the jinja2 package"""

    def __init__(self):
        super().__init__(
            deb="python3-jinja2",
            rpm="python3-jinja2",
            arch="python-jinja",
            message=Headers.MissingJinja2,
        )


class SeabornPackage(DistroPackage):
    """Class for handling the seaborn package"""

    def __init__(self):
        super().__init__(
            deb="python3-seaborn",
            rpm="python3-seaborn",
            arch="python-seaborn",
            message=Headers.MissingSeaborn,
        )


class IaslPackage(DistroPackage):
    """Iasl package"""

    def __init__(self):
        super().__init__(
            deb="acpica-tools",
            rpm="acpica-tools",
            arch="acpica",
            message=Headers.MissingIasl,
        )


class EthtoolPackage(DistroPackage):
    """Ethtool package"""

    def __init__(self):
        super().__init__(
            deb="ethtool",
            rpm="ethtool",
            arch="ethtool",
            message=Headers.MissingEthtool,
        )


class FwupdPackage(DistroPackage):
    """Fwupd package"""

    def __init__(self):
        super().__init__(
            deb="gir1.2-fwupd-2.0",
            rpm=None,
            arch=None,
            message=Headers.MissingFwupd,
        )


def show_install_message(message):
    """Show an install message"""
    action = Headers.InstallAction
    message = f"{message}. {action}."
    print_color(message, "👀")


class Installer(AmdTool):
    """Installer class"""

    def __init__(self, tool_debug):
        log_prefix = "installer" if tool_debug else None
        super().__init__(log_prefix)
        self.systemd = systemd_in_use()
        self.systemd_path = os.path.join("/", "lib", "systemd", "system-sleep")

        # test if fwupd can report device firmware versions
        try:
            import gi  # pylint: disable=import-outside-toplevel
            from gi.repository import (
                GLib as _,
            )  # pylint: disable=import-outside-toplevel

            gi.require_version("Fwupd", "2.0")
            from gi.repository import (
                Fwupd as _,
            )  # pylint: disable=import-outside-toplevel

            self.fwupd = True
        except ImportError:
            self.fwupd = False
        except ValueError:
            self.fwupd = False
        self.requirements = []

    def set_requirements(self, *args):
        """Set the requirements for the installer"""
        self.requirements = args

    def install_dependencies(self) -> bool:
        """Install the dependencies"""
        if "iasl" in self.requirements:
            try:
                iasl = subprocess.call(["iasl", "-v"], stdout=subprocess.DEVNULL) == 0
            except FileNotFoundError:
                iasl = False
            if not iasl:
                package = IaslPackage()
                if not package.install():
                    return False
        if "ethtool" in self.requirements:
            try:
                ethtool = (
                    subprocess.call(["ethtool", "-h"], stdout=subprocess.DEVNULL) == 0
                )
            except FileNotFoundError:
                ethtool = False
            if not ethtool:
                package = EthtoolPackage()
                if not package.install():
                    return False
        if "fwupd" in self.requirements and not self.fwupd:
            package = FwupdPackage()
            if not package.install():
                return False
        if "pyudev" in self.requirements:
            try:
                import pyudev as _  # pylint: disable=import-outside-toplevel
            except ModuleNotFoundError:
                package = PyUdevPackage()
                if not package.install():
                    return False
        if "packaging" in self.requirements:
            try:
                import packaging as _  # pylint: disable=import-outside-toplevel
            except ModuleNotFoundError:
                package = PackagingPackage()
                if not package.install():
                    return False
        if "pandas" in self.requirements:
            try:
                import pandas as _  # pylint: disable=import-outside-toplevel
            except ModuleNotFoundError:
                package = PandasPackage()
                if not package.install():
                    return False
        if "tabulate" in self.requirements:
            try:
                import tabulate as _  # pylint: disable=import-outside-toplevel
            except ModuleNotFoundError:
                package = TabulatePackage()
                if not package.install():
                    return False
        if "jinja2" in self.requirements:
            try:
                import jinja2 as _  # pylint: disable=import-outside-toplevel
            except ModuleNotFoundError:
                package = Jinja2Package()
                if not package.install():
                    return False
        if "seaborn" in self.requirements:
            try:
                import seaborn as _  # pylint: disable=import-outside-toplevel
            except ModuleNotFoundError:
                package = SeabornPackage()
                if not package.install():
                    return False

        return True

    def _check_systemd(self) -> bool:
        """Check if the systemd path exists"""
        if not os.path.exists(self.systemd_path):
            print_color(
                f"Systemd path does not exist: {self.systemd_path}",
                "❌",
            )
        return os.path.exists(self.systemd_path)

    def remove(self) -> bool:
        """Remove the amd-s2idle hook"""
        if self._check_systemd():
            f = "s2idle-hook"
            t = os.path.join(self.systemd_path, f)
            os.remove(t)
            print_color(
                f"Removed {f} from {self.systemd_path}",
                "✅",
            )
        else:
            print_color("Systemd path does not exist, not removing hook", "🚦")
        f = "amd-s2idle"
        d = os.path.join(
            "/",
            "usr",
            "local",
            "share",
            "bash-completion",
            "completions",
        )
        t = os.path.join(d, f)
        if os.path.exists(t):
            os.remove(t)
            print_color(f"Removed {f} from {d}", "✅")
        return True

    def install(self) -> bool:
        """Install the amd-s2idle hook"""
        import amd_debug  # pylint: disable=import-outside-toplevel

        d = os.path.dirname(amd_debug.__file__)
        if self._check_systemd():
            f = "s2idle-hook"
            s = os.path.join(d, f)
            t = os.path.join(self.systemd_path, f)
            with open(s, "r", encoding="utf-8") as r:
                with open(t, "w", encoding="utf-8") as w:
                    for line in r.readlines():
                        if 'parser.add_argument("--path"' in line:
                            line = line.replace(
                                'default=""',
                                f"default=\"{os.path.join(d, '..')}\"",
                            )
                        w.write(line)
            os.chmod(t, 0o755)
            print_color(
                f"Installed {f} to {self.systemd_path}",
                "✅",
            )
        else:
            print_color("Systemd path does not exist, not installing hook", "🚦")
        f = "amd-s2idle"
        s = os.path.join(d, "bash", f)
        t = os.path.join(
            "/",
            "usr",
            "local",
            "share",
            "bash-completion",
            "completions",
        )
        os.makedirs(t, exist_ok=True)
        shutil.copy(s, t)
        print_color(f"Installed {f} to {t}", "✅")
        return True


def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Install dependencies for AMD debug tools",
    )
    parser.add_argument(
        "--tool-debug",
        action="store_true",
        help="Enable tool debug logging",
    )
    return parser.parse_args()


def install_dep_superset() -> bool:
    """Install all python supserset dependencies"""
    args = parse_args()
    tool = Installer(tool_debug=args.tool_debug)
    tool.set_requirements(
        "iasl",
        "ethtool",
        "jinja2",
        "pyudev",
        "packaging",
        "pandas",
        "seaborn",
        "tabulate",
    )
    ret = tool.install_dependencies()
    if ret:
        print_color("All dependencies installed", "✅")
    show_log_info()
    return ret

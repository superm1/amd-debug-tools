#!/usr/bin/python3
# SPDX-License-Identifier: MIT

import os
import shutil
import subprocess
from amd_debug.common import (
    print_color,
    get_distro,
    read_file,
    systemd_in_use,
    fatal_error,
    relaunch_sudo,
)


class Headers:  # pylint: disable=too-few-public-methods
    """Headers for the script"""

    MissingIasl = "ACPI extraction tool `iasl` is missing"
    MissingEthtool = "Ethtool is missing"
    InstallAction = "Attempting to install"
    MissingFwupd = "Firmware update library `fwupd` is missing"


class DistroPackage:
    """Base class for distro packages"""

    def __init__(self, deb, rpm, arch):
        self.deb = deb
        self.rpm = rpm
        self.arch = arch

    def install(self):
        """Install the package for a given distro"""
        relaunch_sudo()
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


class IaslPackage(DistroPackage):
    """Iasl package"""

    def __init__(
        self,
    ):
        super().__init__(deb="acpica-tools", rpm="acpica-tools", arch="acpica")


class EthtoolPackage(DistroPackage):
    """Ethtool package"""

    def __init__(self):
        super().__init__(
            deb="ethtool",
            rpm="ethtool",
            arch="ethtool",
        )


class FwupdPackage(DistroPackage):
    """Fwupd package"""

    def __init__(self):
        super().__init__(
            deb="gir1.2-fwupd-2.0",
            rpm=None,
            arch=None,
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

        # for checking WoL
        try:
            _ = subprocess.call(["ethtool", "-h"], stdout=subprocess.DEVNULL) == 0
            self.ethtool = True
        except FileNotFoundError:
            self.ethtool = False

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
        if "iasl" in self.requirements and not self.iasl:
            self.show_install_message(Headers.MissingIasl)
            package = IaslPackage()
            if not package.install():
                return False
        if "ethtool" in self.requirements and not self.ethtool:
            self.show_install_message(Headers.MissingEthtool)
            package = EthtoolPackage()
            if not package.install():
                return False
        if "fwupd" in self.requirements and not self.fwupd:
            self.show_install_message(Headers.MissingFwupd)
            package = FwupdPackage()
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
        f = "amd-s2icle"
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
            with open(s, "r") as r:
                with open(t, "w") as w:
                    for line in r.readlines():
                        line = line.replace("%PATH%", os.path.join(d, ".."))
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

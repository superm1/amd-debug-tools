#!/usr/bin/python3
# SPDX-License-Identifier: MIT
"""S0i3/s2idle analysis script for AMD systems"""
import argparse
import configparser
import glob
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import struct
from datetime import datetime, timedelta, date

# test if dbus is available for logind use
try:
    import dbus

    DBUS = True
except ModuleNotFoundError:
    DBUS = False
except ImportError:
    DBUS = False

# test if pip can be used to install anything
try:
    import pip as _

    PIP = True
except ModuleNotFoundError:
    PIP = False

# test if fwupd can report device firmware versions
try:
    import gi
    from gi.repository import GLib as _

    gi.require_version("Fwupd", "2.0")
    from gi.repository import Fwupd  # pylint: disable=unused-import

    FWUPD = True
except ImportError:
    FWUPD = False
except ValueError:
    FWUPD = False

# used to capture linux firmware versions
try:
    import apt
    import gzip

    APT = True
except ModuleNotFoundError:
    APT = False

# used for various version comparison
try:
    from packaging import version

    VERSION = True
except ModuleNotFoundError:
    VERSION = False

# used to identify the distro
try:
    import distro

    DISTRO = True
except ModuleNotFoundError:
    DISTRO = False


class Colors:
    """Colors for terminal output"""

    DEBUG = "\033[90m"
    HEADER = "\033[95m"
    OK = "\033[94m"
    WARNING = "\033[32m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"
    UNDERLINE = "\033[4m"


class Defaults:
    """Default values for the script"""

    duration = 10
    wait = 4
    count = 1
    log_prefix = "s2idle_report"
    log_suffix = "txt"


class Headers:
    """Headers for the script"""

    Info = "Debugging script for s2idle on AMD systems"
    Prerequisites = "Checking prerequisites for s2idle"
    BrokenPrerequisites = "Your system does not meet s2idle prerequisites!"
    SuspendDuration = "Suspend timer programmed for"
    LastCycleResults = "Results from last s2idle cycle"
    CycleCount = "Suspend cycle"
    RootError = "Suspend must be initiated by root user"
    NvmeSimpleSuspend = "platform quirk: setting simple suspend"
    WokeFromIrq = "Woke up from IRQ"
    WakeTriggeredIrq = "Wakeup triggered from IRQ"
    MissingFwupd = "Firmware update library `fwupd` is missing"
    MissingPyudev = "Udev access library `pyudev` is missing"
    MissingPackaging = "Python library `packaging` is missing"
    MissingIasl = "ACPI extraction tool `iasl` is missing"
    MissingJournald = "Python systemd/journald module is missing"
    MissingEthtool = "Ethtool is missing"
    Irq1Workaround = "Disabling IRQ1 wakeup source to avoid platform firmware bug"
    DurationDescription = "How long should suspend cycles last in seconds"
    WaitDescription = "How long to wait in between suspend cycles in seconds"
    CountDescription = "How many suspend cycles to run"
    LogDescription = "Location of log file"
    InstallAction = "Attempting to install"
    RerunAction = "Running this script as root will attempt to install it"
    ExplanationReport = "Explanations for your system"
    EcDebugging = "Turn on dynamic debug messages for EC during suspend"
    RogAllyMcuOld = "ROG Ally MCU firmware too old"
    RogAllyPowerSave = "Rog Ally doesn't have MCU powersave enabled"


def BIT(num):  # pylint=disable=invalid-name
    """Returns a bit shifted by num"""
    return 1 << num


def read_file(fn):
    """Reads and returns the contents of fn"""
    with open(fn, "r") as r:
        return r.read().strip()


def capture_file_to_debug(fn):
    """Reads and captures all contents of fn"""
    try:
        contents = read_file(fn)
        for line in contents.split("\n"):
            logging.debug(line.rstrip())
        return contents
    except PermissionError:
        logging.debug("Unable to capture %s", fn)
        return None


def get_property_pyudev(properties, key, fallback=""):
    """Get a property from a udev device"""
    try:
        return properties.get(key, fallback)
    except UnicodeDecodeError:
        return ""


def print_color(message, group):
    """Prints a message with a color"""
    prefix = f"{group} "
    suffix = Colors.ENDC
    if group == "🚦":
        color = Colors.WARNING
    elif group == "🦟":
        color = Colors.DEBUG
    elif any(mk in group for mk in ["❌", "👀", "🌡️"]):
        color = Colors.FAIL
    elif any(mk in group for mk in ["✅", "🔋", "🐧", "💻", "○", "💤", "🥱"]):
        color = Colors.OK
    else:
        color = group
        prefix = ""

    log_txt = f"{prefix}{message}".strip()
    if any(c in color for c in [Colors.OK, Colors.HEADER, Colors.UNDERLINE]):
        logging.info(log_txt)
    elif color == Colors.WARNING:
        logging.warning(log_txt)
    elif color == Colors.FAIL:
        logging.error(log_txt)
    else:
        logging.debug(log_txt)

    if "TERM" in os.environ and os.environ["TERM"] == "dumb":
        suffix = ""
        color = ""
    print(f"{prefix}{color}{message}{suffix}")


def fatal_error(message):
    """Prints a fatal error message and exits"""
    print_color(message, "👀")
    sys.exit(1)


def pm_debugging(func):
    """Turn on pm_debug_messages for the duration of the function"""

    def runner(*args, **kwargs):
        # enable PM debugging
        pm_debug_messages = os.path.join("/", "sys", "power", "pm_debug_messages")
        with open(pm_debug_messages, "w", encoding="utf-8") as w:
            w.write("1")

        # enable ACPI debugging
        old_debug_level = None
        old_debug_layer = None
        old_trace_state = None
        acpi_base = os.path.join("/", "sys", "module", "acpi")
        acpi_debug_layer = os.path.join(acpi_base, "parameters", "trace_debug_layer")
        acpi_debug_level = os.path.join(acpi_base, "parameters", "trace_debug_level")
        acpi_trace_state = os.path.join(acpi_base, "parameters", "trace_state")
        if (
            os.path.exists(acpi_debug_level)
            and os.path.exists(acpi_debug_layer)
            and os.path.exists(acpi_trace_state)
        ):
            # backup old settings
            old_debug_level = read_file(acpi_debug_level)
            old_debug_layer = read_file(acpi_debug_layer)
            old_trace_state = read_file(acpi_trace_state)

            # enable ACPI_LV_INFO
            with open(acpi_debug_level, "w", encoding="utf-8") as w:
                w.write("0x00000004")

            # enable ACPI_EVENTS
            with open(acpi_debug_layer, "w", encoding="utf-8") as w:
                w.write("0x00000004")
            with open(acpi_trace_state, "w", encoding="utf-8") as w:
                w.write("enable")
            logging.debug("Enabled ACPI debugging for ACPI_LV_INFO/ACPI_EVENTS")
        else:
            print_color("ACPI Notify() debugging not available", "👀")

        # getting the returned value
        ret = func(*args, **kwargs)

        # disable PM debugging
        with open(pm_debug_messages, "w", encoding="utf-8") as w:
            w.write("0")

        # disable ACPI debugging
        if old_debug_level:
            with open(acpi_debug_level, "w", encoding="utf-8") as w:
                w.write(old_debug_level)
        if old_debug_layer:
            with open(acpi_debug_layer, "w", encoding="utf-8") as w:
                w.write(old_debug_layer)
        if old_trace_state:
            with open(acpi_trace_state, "w", encoding="utf-8") as w:
                w.write("disable")
        return ret

    return runner


class S0i3Failure:
    """Base class for all S0i3 failures"""

    def __init__(self):
        self.explanation = ""
        self.url = ""
        self.description = ""

    def get_failure(self):
        """Prints the failure message"""
        if self.description:
            print_color(self.description, "🚦")
        if self.explanation:
            print(self.explanation)
        if self.url:
            print(f"For more information on this failure see:\n\t{self.url}")


class RtcAlarmWrong(S0i3Failure):
    """RTC alarm is not configured to use ACPI"""

    def __init__(self):
        super().__init__()
        self.description = "rtc_cmos is not configured to use ACPI alarm"
        self.explanation = (
            "\tSome problems can occur during wakeup cycles if the HPET RTC emulation is used to\n"
            "\twake systems. This can manifest in unexpected wakeups or high power consumption.\n"
        )
        self.url = "https://github.com/systemd/systemd/issues/24279"


class MissingAmdgpu(S0i3Failure):
    """AMDGPU driver is missing"""

    def __init__(self):
        super().__init__()
        self.description = "AMDGPU driver is missing"
        self.explanation = (
            "\tThe amdgpu driver is used for hardware acceleration as well\n"
            "\tas coordination of the power states for certain IP blocks on the SOC.\n"
            "\tBe sure that you have enabled CONFIG_AMDGPU in your kernel.\n"
        )


class MissingAmdgpuFirmware(S0i3Failure):
    """AMDGPU firmware is missing"""

    def __init__(self, errors):
        super().__init__()
        self.description = "AMDGPU firmware is missing"
        self.explanation = (
            "\tThe amdgpu driver loads firmware from /lib/firmware/amdgpu\n"
            "\tIn some cases missing firmware will prevent a successful suspend cycle.\n"
            "\tUpgrade to a newer snapshot at https://gitlab.com/kernel-firmware/linux-firmware\n"
        )
        self.url = "https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=1053856"
        for error in errors:
            self.explanation += f"\t{error}"


class AmdgpuPpFeatureMask(S0i3Failure):
    """AMDGPU ppfeaturemask has been changed"""

    def __init__(self):
        super().__init__()
        self.description = "AMDGPU ppfeaturemask changed"
        self.explanation = (
            "\tThe ppfeaturemask for the amdgpu driver has been changed\n"
            "\tModifying this from the defaults may cause the system to not enter hardware sleep.\n"
        )
        self.url = "https://gitlab.freedesktop.org/drm/amd/-/issues/2808#note_2379968"


class MissingAmdPmc(S0i3Failure):
    """AMD-PMC driver is missing"""

    def __init__(self):
        super().__init__()
        self.description = "AMD-PMC driver is missing"
        self.explanation = (
            "\tThe amd-pmc driver is required for the kernel to instruct the\n"
            "\tsoc to enter the hardware sleep state.\n"
            "\tBe sure that you have enabled CONFIG_AMD_PMC in your kernel.\n"
            "\n"
            "\tIf CONFIG_AMD_PMC is enabled but the amd-pmc driver isn't loading\n"
            "\tthen you may have found a bug and should report it."
        )


class MissingThunderbolt(S0i3Failure):
    """Thunderbolt driver is missing"""

    def __init__(self):
        super().__init__()
        self.description = "thunderbolt driver is missing"
        self.explanation = (
            "\tThe thunderbolt driver is required for the USB4 routers included\n"
            "\twith the SOC to enter the proper power states.\n"
            "\tBe sure that you have enabled CONFIG_USB4 in your kernel.\n"
        )


class MissingXhciHcd(S0i3Failure):
    """xhci_hcd driver is missing"""

    def __init__(self):
        super().__init__()
        self.description = "xhci_hcd driver is missing"
        self.explanation = (
            "\tThe xhci_hcd driver is required for the USB3 controllers included\n"
            "\twith the SOC to enter the proper power states.\n"
            "\tBe sure that you have enabled CONFIG_XHCI_PCI in your kernel.\n"
        )


class MissingDriver(S0i3Failure):
    """driver is missing"""

    def __init__(self, slot):
        super().__init__()
        self.description = f"{slot} driver is missing"
        self.explanation = (
            f"\tNo driver has been bound to PCI device {slot}\n"
            "\tWithout a driver, the hardware may be able to enter a low power.\n"
            "\tstate, but there may be spurious wake up events.\n"
        )


class AcpiBiosError(S0i3Failure):
    """ACPI BIOS errors detected"""

    def __init__(self, errors):
        super().__init__()
        self.description = "ACPI BIOS Errors detected"
        self.explanation = (
            "\tWhen running a firmware component utilized for s2idle\n"
            "\tthe ACPI interpreter in the Linux kernel encountered some\n"
            "\tproblems. This usually means it's a bug in the system BIOS\n"
            "\tthat should be fixed the system manufacturer.\n"
            "\n"
            "\tYou may have problems with certain devices after resume or high\n"
            "\tpower consumption when this error occurs.\n"
        )
        for error in errors:
            self.explanation += f"\t{error}"


class VendorWrong(S0i3Failure):
    """Unsupported CPU vendor"""

    def __init__(self):
        super().__init__()
        self.description = "Unsupported CPU vendor"
        self.explanation = (
            "\tThis tool specifically measures requirements utilized\n"
            "\tby AMD's S0i3 architecture.  Some of them may apply to other\n"
            "\tvendors, but definitely some are AMD specific."
        )


class UnsupportedModel(S0i3Failure):
    """Unsupported CPU model"""

    def __init__(self):
        super().__init__()
        self.description = "Unsupported CPU model"
        self.explanation = (
            "\tThis model does not support hardware s2idle.\n"
            "\tAttempting to run s2idle will use a pure software suspend\n"
            "\tand will not yield tangible power savings."
        )


class UserNvmeConfiguration(S0i3Failure):
    """User has disabled NVME ACPI support"""

    def __init__(self):
        super().__init__()
        self.description = "NVME ACPI support is disabled"
        self.explanation = (
            "\tThe kernel command line has been configured to not support NVME ACPI support.\n"
            "\tThis is required for the NVME device to enter the proper power state.\n"
        )


class AcpiNvmeStorageD3Enable(S0i3Failure):
    """NVME device is missing ACPI attributes"""

    def __init__(self, disk, num_ssds):
        super().__init__()
        self.description = f"{disk} missing ACPI attributes"
        self.explanation = (
            "\tAn NVME device was found, but it doesn't specify the StorageD3Enable\n"
            "\tattribute in the device specific data (_DSD).\n"
            "\tThis is a BIOS bug, but it may be possible to work around in the kernel.\n"
        )
        if num_ssds > 1:
            self.explanation += (
                "\n"
                "\tIf you added an aftermarket SSD to your system, the system vendor might not have added this\n"
                "\tproperty to the BIOS for the second port which could cause this behavior.\n"
                "\n"
                "\tPlease re-run this script with the --acpidump argument and file a bug to "
                "investigate.\n"
            )
        self.url = "https://bugzilla.kernel.org/show_bug.cgi?id=216440"


class DevSlpHostIssue(S0i3Failure):
    """AHCI controller doesn't support DevSlp"""

    def __init__(self):
        super().__init__()
        self.description = "AHCI controller doesn't support DevSlp"
        self.explanation = (
            "\tThe AHCI controller is not configured to support DevSlp.\n"
            "\tThis must be enabled in BIOS for s2idle in Linux.\n"
        )


class DevSlpDiskIssue(S0i3Failure):
    """SATA disk doesn't support DevSlp"""

    def __init__(self):
        super().__init__()
        self.description = "SATA disk doesn't support DevSlp"
        self.explanation = (
            "\tThe SATA disk does not support DevSlp.\n"
            "\ts2idle in Linux requires SATA disks that support this feature.\n"
        )


class SleepModeWrong(S0i3Failure):
    """System is not configured for Modern Standby"""

    def __init__(self):
        super().__init__()
        self.description = (
            "The system hasn't been configured for Modern Standby in BIOS setup"
        )
        self.explanation = (
            "\tAMD systems must be configured for Modern Standby in BIOS setup\n"
            "\tfor s2idle to function properly in Linux.\n"
            "\tOn some OEM systems this is referred to as 'Windows' sleep mode.\n"
            "\tIf the BIOS is configured for S3 and you manually select s2idle\n"
            "\tin /sys/power/mem_sleep, the system will not enter the deepest hardware state."
        )


class DeepSleep(S0i3Failure):
    """Deep sleep is configured on the kernel command line"""

    def __init__(self):
        super().__init__()
        self.description = (
            "The kernel command line is asserting the system to use deep sleep"
        )
        self.explanation = (
            "\tAdding mem_sleep_default=deep doesn't work on AMD systems.\n"
            "\tPlease remove it from the kernel command line."
        )


class FadtWrong(S0i3Failure):
    """FADT doesn't support low power idle"""

    def __init__(self):
        super().__init__()
        self.description = (
            "The kernel didn't emit a message that low power idle was supported"
        )
        self.explanation = (
            "\tLow power idle is a bit documented in the FADT to indicate that\n"
            "\tlow power idle is supported.\n"
            "\tOnly newer kernels support emitting this message, so if you run on\n"
            "\tan older kernel you may get a false negative.\n"
            "\tWhen launched as root this script will try to directly introspect the\n"
            "\tACPI tables to confirm this."
        )


class Irq1Workaround(S0i3Failure):
    """IRQ1 wakeup source is active"""

    def __init__(self):
        super().__init__()
        self.description = "The wakeup showed an IRQ1 wakeup source, which might be a platform firmware bug"
        self.explanation = (
            "\tA number of Renoir, Lucienne, Cezanne, & Barcelo platforms have a platform firmware\n"
            "\tbug where IRQ1 is triggered during s0i3 resume.\n"
            "\tYou may have tripped up on this bug as IRQ1 was active during resume.\n"
            "\tIf you didn't press a keyboard key to wakeup the system then this can be\n"
            "\tthe cause of spurious wakeups.\n"
            "\n"
            "\tTo fix it, first try to upgrade to the latest firmware from your manufacturer.\n"
            "\tIf you're already upgraded to the latest firmware you can use one of two workarounds:\n"
            "\t 1. Manually disable wakeups from IRQ1 by running this command each boot:\n"
            "\t\t echo 'disabled' | sudo tee /sys/bus/serio/devices/serio0/power/wakeup \n"
            "\t 2. Use the below linked patch in your kernel."
        )
        self.url = "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/drivers/platform/x86/amd/pmc.c?id=8e60615e8932167057b363c11a7835da7f007106"


class KernelRingBufferWrapped(S0i3Failure):
    """Kernel ringbuffer has wrapped"""

    def __init__(self):
        super().__init__()
        self.description = "Kernel ringbuffer has wrapped"
        self.explanation = (
            "\tThis script relies upon analyzing the kernel log for markers.\n"
            "\tThe kernel's log provided by dmesg uses a ring buffer.\n"
            "\tWhen the ring buffer fills up it will wrap around and overwrite old messages.\n"
            "\n"
            "\tIn this case it's not possible to look for some of these markers\n"
            "\n"
            "\tPassing the pre-requisites check won't be possible without rebooting the machine.\n"
            "\tIf you are sure your system meets pre-requisites, you can re-run the script using.\n"
            "\tthe systemd logger or with --force.\n"
        )


class AmdHsmpBug(S0i3Failure):
    """AMD HSMP is built into the kernel"""

    def __init__(self):
        super().__init__()
        self.description = "amd-hsmp built in to kernel"
        self.explanation = (
            "\tThe kernel has been compiled with CONFIG_AMD_HSMP=y.\n"
            "\tThis has been shown to cause suspend failures on some systems.\n"
            "\n"
            "\tEither recompile the kernel without CONFIG_AMD_HSMP,\n"
            "\tor use initcall_blacklist=hsmp_plt_init on your kernel command line to avoid triggering problems\n"
            "\n"
        )
        self.url = "https://gitlab.freedesktop.org/drm/amd/-/issues/2414"


class WCN6855Bug(S0i3Failure):
    """WCN6855 firmware causes spurious wakeups"""

    def __init__(self):
        super().__init__()
        self.description = "The firmware loaded for the WCN6855 causes spurious wakeups"
        self.explanation = (
            "\tDuring s2idle on AMD systems PCIe devices are put into D3cold. During wakeup they're transitioned back\n"
            "\tinto the state they were before s2idle.  For many implementations this is D3hot.\n"
            "\tIf an ACPI event has been triggered by the EC, the hardware will resume from s2idle,\n"
            "\tbut the kernel should process the event and then put it back into s2idle.\n"
            "\n"
            "\tWhen this bug occurs, a GPIO connected to the WLAN card is active on the system making\n"
            "\the GPIO controller IRQ also active.  The kernel sees that the ACPI event IRQ and GPIO\n"
            "\tcontroller IRQ are both active and resumes the system.\n"
            "\n"
            "\tSome non-exhaustive events that will trigger this behavior:\n"
            "\t * Suspending the system and then closing the lid.\n"
            "\t * Suspending the system and then unplugging the AC adapter.\n"
            "\t * Suspending the system and the EC notifying the OS of a battery level change.\n"
            "\n"
            "\tThis issue is fixed by updated WCN6855 firmware which will avoid triggering the GPIO.\n"
            "\tThe version string containing the fix is 'WLAN.HSP.1.1-03125-QCAHSPSWPL_V1_V2_SILICONZ_LITE-3.6510.23'\n"
        )
        self.url = "https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git/commit/?id=c7a57ef688f7d99d8338a5d8edddc8836ff0e6de"


class I2CHidBug(S0i3Failure):
    """I2C HID device causes spurious wakeups"""

    def __init__(self, name, remediation):
        super().__init__()
        self.description = f"The {name} device has been reported to cause high power consumption and spurious wakeups"
        self.explanation = (
            "\tI2C devices work in an initiator/receiver relationship where the device is the receiver. In order for the receiver to indicate\n"
            "\tthe initiator needs to read data they will assert an attention GPIO pin.\n"
            "\tWhen a device misbehaves it may assert this pin spuriously which can cause the SoC to wakeup prematurely.\n"
            "\tThis typically manifests as high power consumption at runtime and spurious wakeups at suspend.\n"
            "\n"
            "\tThis issue can be worked around by unbinding the device from the kernel using this command:\n"
            "\n"
            f"\t{remediation}\n"
            "\n"
            "\tTo fix this issue permanently the kernel will need to avoid binding to this device."
        )
        self.url = "https://gitlab.freedesktop.org/drm/amd/-/issues/2812"


class SpuriousWakeup(S0i3Failure):
    """System woke up prematurely"""

    def __init__(self, duration):
        super().__init__()
        self.description = (
            f"Userspace wasn't asleep at least {timedelta(seconds=duration)}"
        )
        self.explanation = (
            f"\tThe system was programmed to sleep for {timedelta(seconds=duration)}, but woke up prematurely.\n"
            "\tThis typically happens when the system was woken up from a non-timer based source.\n"
            "\n"
            "\tIf you didn't intentionally wake it up, then there may be a kernel or firmware bug\n"
        )


class LowHardwareSleepResidency(S0i3Failure):
    """System had low hardware sleep residency"""

    def __init__(self, duration, percent):
        super().__init__()
        self.description = "System had low hardware sleep residency"
        self.explanation = (
            f"\tThe system was asleep for {timedelta(seconds=duration)}, but only spent {percent:.2%}\n"
            "\tof this time in a hardware sleep state.  In sleep cycles that are at least\n"
            "\t60 seconds long it's expected you spend above 90 percent of the cycle in"
            "\thardware sleep.\n"
        )


class MSRFailure(S0i3Failure):
    """MSR access failed"""

    def __init__(self):
        super().__init__()
        self.description = "PC6 or CC6 state disabled"
        self.explanation = (
            "\tThe PC6 state of the package or the CC6 state of CPU cores was disabled.\n"
            "\tThis will prevent the system from getting to the deepest sleep state over suspend.\n"
        )


class TaintedKernel(S0i3Failure):
    """Kernel is tainted"""

    def __init__(self):
        super().__init__()
        self.description = "Kernel is tainted"
        self.explanation = (
            "\tA tainted kernel may exhibit unpredictable bugs that are difficult for this script to characterize.\n"
            "\tIf this is intended behavior run the tool with --force.\n"
        )
        self.url = "https://gitlab.freedesktop.org/drm/amd/-/issues/3089"


class DMArNotEnabled(S0i3Failure):
    """DMAr is not enabled"""

    def __init__(self):
        super().__init__()
        self.description = "Pre-boot DMA protection disabled"
        self.explanation = (
            "\tPre-boot IOMMU DMA protection has been disabled.\n"
            "\tWhen the IOMMU is enabled this platform requires pre-boot DMA protection for suspend to work.\n"
        )


class MissingIommuACPI(S0i3Failure):
    """IOMMU ACPI table errors"""

    def __init__(self, device):
        super().__init__()
        self.description = f"Device {device} missing from ACPI tables"
        self.explanation = (
            f"\tThe ACPI device {device} is required for suspend to work when the IOMMU is enabled.\n"
            "\tPlease check your BIOS settings and if configured correctly, report a bug to your system vendor.\n"
        )
        self.url = "https://gitlab.freedesktop.org/drm/amd/-/issues/3738#note_2667140"


class MissingIommuPolicy(S0i3Failure):
    """ACPI table errors"""

    def __init__(self, device):
        super().__init__()
        self.description = f"Device {device} does not have IOMMU policy applied"
        self.explanation = (
            f"\tThe ACPI device {device} is present but no IOMMU policy was set for it.\n"
            "\tThis generally happens if the HID or UID don't match the ACPI IVRS table.\n"
        )


class IommuPageFault(S0i3Failure):
    """IOMMU Page fault"""

    def __init__(self, device):
        super().__init__()
        self.description = f"Page fault reported for {device}"
        self.explanation = (
            f"\tThe IOMMU reports a page fault caused by {device}. This can prevent suspend/resume from functioning properly\n"
            "\tThe page fault can be the device itself, a problem in the firmware or a problem in the kernel.\n"
            "\tReport a bug for further triage and investigation.\n"
        )


class SMTNotEnabled(S0i3Failure):
    """SMT is not enabled"""

    def __init__(self):
        super().__init__()
        self.description = "SMT is not enabled"
        self.explanation = (
            "\tDisabling SMT prevents cores from going into the correct state.\n"
        )


class ASpmWrong(S0i3Failure):
    """ASPM is overridden"""

    def __init__(self):
        super().__init__()
        self.description = "ASPM is overridden"
        self.explanation = (
            "\t Modifying ASPM may prevent PCIe devices from going into the\n"
            "\t correct state and lead to system stability issues.\n"
        )


class UnservicedGpio(S0i3Failure):
    """GPIO is not serviced"""

    def __init__(self):
        super().__init__()
        self.description = "GPIO interrupt is not serviced"
        self.explanation = (
            "\t All GPIO controllers interrupts must be serviced to enter\n"
            "\t hardware sleep.\n"
            "\t Make sure that all drivers necessary to service GPIOs are loaded.\n"
            "\t The most common cause is that i2c-hid-acpi is not loaded but the.\n"
            "\t machine contains an I2C touchpad.\n"
        )


class DmiNotSetup(S0i3Failure):
    """DMI isn't setup"""

    def __init__(self):
        super().__init__()
        self.description = "DMI data was not scanned"
        self.explanation = (
            "\t If DMI data hasn't been scanned then quirks that are dependent\n"
            "\t upon DMI won't be loaded.\n"
            "\t Most notably, this will prevent the rtc-cmos driver from setting.\n"
            "\t up properly by default. It may also prevent other drivers from working.\n"
        )


class LimitedCores(S0i3Failure):
    """Number of CPU cores limited"""

    def __init__(self, actual_cores, max_cores):
        super().__init__()
        self.description = "CPU cores have been limited"
        self.explanation = (
            f"\tThe CPU cores have been limited to {max_cores}, but the system\n"
            f"\tactually has {actual_cores}. Limiting the cores will prevent the\n"
            "\tthe system from going into a hardware sleep state.\n"
            "\tThis is typically solved by increasing the kernel config CONFIG_NR_CPUS.\n"
        )


class RogAllyOldMcu(S0i3Failure):
    """MCU firwmare is too old"""

    def __init__(self, vmin, actual):
        super().__init__()
        self.description = "Rog Ally MCU firmware is too old"
        self.explanation = (
            f"\tThe MCU is version {actual}, but needs to be at least {vmin}\n"
            f"\tto avoid major issues with interactions with suspend\n"
        )


class RogAllyMcuPowerSave(S0i3Failure):
    """MCU powersave is disabled"""

    def __init__(self):
        super().__init__()
        self.description = "Rog Ally MCU power save is disabled"
        self.explanation = (
            f"\tThe MCU powersave feature is disabled which will cause problems\n"
            f"\twith the controller after suspend/resume.\n"
        )


class KernelLogger:
    """Base class for kernel loggers"""

    def __init__(self):
        pass

    def seek(self):
        """Seek to the beginning of the log"""

    def process_callback(self, callback):
        """Process the log"""

    def match_line(self, matches):
        """Find lines that match all matches"""

    def match_pattern(self, pattern):
        """Find lines that match a pattern"""

    def capture_full_dmesg(self, line):
        """Capture the full dmesg"""
        logging.debug(line)


class DmesgLogger(KernelLogger):
    """Class for dmesg logging"""

    def __init__(self):
        self.since_support = False
        self.buffer = None
        self.seeked = False

        cmd = ["dmesg", "-h"]
        result = subprocess.run(cmd, check=True, capture_output=True)
        for line in result.stdout.decode("utf-8").split("\n"):
            if "--since" in line:
                self.since_support = True
        logging.debug("Since support: %d", self.since_support)

        self.command = ["dmesg", "-t", "-k"]
        self._refresh_head()

    def _refresh_head(self):
        self.buffer = []
        self.seeked = False
        result = subprocess.run(self.command, check=True, capture_output=True)
        if result.returncode == 0:
            self.buffer = result.stdout.decode("utf-8")

    def seek(self, tim=None):
        """Seek to the beginning of the log"""
        if tim:
            if self.since_support:
                # look 10 seconds back because dmesg time isn't always accurate
                fuzz = tim - timedelta(seconds=10)
                cmd = self.command + [
                    "--time-format=iso",
                    f"--since={fuzz.strftime('%Y-%m-%dT%H:%M:%S')}",
                ]
            else:
                cmd = self.command
            result = subprocess.run(cmd, check=True, capture_output=True)
            if result.returncode == 0:
                self.buffer = result.stdout.decode("utf-8")
                if self.since_support:
                    self.seeked = True
        elif self.seeked:
            self._refresh_head()

    def process_callback(self, callback):
        """Process the log"""
        for entry in self.buffer.split("\n"):
            callback(entry)

    def match_line(self, matches):
        """Find lines that match all matches"""
        for entry in self.buffer.split("\n"):
            for match in matches:
                if match not in entry:
                    break
                return entry
        return None

    def match_pattern(self, pattern):
        for entry in self.buffer.split("\n"):
            if re.search(pattern, entry):
                return entry
        return None

    def capture_full_dmesg(self, line=None):
        """Capture the full dmesg"""
        self.seek()
        for entry in self.buffer.split("\n"):
            super().capture_full_dmesg(entry)

    def capture_header(self):
        """Capture the header of the log"""
        return self.buffer.split("\n")[0]


class SystemdLogger(KernelLogger):
    """Class for logging using systemd journal"""

    def __init__(self):
        from systemd import journal  # pylint: disable=import-outside-toplevel

        self.journal = journal.Reader()
        self.journal.this_boot()
        self.journal.log_level(journal.LOG_INFO)
        self.journal.add_match(_TRANSPORT="kernel")
        self.journal.add_match(PRIORITY=journal.LOG_DEBUG)

    def seek(self, tim=None):
        """Seek to the beginning of the log"""
        if tim:
            self.journal.seek_realtime(tim)
        else:
            self.journal.seek_head()

    def process_callback(self, callback):
        """Process the log"""
        for entry in self.journal:
            callback(entry["MESSAGE"])

    def match_line(self, matches):
        """Find lines that match all matches"""
        for entry in self.journal:
            for match in matches:
                if match not in entry["MESSAGE"]:
                    break
                return entry["MESSAGE"]
        return None

    def match_pattern(self, pattern):
        """Find lines that match a pattern"""
        for entry in self.journal:
            if re.search(pattern, entry["MESSAGE"]):
                return entry["MESSAGE"]
        return None

    def capture_full_dmesg(self, line=None):
        """Capture the full dmesg"""
        self.seek()
        for entry in self.journal:
            super().capture_full_dmesg(entry["MESSAGE"])


class DistroPackage:
    """Base class for distro packages"""

    def __init__(self, deb, rpm, arch, pip, root):
        self.deb = deb
        self.rpm = rpm
        self.arch = arch
        self.pip = pip
        self.root = root

    def install(self, dist):
        """Install the package for a given distro"""
        if not self.root:
            sys.exit(1)
        if dist == "ubuntu" or dist == "debian":
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

    def __init__(self, root):
        super().__init__(
            deb="python3-pyudev",
            rpm="python3-pyudev",
            arch="python-pyudev",
            pip="pyudev",
            root=root,
        )


class IaslPackage(DistroPackage):
    """Iasl package"""

    def __init__(self, root):
        super().__init__(
            deb="acpica-tools", rpm="acpica-tools", arch="acpica", pip=None, root=root
        )


class PackagingPackage(DistroPackage):
    """Packaging package"""

    def __init__(self, root):
        super().__init__(
            deb="python3-packaging",
            rpm=None,
            arch="python-packaging",
            pip="python3-setuptools",
            root=root,
        )


class JournaldPackage(DistroPackage):
    """Journald package"""

    def __init__(self, root):
        super().__init__(
            deb="python3-systemd",
            rpm="python3-pyudev",
            arch="python-systemd",
            pip=None,
            root=root,
        )


class EthtoolPackage(DistroPackage):
    """Ethtool package"""

    def __init__(self, root):
        super().__init__(
            deb="ethtool",
            rpm="ethtool",
            arch="ethtool",
            pip=None,
            root=root,
        )


class FwupdPackage(DistroPackage):
    """Fwupd package"""

    def __init__(self, root):
        super().__init__(
            deb="gir1.2-fwupd-2.0",
            rpm=None,
            arch=None,
            pip=None,
            root=root,
        )


class WakeIRQ:
    """Class for wake IRQs"""

    def __init__(self, num, context):
        self.num = num
        p = os.path.join("/", "sys", "kernel", "irq", str(num))
        self.chip_name = read_file(os.path.join(p, "chip_name"))
        self.actions = read_file(os.path.join(p, "actions"))
        self.driver = ""
        self.name = ""
        wakeup = read_file(os.path.join(p, "wakeup"))

        # This is an IRQ tied to _AEI
        if self.chip_name == "amd_gpio":
            hw_gpio = read_file(os.path.join(p, "hwirq"))
            self.name = f"GPIO {hw_gpio}"
        # legacy IRQs
        elif "IR-IO-APIC" in self.chip_name:
            if self.actions == "acpi":
                self.name = "ACPI SCI"
            elif self.actions == "i8042":
                self.name = "PS/2 controller"
            elif self.actions == "pinctrl_amd":
                self.name = "GPIO Controller"
            elif self.actions == "rtc0":
                self.name = "RTC"
            elif self.actions == "timer":
                self.name = "Timer"
            self.actions = ""
        elif "PCI-MSI" in self.chip_name:
            bdf = self.chip_name.split("-")[-1]
            for dev in context.list_devices(subsystem="pci"):
                if dev.device_path.endswith(bdf):
                    vendor = dev.properties.get("ID_VENDOR_FROM_DATABASE")
                    desc = dev.properties.get("ID_PCI_CLASS_FROM_DATABASE")
                    if not desc:
                        desc = dev.properties.get("ID_PCI_INTERFACE_FROM_DATABASE")
                    name = dev.properties.get("PCI_SLOT_NAME")
                    self.driver = dev.properties.get("DRIVER")
                    self.name = f"{vendor} {desc} ({name})"
                    break

        # "might" look like an ACPI device, try to follow it
        if not self.name and self.actions:
            p = os.path.join("/", "sys", "bus", "acpi", "devices", self.actions)
            if os.path.exists(p):
                for directory in os.listdir(p):
                    if "physical_node" not in directory:
                        continue

                    for root, _dirs, files in os.walk(
                        os.path.join(p, directory), followlinks=True
                    ):
                        if "name" in files:
                            self.name = read_file(os.path.join(root, "name"))
                            t = os.path.join(root, "driver")
                            if os.path.exists(t):
                                self.driver = os.path.basename(os.readlink(t))
                            break
                    if self.name:
                        break

        # If the name isn't descriptive try to guess further
        if self.driver and self.actions == self.name:
            if self.driver == "i2c_hid_acpi":
                self.name = f"{self.name} I2C HID device"

        # check if it's disabled
        if not self.name and wakeup == "disabled":
            self.name = "Disabled interrupt"

    def __str__(self):
        actions = f" ({self.actions})" if self.actions else ""
        return f"{self.name}{actions}"


class S0i3Validator:
    """
    S0i3Validator class performs various checks and validations for
    S0i3/s2idle analysis on AMD systems.
    """

    def check_selinux(self):
        """Check if SELinux is enabled and enforce mode is active."""
        p = os.path.join("/", "sys", "fs", "selinux", "enforce")
        if os.path.exists(p):
            v = read_file(p)
            if v == "1" and not self.root_user:
                fatal_error("Unable to run with SELinux enabled without root")

    def show_install_message(self, message):
        """Show a message to install a package"""
        action = Headers.InstallAction if self.root_user else Headers.RerunAction
        message = f"{message}. {action}."
        print_color(message, "👀")

    def guess_distro(self):
        """Guess the distro based on heuristics"""
        self.distro = None
        self.pretty_distro = None

        if DISTRO:
            try:
                self.distro = distro.id()
                self.pretty_distro = distro.distro.os_release_info()["pretty_name"]
            except AttributeError:
                print_color("Failed to discover distro using python-distro", "🚦")

        if not self.distro or not self.pretty_distro:
            p = os.path.join("/", "etc", "os-release")
            if os.path.exists(p):
                v = read_file(p)
                for line in v.split("\n"):
                    if "ID=" in line:
                        self.distro = line.split("=")[-1].strip().strip('"')
                    if "PRETTY_NAME=" in line:
                        self.pretty_distro = line.split("=")[-1].strip().strip('"')
        if not self.distro:
            if os.path.exists("/etc/arch-release"):
                self.distro = "arch"
            elif os.path.exists("/etc/fedora-release"):
                self.distro = "fedora"
            elif os.path.exists("/etc/debian_version"):
                self.distro = "debian"

        if not self.distro:
            fatal_error("Unable to identify distro")

    def setup_kernel_log(self, kernel_log):
        """Setup the kernel log provider"""
        self.kernel_log = None
        if kernel_log == "auto":
            init_daemon = read_file("/proc/1/comm")
            if "systemd" in init_daemon:
                try:
                    self.kernel_log = SystemdLogger()
                except ImportError:
                    self.kernel_log = None
                if not self.kernel_log:
                    self.show_install_message(Headers.MissingJournald)
                    package = JournaldPackage(self.root_user)
                    package.install(self.distro)
                    self.kernel_log = SystemdLogger()
            else:
                try:
                    self.kernel_log = DmesgLogger()
                except subprocess.CalledProcessError:
                    self.kernel_log = None
        elif kernel_log == "systemd":
            self.kernel_log = SystemdLogger()
        elif kernel_log == "dmesg":
            self.kernel_log = DmesgLogger()

    def __init__(self, acpidump, logind, debug_ec, kernel_log, use_wakeup_count):
        # for installing and running suspend
        self.root_user = os.geteuid() == 0
        self.check_selinux()

        # capture all DSDT/SSDT or just one with _AEI
        self.acpidump = acpidump

        # initiate suspend cycles using logind
        self.logind = logind

        # turn on EC debug messages
        self.debug_ec = debug_ec

        self.guess_distro()

        # for analyzing devices
        try:
            from pyudev import Context  # pylint: disable=import-outside-toplevel

            self.pyudev = Context()
        except ModuleNotFoundError:
            self.pyudev = False

        if not self.pyudev:
            self.show_install_message(Headers.MissingPyudev)
            package = PyUdevPackage(self.root_user)
            package.install(self.distro)
            try:
                from pyudev import Context  # pylint: disable=import-outside-toplevel
            except ModuleNotFoundError:
                fatal_error("Missing python-pyudev package, unable to identify devices")

            self.pyudev = Context()

        try:
            self.iasl = subprocess.call(["iasl", "-v"], stdout=subprocess.DEVNULL) == 0
        except FileNotFoundError:
            self.show_install_message(Headers.MissingIasl)
            package = IaslPackage(self.root_user)
            self.iasl = package.install(self.distro)

        self.setup_kernel_log(kernel_log)

        # for comparing SMU version
        if not VERSION:
            self.show_install_message(Headers.MissingPackaging)
            package = PackagingPackage(self.root_user)
            package.install(self.distro)
            from packaging import version  # pylint: disable=import-outside-toplevel

        # for reading firmware versions
        if not FWUPD:
            self.show_install_message(Headers.MissingFwupd)
            package = FwupdPackage(self.root_user)
            package.install(self.distro)

        self.cpu_family = ""
        self.cpu_model = ""
        self.cpu_model_string = ""
        self.smu_version = ""
        self.smu_program = ""

        # we only want kernel messages from our triggered suspend
        self.last_suspend = datetime.now()
        self.requested_duration = 0
        self.userspace_duration = 0
        self.kernel_duration = 0
        self.hw_sleep_duration = 0

        # failure reasons to display at the end
        self.failures = []

        # for comparing GPEs before/after sleep
        self.gpes = {}
        self.irqs = []

        # for monitoring battery levels across suspend
        self.energy = {}
        self.charge = {}

        # for monitoring thermals across suspend
        self.thermal = {}

        # If we're locked down, a lot less errors make sense
        self.lockdown = False

        # kernel versioning reporting and checking
        self.kernel = platform.uname().release
        self.kernel_major = int(self.kernel.split(".")[0])
        self.kernel_minor = int(self.kernel.split(".")[1])

        # used to analyze the suspend cycle
        self.suspend_count = 0
        self.cycle_count = 0
        self.upep = False
        self.upep_microsoft = False
        self.wakeup_irqs = []
        self.notify_devices = []
        self.idle_masks = []
        self.acpi_errors = []
        self.active_gpios = []
        self.irq1_workaround = False
        self.page_faults = []
        self.wakeup_count = {}
        self.use_wakeup_count = use_wakeup_count

    # See https://github.com/torvalds/linux/commit/ec6c0503190417abf8b8f8e3e955ae583a4e50d4
    def check_fadt(self):
        """Check the kernel emitted a message specific to 6.0 or later indicating FADT had a bit set."""
        found = False
        if not self.kernel_log:
            message = "Unable to test FADT from kernel log"
            print_color(message, "🚦")
        else:
            self.kernel_log.seek()
            matches = ["Low-power S0 idle used by default for system suspend"]
            found = self.kernel_log.match_line(matches)
        # try to look at FACP directly if not found (older kernel compat)
        if not found:
            if not self.root_user:
                logging.debug("Unable to capture ACPI tables without root")
                return True

            logging.debug("Fetching low power idle bit directly from FADT")
            target = os.path.join("/", "sys", "firmware", "acpi", "tables", "FACP")
            try:
                with open(target, "rb") as r:
                    r.seek(0x70)
                    found = struct.unpack("<I", r.read(4))[0] & BIT(21)
            except PermissionError:
                print_color("FADT check unavailable", Colors.WARNING)
                return True
        if found:
            message = "ACPI FADT supports Low-power S0 idle"
            print_color(message, "✅")
        else:
            message = "ACPI FADT doesn't support Low-power S0 idle"
            print_color(message, "❌")
            self.failures += [FadtWrong()]
        return found

    def check_msr(self):
        """Check if PC6 or CC6 has been disabled"""

        def read_msr(msr, cpu):
            p = os.path.join("/", "dev", "cpu", f"{cpu}", "msr")
            if not os.path.exists(p) and self.root_user:
                os.system("modprobe msr")
            f = os.open(p, os.O_RDONLY)
            os.lseek(f, msr, os.SEEK_SET)
            val = struct.unpack("Q", os.read(f, 8))[0]
            os.close(f)
            return val

        def check_bits(value, mask):
            return value & mask

        expect = {
            0xC0010292: BIT(32),  # PC6
            0xC0010296: (BIT(22) | BIT(14) | BIT(6)),  # CC6
        }
        try:
            for reg, expect_val in expect.items():
                val = read_msr(reg, 0)
                if not check_bits(val, expect_val):
                    self.failures += [MSRFailure()]
                    return False
                logging.debug("MSR %s: %s", hex(reg), hex(val))
            print_color("PC6 and CC6 states are enabled", "✅")
        except FileNotFoundError:
            print_color("Unabled to check MSRs: MSR kernel module not loaded", "❌")
            return False
        except PermissionError:
            print_color("MSR checks unavailable", "🚦")

        return True

    def capture_kernel_version(self):
        """Log the kernel version used"""
        if self.pretty_distro:
            print_color(f"{self.pretty_distro}", "🐧")
        print_color(f"Kernel {self.kernel}", "🐧")

    def check_thermal(self):
        """Capture thermal zone information"""
        devs = []
        for dev in self.pyudev.list_devices(subsystem="acpi", DRIVER="thermal"):
            devs.append(dev)

        logging.debug("Thermal zones")
        for dev in devs:
            prefix = "├─ " if dev != devs[-1] else "└─"
            detail_prefix = "│ \t" if dev != devs[-1] else "  \t"
            name = os.path.basename(dev.device_path)
            p = os.path.join(dev.sys_path, "thermal_zone")
            temp = int(read_file(os.path.join(p, "temp"))) / 1000

            logging.debug("%s %s", prefix, name)
            if name not in self.thermal:
                logging.debug("%s temp: %s°C", detail_prefix, temp)
            else:
                logging.debug(
                    "%s %s°C -> %s°C", detail_prefix, self.thermal[name], temp
                )

            # handle all trip points
            trip_count = 0
            for f in os.listdir(p):
                if "trip_point" not in f:
                    continue
                if "temp" not in f:
                    continue
                trip_count = trip_count + 1

            for i in range(0, trip_count):
                f = os.path.join(p, f"trip_point_{i}_type")
                trip_type = read_file(f)
                f = os.path.join(p, f"trip_point_{i}_temp")
                trip = int(read_file(f)) / 1000

                if name not in self.thermal:
                    logging.debug(f"{detail_prefix} {trip_type} trip: {trip}°C")

                if temp > trip:
                    print_color(
                        f"Thermal zone {name} past trip point {trip_type}: {trip}°C",
                        "🌡️",
                    )
                    return False
            self.thermal[name] = temp

        return True

    def check_battery(self):
        """Check battery level"""
        for dev in self.pyudev.list_devices(
            subsystem="power_supply", POWER_SUPPLY_TYPE="Battery"
        ):
            if not "PNP0C0A" in dev.device_path:
                continue

            energy_full_design = get_property_pyudev(
                dev.properties, "POWER_SUPPLY_ENERGY_FULL_DESIGN"
            )
            energy_full = get_property_pyudev(
                dev.properties, "POWER_SUPPLY_ENERGY_FULL"
            )
            energy = get_property_pyudev(dev.properties, "POWER_SUPPLY_ENERGY_NOW")
            charge_full_design = get_property_pyudev(
                dev.properties, "POWER_SUPPLY_CHARGE_FULL_DESIGN"
            )
            charge_full = get_property_pyudev(
                dev.properties, "POWER_SUPPLY_CHARGE_FULL"
            )
            charge = get_property_pyudev(dev.properties, "POWER_SUPPLY_CHARGE_NOW")
            man = get_property_pyudev(dev.properties, "POWER_SUPPLY_MANUFACTURER", "")
            model = get_property_pyudev(dev.properties, "POWER_SUPPLY_MODEL_NAME", "")
            name = get_property_pyudev(dev.properties, "POWER_SUPPLY_NAME", "Unknown")

            if energy_full_design:
                logging.debug("%s energy level is %s µWh", name, energy)
                if name not in self.energy:
                    print_color(
                        f"Battery {name} ({man} {model}) is operating at {float(energy_full) / int(energy_full_design):.2%} of design",
                        "🔋",
                    )
                else:
                    diff = abs(int(energy) - self.energy[name])
                    percent = float(diff) / int(energy_full)
                    if int(energy) > self.energy[name]:
                        action = "gained"
                    else:
                        action = "lost"
                    avg = round(
                        diff
                        / 1000000
                        / (self.userspace_duration.total_seconds() / 3600),
                        2,
                    )
                    print_color(
                        f"Battery {name} {action} {diff} µWh ({percent:.2%}) [Average rate {avg}W]",
                        "🔋",
                    )
                self.energy[name] = int(energy)

            if charge_full_design:
                logging.debug("%s charge level is %s µAh", name, charge)
                if name not in self.charge:
                    print_color(
                        f"Battery {name} ({man} {model}) is operating at {float(charge_full) / int(charge_full_design):.2%} of design",
                        "🔋",
                    )
                else:
                    diff = abs(int(charge) - self.charge[name])
                    percent = float(diff) / int(charge_full)
                    if int(charge) > self.charge[name]:
                        action = "gained"
                    else:
                        action = "lost"
                    avg = round(
                        diff
                        / 1000000
                        / (self.userspace_duration.total_seconds() / 3600),
                        2,
                    )
                    print_color(
                        f"Battery {name} {action} {diff} µAh ({percent:.2%}) [Average rate: {avg}A]",
                        "🔋",
                    )
                self.charge[name] = int(charge)

        return True

    def check_lps0(self):
        """Check if LPS0 is enabled"""
        for m in ["acpi", "acpi_x86"]:
            p = os.path.join("/", "sys", "module", m, "parameters", "sleep_no_lps0")
            if not os.path.exists(p):
                continue
            fail = read_file(p) == "Y"
            if fail:
                print_color("LPS0 _DSM disabled", "❌")
            else:
                print_color("LPS0 _DSM enabled", "✅")
            return not fail
        print_color("LPS0 _DSM mpt found", "👀")
        return False

    def check_cpu(self):
        """Check if the CPU is supported"""

        def read_cpuid(cpu, leaf, subleaf):
            """Read CPUID using kernel userspace interface"""
            p = os.path.join("/", "dev", "cpu", f"{cpu}", "cpuid")
            if not os.path.exists(p) and self.root_user:
                os.system("modprobe cpuid")
            with open(p, "rb") as f:
                position = (subleaf << 32) | leaf
                f.seek(position)
                data = f.read(16)
                return struct.unpack("4I", data)

        p = os.path.join("/", "proc", "cpuinfo")
        valid = False
        cpu = read_file(p)
        for line in cpu.split("\n"):
            if "AuthenticAMD" in line:
                valid = True
                continue
            if "cpu family" in line:
                self.cpu_family = int(line.split()[-1])
                continue
            if "model name" in line:
                self.cpu_model_string = line.split(":")[-1].strip()
                continue
            if "model" in line:
                self.cpu_model = int(line.split()[-1])
                continue
            if self.cpu_family and self.cpu_model and self.cpu_model_string:
                break

        # check for supported vendor
        if not valid:
            self.failures += [VendorWrong()]
            print_color(
                "This tool is not designed for parts from this CPU vendor",
                "❌",
            )
            return False

        # check for supported models
        if self.cpu_family == 0x17:
            if self.cpu_model in range(0x30, 0x3F):
                valid = False
        if self.cpu_family == 0x19:
            if self.cpu_model in [0x08, 0x18]:
                valid = False

        if not valid:
            self.failures += [UnsupportedModel()]
            print_color(
                "This CPU model does not support hardware sleep over s2idle",
                "❌",
            )
            return False

        # check for artificially limited CPUs
        p = os.path.join("/", "sys", "devices", "system", "cpu", "kernel_max")
        max_cpus = int(read_file(p)) + 1  # 0 indexed
        # https://www.amd.com/content/dam/amd/en/documents/processor-tech-docs/programmer-references/24594.pdf
        # Extended Topology Enumeration (NumLogCores)
        # CPUID 0x80000026 subleaf 1
        try:
            _, cpu_count, _, _ = read_cpuid(0, 0x80000026, 1)
            if cpu_count > max_cpus:
                print_color(
                    f"The kernel has been limited to {max_cpus} CPU cores, but the system has {cpu_count} cores",
                    "❌",
                )
                self.failures += [LimitedCores(cpu_count, max_cpus)]
                return False
            logging.debug("CPU core count: %d max: %d", cpu_count, max_cpus)
        except FileNotFoundError:
            print_color(
                "Unabled to check CPU topology: cpuid kernel module not loaded", "❌"
            )
            return False
        except PermissionError:
            print_color("CPUID checks unavailable", "🚦")

        if valid:
            print_color(
                f"{self.cpu_model_string} (family {self.cpu_family:x} model {self.cpu_model:x})",
                "✅",
            )

        return True

    def check_smt(self):
        """Check if SMT is enabled"""
        p = os.path.join("/", "sys", "devices", "system", "cpu", "smt", "control")
        v = read_file(p)
        logging.debug("SMT control: %s", v)
        if v == "notsupported":
            return True
        p = os.path.join("/", "sys", "devices", "system", "cpu", "smt", "active")
        v = read_file(p)
        if v == "0":
            self.failures += [SMTNotEnabled()]
            print_color("SMT is not enabled", "❌")
            return False
        print_color("SMT enabled", "✅")
        return True

    def capture_smbios(self):
        """Capture the SMBIOS (DMI) information"""
        p = os.path.join("/", "sys", "class", "dmi", "id")
        if not os.path.exists(p):
            print_color("DMI data was not setup", "🚦")
            self.failures += [DmiNotSetup()]
        else:
            keys = {}
            filtered = [
                "product_serial",
                "board_serial",
                "board_asset_tag",
                "chassis_asset_tag",
                "chassis_serial",
                "modalias",
                "uevent",
                "product_uuid",
            ]
            for root, _dirs, files in os.walk(p, topdown=False):
                files.sort()
                for fname in files:
                    if "power" in root:
                        continue
                    if fname in filtered:
                        continue
                    contents = read_file(os.path.join(root, fname))
                    keys[fname] = contents
            print_color(
                f"{keys['sys_vendor']} {keys['product_name']} ({keys['product_family']})",
                "💻",
            )
            for key, value in keys.items():
                if (
                    "product_name" in key
                    or "sys_vendor" in key
                    or "product_family" in key
                ):
                    continue
                logging.debug("%s: %s", key, value)

    def check_sleep_mode(self):
        """Check if the system is configured for s2idle"""
        fn = os.path.join("/", "sys", "power", "mem_sleep")
        if not os.path.exists(fn):
            print_color("Kernel doesn't support sleep", "❌")
            return False

        cmdline = read_file(os.path.join("/proc", "cmdline"))
        if "mem_sleep_default=deep" in cmdline:
            print_color("Kernel command line is configured for 'deep' sleep", "❌")
            self.failures += [DeepSleep()]
            return False
        if "[s2idle]" not in read_file(fn):
            self.failures += [SleepModeWrong()]
            print_color("System isn't configured for s2idle in firmware setup", "❌")
            return False
        print_color("System is configured for s2idle", "✅")
        return True

    def check_storage(self):
        """Check storage devices for s2idle support"""
        has_sata = False
        valid_nvme = {}
        invalid_nvme = {}
        valid_sata = False
        valid_ahci = False
        cmdline = read_file(os.path.join("/proc", "cmdline"))
        p = os.path.join("/", "sys", "module", "nvme", "parameters", "noacpi")
        check = os.path.exists(p) and read_file(p) == "Y"
        if ("nvme.noacpi" in cmdline) and check:
            print_color("NVME ACPI support is blocked by kernel command line", "❌")
            self.failures += [UserNvmeConfiguration()]
            return False

        if not self.kernel_log:
            message = "Unable to test storage from kernel log"
            print_color(message, "🚦")
            return True

        for dev in self.pyudev.list_devices(subsystem="pci", DRIVER="nvme"):
            # https://git.kernel.org/torvalds/c/e79a10652bbd3
            if self.minimum_kernel(6, 10):
                logging.debug("New enough kernel to avoid NVME check")
                break
            pci_slot_name = dev.properties["PCI_SLOT_NAME"]
            vendor = get_property_pyudev(dev.properties, "ID_VENDOR_FROM_DATABASE", "")
            model = get_property_pyudev(dev.properties, "ID_MODEL_FROM_DATABASE", "")
            message = f"{vendor} {model}"
            self.kernel_log.seek()
            pattern = f"{pci_slot_name}.*{Headers.NvmeSimpleSuspend}"
            if self.kernel_log.match_pattern(pattern):
                valid_nvme[pci_slot_name] = message
            if pci_slot_name not in valid_nvme:
                invalid_nvme[pci_slot_name] = message

            for dev in self.pyudev.list_devices(subsystem="ata", DRIVER="ahci"):
                has_sata = True
                break

            if has_sata:
                # Test AHCI
                self.kernel_log.seek()
                matches = ["ahci", "flags", "sds", "sadm"]
                if self.kernel_log.match_line(matches):
                    valid_ahci = True
                # Test SATA
                self.kernel_log.seek()
                matches = ["ata", "Features", "Dev-Sleep"]
                if self.kernel_log.match_line(matches):
                    valid_sata = True
        if invalid_nvme:
            for disk, name in invalid_nvme.items():
                print_color(
                    f"NVME {name.strip()} is not configured for s2idle in BIOS",
                    "❌",
                )
                num = len(invalid_nvme) + len(valid_nvme)
                self.failures += [AcpiNvmeStorageD3Enable(invalid_nvme[disk], num)]
        if valid_nvme:
            for disk, name in valid_nvme.items():
                print_color(
                    f"NVME {name.strip()} is configured for s2idle in BIOS",
                    "✅",
                )
        if has_sata:
            if valid_sata:
                print_color("SATA supports DevSlp feature", "✅")
            else:
                invalid_nvme = True
                print_color("SATA does not support DevSlp feature", "❌")
                self.failures += [DevSlpDiskIssue()]

            if valid_ahci:
                print_color("AHCI is configured for DevSlp in BIOS", "✅")
            else:
                print_color("AHCI is not configured for DevSlp in BIOS", "❌")
                self.failures += [DevSlpHostIssue()]

        return (
            (len(invalid_nvme) == 0)
            and (valid_sata or not has_sata)
            and (valid_ahci or not has_sata)
        )

    def install_ethtool(self):
        """Install ethtool if necessary"""
        try:
            _ = subprocess.call(["ethtool", "-h"], stdout=subprocess.DEVNULL) == 0
            return True
        except FileNotFoundError:
            self.show_install_message(Headers.MissingEthtool)
            package = EthtoolPackage(self.root_user)
            return package.install(self.distro)

    def check_network(self):
        """Check network devices for s2idle support"""
        ethtool = False
        for device in self.pyudev.list_devices(subsystem="net", ID_NET_DRIVER="r8169"):
            if not ethtool:
                ethtool = self.install_ethtool()
            if not ethtool:
                print_color("Ethernet checks unavailable without `ethtool`", "🚦")
                return True
            interface = device.properties.get("INTERFACE")
            cmd = ["ethtool", interface]
            wol_supported = False
            output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode(
                "utf-8"
            )
            for line in output.split("\n"):
                if "Supports Wake-on" in line:
                    val = line.split(":")[1].strip()
                    if "g" in val:
                        logging.debug("%s supports WoL", interface)
                        wol_supported = True
                    else:
                        logging.debug("%s doesn't support WoL (%s)", interface, val)
                elif "Wake-on" in line and wol_supported:
                    val = line.split(":")[1].strip()
                    if "g" in val:
                        print_color(f"{interface} has WoL enabled", "✅")
                    else:
                        print_color(
                            f"Platform may have low hardware sleep residency with Wake-on-lan disabled. Run `ethtool -s {interface} wol g` to enable it if necessary.",
                            Colors.WARNING,
                        )
        return True

    def check_device_firmware(self):
        """Check for device firmware issues"""
        try:
            import gi  # pylint: disable=redefined-outer-name,import-outside-toplevel
            from gi.repository import (
                GLib as _,
            )  # pylint: disable=import-outside-toplevel

            gi.require_version("Fwupd", "2.0")
            from gi.repository import (
                Fwupd,
            )  # pylint: disable=redefined-outer-name,import-outside-toplevel,wrong-import-position
        except ValueError:
            print_color(
                "Device firmware checks unavailable without gobject introspection",
                "🚦",
            )
            return True
        except ImportError:
            print_color(
                "Device firmware checks unavailable without gobject introspection",
                "🚦",
            )
            return True

        client = Fwupd.Client()
        devices = client.get_devices()
        for device in devices:
            # Dictionary of instance id to firmware version mappings that
            # have been "reported" to be problematic
            device_map = {
                "8c36f7ee-cc11-4a36-b090-6363f54ecac2": "0.1.26",  # https://gitlab.freedesktop.org/drm/amd/-/issues/3443
            }
            interesting_plugins = ["asus_hid", "nvme", "tpm", "uefi_capsule"]
            if device.get_plugin() in interesting_plugins:
                logging.debug(
                    "%s %s firmware version: '%s'",
                    device.get_vendor(),
                    device.get_name(),
                    device.get_version(),
                )
                logging.debug("| %s", device.get_guids())
                logging.debug("└─%s", device.get_instance_ids())
            for item, version in device_map.items():
                if (
                    item in device.get_guids() or item in device.get_instance_ids()
                ) and version in device.get_version():
                    print_color(
                        f"Platform may have problems resuming.  Upgrade the firmware for '{device.get_name()}' if you have problems.",
                        Colors.WARNING,
                    )
        return True

    def check_amd_hsmp(self):
        """Check for AMD HSMP driver"""
        # not needed to check in newer kernels
        # see https://github.com/torvalds/linux/commit/77f1972bdcf7513293e8bbe376b9fe837310ee9c
        if self.minimum_kernel(6, 10):
            logging.debug("New enough kernel to avoid HSMP check")
            return True
        f = os.path.join("/", "boot", f"config-{platform.uname().release}")
        if os.path.exists(f):
            kconfig = read_file(f)
            if "CONFIG_AMD_HSMP=y" in kconfig:
                print_color(
                    "HSMP driver `amd_hsmp` driver may conflict with amd_pmc",
                    "❌",
                )
                self.failures += [AmdHsmpBug()]
                return False

        cmdline = read_file(os.path.join("/proc", "cmdline"))
        blocked = "initcall_blacklist=hsmp_plt_init" in cmdline

        p = os.path.join("/", "sys", "module", "amd_hsmp")
        if os.path.exists(p) and not blocked:
            print_color("`amd_hsmp` driver may conflict with amd_pmc", "❌")
            self.failures += [AmdHsmpBug()]
            return False

        print_color(
            f"HSMP driver `amd_hsmp` not detected (blocked: {blocked})",
            "✅",
        )
        return True

    def check_iommu(self):
        """Check IOMMU configuration"""
        affected_1a = (
            list(range(0x20, 0x2F)) + list(range(0x60, 0x6F)) + list(range(0x70, 0x7F))
        )
        if self.cpu_family == 0x1A and self.cpu_model in affected_1a:
            found_iommu = False
            found_acpi = False
            found_dmar = False
            for dev in self.pyudev.list_devices(subsystem="iommu"):
                found_iommu = True
                logging.debug("Found IOMMU %s", dev.sys_path)
                break
            if not found_iommu:
                print_color("IOMMU disabled", "✅")
                return True
            for dev in self.pyudev.list_devices(
                subsystem="thunderbolt", DEVTYPE="thunderbolt_domain"
            ):
                p = os.path.join(dev.sys_path, "iommu_dma_protection")
                v = int(read_file(p))
                logging.debug("%s:%s", p, v)
                found_dmar = v == 1
            if not found_dmar:
                print_color(
                    "IOMMU is misconfigured: Pre-boot DMA protection not enabled", "❌"
                )
                self.failures += [DMArNotEnabled()]
                return False
            # check that MSFT0201 is present
            for dev in self.pyudev.list_devices(subsystem="acpi"):
                if "MSFT0201" in dev.sys_path:
                    found_acpi = True
            if not found_acpi:
                print_color("IOMMU is misconfigured: missing MSFT0201 ACPI device", "❌")
                self.failures += [MissingIommuACPI("MSFT0201")]
                return False
            # check that policy is bound to it
            for dev in self.pyudev.list_devices(subsystem="platform"):
                if "MSFT0201" in dev.sys_path:
                    p = os.path.join(dev.sys_path, "iommu")
                    if not os.path.exists(p):
                        self.failures += [MissingIommuPolicy("MSFT0201")]
                        return False
            print_color("IOMMU properly configured", "✅")
        return True

    def check_port_pm_override(self):
        """Check for PCIe port power management override"""
        if self.cpu_family != 0x19:
            return
        if self.cpu_model not in [0x74, 0x78]:
            return
        if version.parse(self.smu_version) > version.parse("76.60.0"):
            return
        if version.parse(self.smu_version) < version.parse("76.18.0"):
            return
        cmdline = read_file(os.path.join("/proc", "cmdline"))
        if "pcie_port_pm=off" in cmdline:
            return
        print_color(
            "Platform may hang resuming.  Upgrade your firmware or add pcie_port_pm=off to kernel command line if you have problems.",
            Colors.WARNING,
        )

    def check_wake_sources(self):
        def get_input_sibling_name(pyudev, parent):
            # input is a sibling not a parent to the wakeup
            for input in pyudev.list_devices(subsystem="input", parent=parent):
                if not "NAME" in input.properties:
                    continue
                return input.properties["NAME"]
            return ""

        devices = []
        for wake_dev in self.pyudev.list_devices(subsystem="wakeup"):
            p = os.path.join(wake_dev.sys_path, "device", "power", "wakeup")
            if not os.path.exists(p):
                continue
            wake_en = read_file(p)
            name = ""
            sys_name = wake_dev.sys_path
            # determine the type of device it hangs off of
            acpi = wake_dev.find_parent(subsystem="acpi")
            serio = wake_dev.find_parent(subsystem="serio")
            rtc = wake_dev.find_parent(subsystem="rtc")
            pci = wake_dev.find_parent(subsystem="pci")
            mhi = wake_dev.find_parent(subsystem="mhi")
            pnp = wake_dev.find_parent(subsystem="pnp")
            hid = wake_dev.find_parent(subsystem="hid")
            thunderbolt_device = wake_dev.find_parent(
                subsystem="thunderbolt", device_type="thunderbolt_device"
            )
            thunderbolt_domain = wake_dev.find_parent(
                subsystem="thunderbolt", device_type="thunderbolt_domain"
            )
            i2c = wake_dev.find_parent(subsystem="i2c")
            if i2c is not None:
                sys_name = i2c.sys_name
                name = get_input_sibling_name(self.pyudev, i2c)
            elif thunderbolt_device is not None:
                if "USB4_TYPE" in thunderbolt_device.properties:
                    name = "USB4 {type} controller".format(
                        type=thunderbolt_device.properties["USB4_TYPE"]
                    )
                sys_name = thunderbolt_device.sys_name
            elif thunderbolt_domain is not None:
                name = "Thunderbolt domain"
                sys_name = thunderbolt_domain.sys_name
            elif serio is not None:
                sys_name = serio.sys_name
                name = get_input_sibling_name(self.pyudev, serio)
            elif rtc is not None:
                sys_name = rtc.sys_name
                for _parent in self.pyudev.list_devices(
                    subsystem="platform", parent=rtc, DRIVER="alarmtimer"
                ):
                    name = "Real Time Clock alarm timer"
                    break
            elif mhi is not None:
                sys_name = mhi.sys_name
                name = "Mobile Broadband host interface"
            elif hid is not None:
                name = hid.properties["HID_NAME"]
                sys_name = hid.sys_name
            elif pci is not None:
                sys_name = pci.sys_name
                if (
                    "ID_PCI_SUBCLASS_FROM_DATABASE" in pci.properties
                    and "ID_VENDOR_FROM_DATABASE" in pci.properties
                ):
                    name = f'{pci.properties["ID_VENDOR_FROM_DATABASE"]} {pci.properties["ID_PCI_SUBCLASS_FROM_DATABASE"]}'
                else:
                    name = f"PCI {pci.properties['PCI_CLASS']}"
            elif acpi is not None:
                sys_name = acpi.sys_name
                if acpi.driver == "button":
                    for inp in self.pyudev.list_devices(subsystem="input", parent=acpi):
                        if not "NAME" in inp.properties:
                            continue
                        name = f"ACPI {inp.properties['NAME']}"
                        break
                elif acpi.driver in ["battery", "ac"]:
                    for ps in self.pyudev.list_devices(
                        subsystem="power_supply", parent=acpi
                    ):
                        if not "POWER_SUPPLY_NAME" in ps.properties:
                            continue
                        name = f"ACPI {ps.properties['POWER_SUPPLY_TYPE']}"
            elif pnp is not None:
                name = "Plug-n-play"
                if pnp.driver == "rtc_cmos":
                    name = f"{name} Real Time Clock"
                sys_name = pnp.sys_name

            name = name.replace('"', "")
            devices.append(f"{name} [{sys_name}]: {wake_en}")
        devices.sort()
        logging.debug("Wakeup sources:")
        for dev in devices:
            # set prefix if last device
            prefix = "│ " if dev != devices[-1] else "└─"
            logging.debug(f"{prefix}{dev}")
        return True

    def check_amd_pmc(self):
        """Check for the AMD PMC driver"""
        for device in self.pyudev.list_devices(subsystem="platform", DRIVER="amd_pmc"):
            message = "PMC driver `amd_pmc` loaded"
            p = os.path.join(device.sys_path, "smu_program")
            v = os.path.join(device.sys_path, "smu_fw_version")
            if os.path.exists(v):
                try:
                    self.smu_version = read_file(v)
                    self.smu_program = read_file(p)
                except TimeoutError:
                    print_color("failed to communicate using `amd_pmc` driver", "❌")
                    return False
                message += f" (Program {self.smu_program} Firmware {self.smu_version})"
            self.check_port_pm_override()
            print_color(message, "✅")
            return True
        self.failures += [MissingAmdPmc()]
        print_color("PMC driver `amd_pmc` did not bind to any ACPI device", "❌")
        return False

    def check_aspm(self):
        """Check if ASPM has been overriden"""
        p = os.path.join("/", "sys", "module", "pcie_aspm", "parameters", "policy")
        contents = read_file(p)
        policy = ""
        for word in contents.split(" "):
            if word.startswith("["):
                policy = word
                break
        if policy != "[default]":
            print_color(f"ASPM policy set to {policy}", "❌")
            self.failures += [ASpmWrong()]
            return False
        print_color("ASPM policy set to 'default'", "✅")
        return True

    def check_wlan(self):
        """Checks for WLAN device"""
        for device in self.pyudev.list_devices(subsystem="pci", PCI_CLASS="28000"):
            slot = device.properties["PCI_SLOT_NAME"]
            driver = device.properties.get("DRIVER")
            if not driver:
                print_color(f"WLAN device in {slot} missing driver", "🚦")
                self.failures += [MissingDriver(slot)]
            print_color(f"WLAN driver `{driver}` bound to {slot}", "✅")
        return True

    def check_usb3(self):
        """Check for the USB4 controller"""
        for device in self.pyudev.list_devices(subsystem="pci", PCI_CLASS="C0330"):
            slot = device.properties["PCI_SLOT_NAME"]
            if device.properties.get("DRIVER") != "xhci_hcd":
                print_color(
                    f"USB3 controller for {slot} not using `xhci_hcd` driver", "❌"
                )
                self.failures += [MissingXhciHcd()]
                return False
            print_color(f"USB3 driver `xhci_hcd` bound to {slot}", "✅")
        return True

    def check_usb4(self):
        """Check for the USB4 controller"""
        for device in self.pyudev.list_devices(subsystem="pci", PCI_CLASS="C0340"):
            slot = device.properties["PCI_SLOT_NAME"]
            if device.properties.get("DRIVER") != "thunderbolt":
                print_color(
                    f"USB4 controller for {slot} not using `thunderbolt` driver", "❌"
                )
                self.failures += [MissingThunderbolt()]
                return False
            print_color(f"USB4 driver `thunderbolt` bound to {slot}", "✅")
        return True

    def check_pinctrl_amd(self):
        """Check for the pinctrl_amd driver"""
        for _device in self.pyudev.list_devices(
            subsystem="platform", DRIVER="amd_gpio"
        ):
            print_color("GPIO driver `pinctrl_amd` available", "✅")
            p = os.path.join("/", "sys", "kernel", "debug", "gpio")
            try:
                contents = read_file(p)
            except PermissionError:
                logging.debug("Unable to capture %s", p)
                contents = None
            header = False
            if contents:
                for line in contents.split("\n"):
                    if "WAKE_INT_MASTER_REG:" in line:
                        val = "en" if int(line.split()[1], 16) & BIT(15) else "dis"
                        logging.debug("Winblue GPIO 0 debounce: %sabled", val)
                        continue
                    if not header and re.search("trigger", line):
                        logging.debug(line)
                        header = True
                    if re.search("edge", line) or re.search("level", line):
                        logging.debug(line)
                    if "🔥" in line:
                        self.failures += [UnservicedGpio()]
                        return False

            return True
        print_color("GPIO driver `pinctrl_amd` not loaded", "❌")
        return False

    def check_rtc_cmos(self):
        """Check for the RTC CMOS driver configuration"""
        p = os.path.join(
            "/", "sys", "module", "rtc_cmos", "parameters", "use_acpi_alarm"
        )
        val = read_file(p)
        if val == "N":
            print_color("RTC driver `rtc_cmos` configured to use ACPI alarm", "🚦")
            self.failures += [RtcAlarmWrong()]
            return False
        print_color("RTC driver `rtc_cmos` configured to use CMOS alarm", "✅")
        return True

    def check_amdgpu(self):
        """Check for the AMDGPU driver"""
        for device in self.pyudev.list_devices(subsystem="pci"):
            klass = device.properties.get("PCI_CLASS")
            if klass not in ["30000", "38000"]:
                continue
            pci_id = device.properties.get("PCI_ID")
            if not pci_id.startswith("1002"):
                continue
            if device.properties.get("DRIVER") != "amdgpu":
                print_color("GPU driver `amdgpu` not loaded", "❌")
                self.failures += [MissingAmdgpu()]
                return False
            slot = device.properties.get("PCI_SLOT_NAME")
            print_color(f"GPU driver `amdgpu` bound to {slot}", "✅")
        p = os.path.join("/", "sys", "module", "amdgpu", "parameters", "ppfeaturemask")
        if os.path.exists(p):
            v = read_file(p)
            if v != "0xfff7bfff":
                print_color(f"AMDGPU ppfeaturemask overridden to {v}", "❌")
                self.failures += [AmdgpuPpFeatureMask()]
                return False
        if not self.kernel_log:
            message = "Unable to test for amdgpu from kernel log"
            print_color(message, "🚦")
            return True
        self.kernel_log.seek()
        match = self.kernel_log.match_pattern("Direct firmware load for amdgpu.*failed")
        if match and not "amdgpu/isp" in match:
            print_color("GPU firmware missing", "❌")
            self.failures += [MissingAmdgpuFirmware([match])]
            return False
        return True

    def check_wcn6855_bug(self):
        """Check for the WCN6855 bug"""
        if not self.kernel_log:
            message = "Unable to test for wcn6855 bug from kernel log"
            print_color(message, "🚦")
            return True
        wcn6855 = False
        self.kernel_log.seek()
        if self.kernel_log.match_pattern("ath11k_pci.*wcn6855"):
            match = self.kernel_log.match_pattern("ath11k_pci.*fw_version")
            if match:
                logging.debug("WCN6855 version string: %s", match)
                objects = match.split()
                for i in range(0, len(objects)):
                    if objects[i] == "fw_build_id":
                        wcn6855 = objects[i + 1]

        if wcn6855:
            components = wcn6855.split(".")
            if int(components[-1]) >= 37 or int(components[-1]) == 23:
                print_color(
                    f"WCN6855 WLAN (fw build id {wcn6855})",
                    "✅",
                )
            else:
                print_color(
                    f"WCN6855 WLAN may cause spurious wakeups (fw build id {wcn6855})",
                    "❌",
                )
                self.failures += [WCN6855Bug()]

        return True

    def capture_input_wakeup_count(self):
        """Capture wakeup count for input related devices"""

        def get_wakeup_count(device):
            """Get the wakeup count for a device"""
            p = os.path.join(device.sys_path, "power", "wakeup")
            if not os.path.exists(p):
                return None
            p = os.path.join(device.sys_path, "power", "wakeup_count")
            if not os.path.exists(p):
                return None
            return read_file(p)

        if not self.use_wakeup_count:
            return

        wakeup_count = {}
        for device in self.pyudev.list_devices(subsystem="input"):
            count = get_wakeup_count(device)
            if count is not None:
                wakeup_count[device.sys_path] = count
                continue
            # iterate parents until finding one with a wakeup count
            # or no more parents
            parent = device.parent
            while parent is not None:
                count = get_wakeup_count(parent)
                if count is not None:
                    wakeup_count[parent.sys_path] = count
                    break
                parent = parent.parent

        # diff the count
        for device, count in wakeup_count.items():
            if device not in self.wakeup_count:
                continue
            if self.wakeup_count[device] == count:
                continue
            print_color(
                f"Woke up from input source {device} ({self.wakeup_count[device]}->{count})",
                "💤",
            )
        self.wakeup_count = wakeup_count

    def capture_amdgpu_ips_status(self):
        """Capture the AMDGPU IPS status"""
        for device in self.pyudev.list_devices(subsystem="pci", PCI_CLASS="38000"):
            pci_id = device.properties.get("PCI_ID")
            if not pci_id.startswith("1002"):
                continue
            slot = device.properties.get("PCI_SLOT_NAME")
            p = os.path.join(
                "/", "sys", "kernel", "debug", "dri", slot, "amdgpu_dm_ips_status"
            )
            if not os.path.exists(p):
                continue
            logging.debug("IPS status")
            try:
                lines = read_file(p).split("\n")
                for line in lines:
                    prefix = "│ " if line != lines[-1] else "└─"
                    logging.debug("%s %s", prefix, line)
            except PermissionError:
                if self.lockdown:
                    print_color(
                        "Unable to gather IPS state data due to kernel lockdown.",
                        Colors.WARNING,
                    )
                else:
                    print_color("Failed to read IPS state data", Colors.WARNING)

    def capture_lid(self):
        """Capture lid status"""
        p = os.path.join("/", "proc", "acpi", "button", "lid")
        if not os.path.exists(p):
            return
        for root, _dirs, files in os.walk(p):
            for fname in files:
                p = os.path.join(root, fname)
                state = read_file(p).split(":")[1].strip()
                logging.debug("ACPI Lid (%s): %s", p, state)

    def capture_gpes(self):
        """Capture general purpose event count"""
        base = os.path.join("/", "sys", "firmware", "acpi", "interrupts")
        for root, _dirs, files in os.walk(base, topdown=False):
            for fname in files:
                if not fname.startswith("gpe") or fname == "gpe_all":
                    continue
                target = os.path.join(root, fname)
                val = 0
                with open(target, "r") as r:
                    val = int(r.read().split()[0])
                if fname in self.gpes and self.gpes[fname] != val:
                    logging.debug(
                        "%s increased from %d to %d", fname, self.gpes[fname], val
                    )
                self.gpes[fname] = val

    def check_wakeup_irq(self):
        """Capture the wakeup IRQ to the log"""
        p = os.path.join("/", "sys", "power", "pm_wakeup_irq")
        try:
            n = int(read_file(p))
            for irq in self.irqs:
                if irq[0] == n:
                    message = f"{Headers.WokeFromIrq} {irq[0]}: {irq[1]}"
                    print_color(message, "🥱")
                    break
        except OSError:
            pass
        return True

    def check_hw_sleep(self):
        """Check for hardware sleep state"""
        result = False
        if self.hw_sleep_duration:
            result = True
        if not self.hw_sleep_duration:
            p = os.path.join("/", "sys", "power", "suspend_stats", "last_hw_sleep")
            if os.path.exists(p):
                try:
                    self.hw_sleep_duration = int(read_file(p)) / 10**6
                    if self.hw_sleep_duration > 0:
                        result = True
                except FileNotFoundError as e:
                    logging.debug(
                        "Failed to read hardware sleep data from %s: %s", p, e
                    )
        if not self.hw_sleep_duration:
            p = os.path.join("/", "sys", "kernel", "debug", "amd_pmc", "smu_fw_info")
            try:
                val = read_file(p)
                for line in val.split("\n"):
                    if "Last S0i3 Status" in line:
                        if "Success" in line:
                            result = True
                        continue
                    if "Time (in us) in S0i3" in line:
                        self.hw_sleep_duration = int(line.split(":")[1]) / 10**6
            except PermissionError:
                if self.lockdown:
                    print_color(
                        "Unable to gather hardware sleep data.",
                        Colors.WARNING,
                    )
                else:
                    print_color("Failed to read hardware sleep data", Colors.WARNING)
                return False
            except FileNotFoundError:
                print_color("HW sleep statistics file missing", "❌")
                return False
        if result:
            if self.userspace_duration:
                percent = float(
                    self.hw_sleep_duration / self.userspace_duration.total_seconds()
                )
            else:
                percent = 0
            if percent and self.userspace_duration.total_seconds() >= 60:
                if percent > 0.9:
                    symbol = "✅"
                else:
                    symbol = "❌"
                    self.failures += [
                        LowHardwareSleepResidency(
                            self.userspace_duration.total_seconds(), percent
                        )
                    ]
            else:
                symbol = "💤"
            percent_msg = "" if not percent else f"({percent:.2%})"
            print_color(
                f"In a hardware sleep state for {timedelta(seconds=self.hw_sleep_duration)} {percent_msg}",
                symbol,
            )
        else:
            print_color("Did not reach hardware sleep state", "❌")
        return result

    def check_permissions(self):
        """Check for permissions"""
        p = os.path.join("/", "sys", "power", "state")
        try:
            with open(p, "w") as w:
                pass
        except PermissionError:
            print_color(f"{Headers.RootError}", "👀")
            return False
        return True

    def check_i2c_hid(self):
        """Check for I2C HID devices"""
        devices = []
        for dev in self.pyudev.list_devices(subsystem="input"):
            if "NAME" not in dev.properties:
                continue
            parent = dev.find_parent(subsystem="i2c")
            if parent is None:
                continue
            devices.append(dev)
        if not devices:
            return True
        logging.debug("I2C HID devices")
        for dev in devices:
            name = dev.properties["NAME"]
            parent = dev.find_parent(subsystem="i2c")
            p = os.path.join(parent.sys_path, "firmware_node", "path")
            if os.path.exists(p):
                acpi_path = read_file(p)
            else:
                acpi_path = ""
            p = os.path.join(parent.sys_path, "firmware_node", "hid")
            if os.path.exists(p):
                acpi_hid = read_file(p)
            else:
                acpi_hid = ""
            # set prefix if last device
            prefix = "│ " if dev != devices[-1] else "└─"
            logging.debug("%s%s [%s] : %s", prefix, name, acpi_hid, acpi_path)
            if "IDEA5002" in name:
                remediation = (
                    "echo {} | sudo tee /sys/bus/i2c/drivers/{}/unbind".format(
                        parent.sys_path.split("/")[-1], parent.driver
                    )
                )

                print_color(
                    f"{name} may cause spurious wakeups",
                    "❌",
                )
                self.failures += [I2CHidBug(name, remediation)]
                return False
        return True

    def map_acpi_path(self):
        """Map of ACPI devices to ACPI paths"""
        devices = []
        for dev in self.pyudev.list_devices(subsystem="acpi"):
            p = os.path.join(dev.sys_path, "path")
            if not os.path.exists(p):
                continue
            p = os.path.join(dev.sys_path, "status")
            if os.path.exists(p):
                status = int(read_file(p))
                if status == 0:
                    continue
            devices.append(dev)
        logging.debug("ACPI name: ACPI path [driver]")
        for dev in devices:
            if dev == devices[-1]:
                prefix = "└─"
            else:
                prefix = "│ "
            p = os.path.join(dev.sys_path, "path")
            pth = read_file(p)
            p = os.path.join(dev.sys_path, "physical_node", "driver")
            if os.path.exists(p):
                driver = os.path.basename(os.readlink(p))
            else:
                driver = None
            logging.debug("%s%s: %s [%s]", prefix, dev.sys_name, pth, driver)
        return True

    def map_acpi_pci(self):
        """Map ACPI devices to PCI devices"""
        devices = []
        for dev in self.pyudev.list_devices(subsystem="pci"):
            devices.append(dev)
        logging.debug("PCI devices")
        for dev in devices:
            pci_id = dev.properties["PCI_ID"].lower()
            pci_slot_name = dev.properties["PCI_SLOT_NAME"]
            database_class = get_property_pyudev(
                dev.properties, "ID_PCI_SUBCLASS_FROM_DATABASE", ""
            )
            database_vendor = get_property_pyudev(
                dev.properties, "ID_VENDOR_FROM_DATABASE", ""
            )
            if dev.parent.subsystem != "pci":
                if dev == devices[-1]:
                    prefix = "└─"
                else:
                    prefix = "│ "
            else:
                if dev == devices[-1]:
                    prefix = "└─"
                else:
                    prefix = "├─ "
            p = os.path.join(dev.sys_path, "firmware_node", "path")
            if os.path.exists(p):
                acpi = read_file(p)
                logging.debug(
                    "%s%s : %s %s [%s] : %s",
                    prefix,
                    pci_slot_name,
                    database_vendor,
                    database_class,
                    pci_id,
                    acpi,
                )
            else:
                logging.debug(
                    "%s%s : %s %s [%s]",
                    prefix,
                    pci_slot_name,
                    database_vendor,
                    database_class,
                    pci_id,
                )
        return True

    def capture_irq(self):
        """Capture the IRQs to the log"""
        p = os.path.join("/sys", "kernel", "irq")
        for directory in os.listdir(p):
            if os.path.isdir(os.path.join(p, directory)):
                wake = WakeIRQ(directory, self.pyudev)
                self.irqs.append([int(directory), str(wake)])
        self.irqs.sort()
        logging.debug("Interrupts")
        for irq in self.irqs:
            # set prefix if last IRQ
            prefix = "│ " if irq != self.irqs[-1] else "└─"
            logging.debug("%s%s: %s", prefix, irq[0], irq[1])
        return True

    def capture_acpi(self):
        """Capture ACPI tables to debug"""
        if not self.iasl:
            print_color(Headers.MissingIasl, Colors.WARNING)
            return True
        if not self.root_user:
            logging.debug("Unable to capture ACPI tables without root")
            return True
        base = os.path.join("/", "sys", "firmware", "acpi", "tables")
        for root, _dirs, files in os.walk(base, topdown=False):
            for fname in files:
                target = os.path.join(root, fname)
                # capture all DSDT/SSDT when run with --acpidump
                if self.acpidump:
                    if not "DSDT" in fname and not "SSDT" in fname:
                        continue
                else:
                    with open(target, "rb") as f:
                        s = f.read()
                        if s.find(b"_AEI") < 0:
                            continue
                try:
                    tmpd = tempfile.mkdtemp()
                    prefix = os.path.join(tmpd, "acpi")
                    subprocess.check_call(
                        ["iasl", "-p", prefix, "-d", target],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    capture_file_to_debug(f"{prefix}.dsl")
                except subprocess.CalledProcessError as e:
                    print_color(f"Failed to capture ACPI table: {e.output}", "👀")
                finally:
                    shutil.rmtree(tmpd)
        return True

    def capture_linux_firmware(self):
        """Capture the Linux firmware to debug"""
        if self.distro in ("ubuntu", "debian"):
            cache = apt.Cache()
            packages = ["linux-firmware"]
            for obj in cache.get_providing_packages("amdgpu-firmware-nda"):
                packages += [obj.name]
            for p in packages:
                pkg = cache.get(p)
                if not pkg:
                    continue
                changelog = ""
                if "amdgpu" in p:
                    for f in pkg.installed_files:
                        if not "changelog" in f:
                            continue
                        changelog = gzip.GzipFile(f).read().decode("utf-8")
                if changelog:
                    for line in changelog.split("\n"):
                        logging.debug(line)
                else:
                    logging.debug(pkg.installed)

        for num in range(0, 2):
            p = os.path.join(
                "/", "sys", "kernel", "debug", "dri", f"{num}", "amdgpu_firmware_info"
            )
            if os.path.exists(p):
                capture_file_to_debug(p)
        return True

    def capture_command_line(self):
        """Capture the kernel command line to debug"""
        cmdline = read_file(os.path.join("/proc", "cmdline"))
        # borrowed from https://github.com/fwupd/fwupd/blob/1.9.5/libfwupdplugin/fu-common-linux.c#L95
        filtered = [
            "apparmor",
            "audit",
            "auto",
            "boot",
            "BOOT_IMAGE",
            "console",
            "crashkernel",
            "cryptdevice",
            "cryptkey",
            "dm",
            "earlycon",
            "earlyprintk",
            "ether",
            "initrd",
            "ip",
            "LANG",
            "loglevel",
            "luks.key",
            "luks.name",
            "luks.options",
            "luks.uuid",
            "mitigations",
            "mount.usr",
            "mount.usrflags",
            "mount.usrfstype",
            "netdev",
            "netroot",
            "nfsaddrs",
            "nfs.nfs4_unique_id",
            "nfsroot",
            "noplymouth",
            "ostree",
            "quiet",
            "rd.dm.uuid",
            "rd.luks.allow-discards",
            "rd.luks.key",
            "rd.luks.name",
            "rd.luks.options",
            "rd.luks.uuid",
            "rd.lvm.lv",
            "rd.lvm.vg",
            "rd.md.uuid",
            "rd.systemd.mask",
            "rd.systemd.wants",
            "resume",
            "resumeflags",
            "rhgb",
            "ro",
            "root",
            "rootflags",
            "roothash",
            "rw",
            "security",
            "showopts",
            "splash",
            "swap",
            "systemd.mask",
            "systemd.show_status",
            "systemd.unit",
            "systemd.verity_root_data",
            "systemd.verity_root_hash",
            "systemd.wants",
            "udev.log_priority",
            "verbose",
            "vt.handoff",
            "zfs",
        ]
        # remove anything that starts with something in filtered from cmdline
        cmdline = " ".join(
            [x for x in cmdline.split() if not x.startswith(tuple(filtered))]
        )
        logging.debug("/proc/cmdline: %s", cmdline)
        return True

    def capture_logind(self):
        """Capture the logind configuration to debug"""
        base = os.path.join("/", "etc", "systemd", "logind.conf")
        if not os.path.exists(base):
            return True

        config = configparser.ConfigParser()
        config.read(base)
        section = config["Login"]
        if not section.keys():
            logging.debug("LOGIND: no configuration changes")
            return True
        logging.debug("LOGIND: configuration changes:")
        for key in section.keys():
            logging.debug("\t%s: %s", key, section[key])
        return True

    def capture_running_compositors(self):
        """Capture information about known compositor processes found"""

        known_compositors = [
            "kwin_wayland",
            "gnome-shell",
            "cosmic-session",
            "hyprland",
        ]

        # Get a list of all process directories in /proc
        process_dirs = glob.glob("/proc/[0-9]*")

        # Extract and print the process names
        for proc_dir in process_dirs:
            p = os.path.join(proc_dir, "exe")
            if not os.path.exists(p):
                continue
            exe = os.path.basename(os.readlink(p)).split()[0]
            if exe in known_compositors:
                logging.debug("%s compositor is running", exe)

        return True

    def capture_disabled_pins(self):
        """Capture disabled pins from pinctrl-amd"""
        base = os.path.join("/", "sys", "module", "gpiolib_acpi", "parameters")
        for parameter in ["ignore_wake", "ignore_interrupt"]:
            f = os.path.join(base, parameter)
            if not os.path.exists(f):
                continue
            with open(f, "r") as r:
                d = r.read().rstrip()
                if d == "(null)":
                    logging.debug("%s is not configured", f)
                else:
                    logging.debug("%s is configured to %s", f, d)
        return True

    def capture_full_dmesg(self):
        """Capture the full dmesg output"""
        if not self.kernel_log:
            message = "Unable to analyze kernel log"
            print_color(message, Colors.WARNING)
            return
        self.kernel_log.capture_full_dmesg()

    def check_logger(self):
        """Check if the kernel log is available"""
        if isinstance(self.kernel_log, SystemdLogger):
            print_color("Logs are provided via systemd", "✅")
        elif isinstance(self.kernel_log, DmesgLogger):
            print_color(
                "🚦Logs are provided via dmesg, timestamps may not be accurate over multiple cycles",
                Colors.WARNING,
            )
            header = self.kernel_log.capture_header()
            if not header.startswith("Linux version"):
                print_color(
                    "Kernel ringbuffer has wrapped, unable to accurately validate pre-requisites",
                    "❌",
                )
                self.failures += [KernelRingBufferWrapped()]
                return False
        else:
            return False
        return True

    def check_logind(self):
        """Check if logind is available and can suspend"""
        if not self.logind:
            return True
        if not DBUS:
            print_color("Unable to import dbus", "❌")
            return False
        try:
            bus = dbus.SystemBus()
            obj = bus.get_object("org.freedesktop.login1", "/org/freedesktop/login1")
            intf = dbus.Interface(obj, "org.freedesktop.login1.Manager")
            if intf.CanSuspend() != "yes":
                print_color("Unable to suspend with logind", "❌")
                return False
        except dbus.exceptions.DBusException as e:
            print_color(f"Unable to communicate with logind: {e}", "❌")
            return False
        return True

    def check_power_profile(self):
        """Check the power profiles"""
        cmd = ["/usr/bin/powerprofilesctl"]
        if os.path.exists(cmd[0]):
            try:
                output = subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode(
                    "utf-8"
                )
                logging.debug("Power profiles:")
                for line in output.split("\n"):
                    logging.debug(" %s", line)
            except subprocess.CalledProcessError as e:
                logging.debug("Failed to run powerprofilesctl: %s", e.output)
        return True

    def check_taint(self):
        """Check if the kernel is tainted"""
        fn = os.path.join("/", "proc", "sys", "kernel", "tainted")
        taint = int(read_file(fn))
        # ignore kernel warnings
        taint &= ~BIT(9)
        if taint != 0:
            print_color(f"Kernel is tainted: {taint}", "❌")
            self.failures += [TaintedKernel()]
            return False
        return True

    def prerequisites(self):
        """Check the prerequisites for the system"""
        print_color(Headers.Info, Colors.HEADER)
        info = [
            self.capture_smbios,
            self.capture_kernel_version,
            self.check_battery,
            self.check_thermal,
        ]
        for i in info:
            i()

        print_color(Headers.Prerequisites, Colors.HEADER)
        checks = [
            self.check_logger,
            self.check_cpu,
            self.check_aspm,
            self.check_smt,
            self.check_lps0,
            self.check_fadt,
            self.capture_disabled_pins,
            self.capture_command_line,
            self.capture_logind,
            self.capture_running_compositors,
            self.check_amd_hsmp,
            self.check_amd_pmc,
            self.check_usb3,
            self.check_usb4,
            self.check_wlan,
            self.cpu_offers_hpet_wa,
            self.check_amdgpu,
            self.check_sleep_mode,
            self.check_storage,
            self.check_pinctrl_amd,
            self.check_device_firmware,
            self.check_network,
            self.check_wcn6855_bug,
            self.check_lockdown,
            self.check_msr,
            self.check_iommu,
            self.capture_linux_firmware,
            self.map_acpi_pci,
            self.map_acpi_path,
            self.capture_irq,
            self.check_i2c_hid,
            self.check_wake_sources,
            self.check_asus_rog_ally,
            self.capture_acpi,
            self.check_logind,
            self.check_power_profile,
            self.check_rtc_cmos,
            self.check_taint,
            self.check_permissions,
        ]
        result = True
        for check in checks:
            if not check():
                result = False
        if not result:
            print_color(Headers.BrokenPrerequisites, Colors.UNDERLINE)
            self.capture_full_dmesg()
        return result

    def check_lockdown(self):
        """Check if the kernel is in lockdown mode"""
        fn = os.path.join("/", "sys", "kernel", "security", "lockdown")
        try:
            lockdown = read_file(fn)
        except FileNotFoundError:
            logging.debug("Lockdown not available")
            return True
        logging.debug("Lockdown: %s", lockdown)
        if lockdown.split()[0] != "[none]":
            self.lockdown = True
        return True

    def minimum_kernel(self, major, minor):
        """Checks if the kernel version is at least major.minor"""
        if self.kernel_major > major:
            return True
        if self.kernel_major < major:
            return False
        return self.kernel_minor >= minor

    def toggle_dynamic_debugging(self, enable):
        """Enable or disable dynamic debugging"""
        try:
            fn = os.path.join("/", "sys", "kernel", "debug", "dynamic_debug", "control")
            setting = "+" if enable else "-"
            if not self.minimum_kernel(6, 2):
                with open(fn, "w") as w:
                    w.write(f"file drivers/acpi/x86/s2idle.c {setting}p")
            if not self.minimum_kernel(6, 5):
                # only needed if missing https://github.com/torvalds/linux/commit/c9a236419ff936755eb5db8a894c3047440e65a8
                with open(fn, "w") as w:
                    w.write(f"file drivers/pinctrl/pinctrl-amd.c {setting}p")
                # only needed if missing https://github.com/torvalds/linux/commit/b77505ed8a885c67a589c049c38824082a569068
                with open(fn, "w") as w:
                    w.write(f"file drivers/platform/x86/amd/pmc.c {setting}p")
            if self.debug_ec:
                with open(fn, "w") as w:
                    w.write(f"file drivers/acpi/ec.c {setting}p")
        except PermissionError:
            # caught by lockdown test
            pass

    def _analyze_kernel_log_line(self, line):
        """Analyze a line from the kernel log"""
        if "Timekeeping suspended for" in line:
            self.cycle_count += 1
            for f in line.split():
                try:
                    self.kernel_duration += float(f)
                except ValueError:
                    pass
        elif "Successfully transitioned to state" in line:
            self.upep = True
            if "Successfully transitioned to state lps0 ms entry" in line:
                self.upep_microsoft = True
        elif "_DSM function" in line:
            self.upep = True
            if "_DSM function 7" in line:
                self.upep_microsoft = True
        elif "PM: suspend entry" in line:
            self.suspend_count += 1
        elif "Last suspend in deepest state for" in line:
            for f in line.split():
                if not f.endswith("us"):
                    continue
                try:
                    self.hw_sleep_duration += float(f.strip("us")) / 10**6
                except ValueError:
                    pass
        elif "Triggering wakeup from IRQ" in line:
            irq = int(line.split()[-1])
            if irq and irq not in self.wakeup_irqs:
                self.wakeup_irqs += [irq]
        elif "SMU idlemask s0i3" in line:
            self.idle_masks += [line.split()[-1]]
        elif "ACPI BIOS Error" in line or "ACPI Error" in line:
            self.acpi_errors += [line]
        elif re.search("GPIO.*is active", line):
            self.active_gpios += re.findall(
                r"\d+", re.search("GPIO.*is active", line).group()
            )
        elif Headers.Irq1Workaround in line:
            self.irq1_workaround = True
        # evmisc-0132 ev_queue_notify_reques: Dispatching Notify on [UBTC] (Device) Value 0x80 (Status Change) Node 0000000080144eee
        elif "Dispatching Notify on" in line:
            # add device without the [] to notify_devices if it's not already there
            device = re.search(r"\[(.*?)\]", line)
            if device:
                device = device.group(1)
                if device not in self.notify_devices:
                    self.notify_devices += [device]
        # AMD-Vi: Event logged [IO_PAGE_FAULT device=0000:00:0c.0 domain=0x0000 address=0x7e800000 flags=0x0050]
        elif "Event logged [IO_PAGE_FAULT" in line:
            # get the device from string
            device = re.search(r"device=(.*?) domain", line)
            if device:
                device = device.group(1)
                if device not in self.page_faults:
                    self.page_faults += [device]

        logging.debug(line)

    def cpu_offers_hpet_wa(self):
        """Check if the CPU offers the HPET workaround"""
        show_warning = False
        if self.cpu_family == 0x17:
            if self.cpu_model in [0x68, 0x60]:
                show_warning = True
        elif self.cpu_family == 0x19:
            if self.cpu_model == 0x50:
                if self.smu_version:
                    show_warning = version.parse(self.smu_version) < version.parse(
                        "64.53.0"
                    )
        if show_warning:
            print_color(
                "Timer based wakeup doesn't work properly for your ASIC/firmware, please manually wake the system",
                Colors.WARNING,
            )
        return True

    def cpu_needs_irq1_wa(self):
        """Check if the CPU needs the IRQ1 workaround"""
        if self.cpu_family == 0x17:
            if self.cpu_model in [0x68, 0x60]:
                return True
        elif self.cpu_family == 0x19:
            if self.cpu_model == 0x50:
                return version.parse(self.smu_version) < version.parse("64.66.0")
        return False

    def analyze_kernel_log(self):
        """Analyze the kernel log for the last cycle"""
        self.suspend_count = 0
        self.cycle_count = 0
        self.upep = False
        self.upep_microsoft = False
        self.wakeup_irqs = []
        self.notify_devices = []
        self.idle_masks = []
        self.acpi_errors = []
        self.active_gpios = []
        self.page_faults = []
        self.irq1_workaround = False
        self.kernel_log.seek(self.last_suspend)
        self.kernel_log.process_callback(self._analyze_kernel_log_line)

        if self.suspend_count:
            print_color(
                f"Suspend count: {self.suspend_count}",
                "💤",
            )

        if self.cycle_count:
            print_color(
                f"Hardware sleep cycle count: {self.cycle_count}",
                "💤",
            )
        if self.active_gpios:
            print_color(f"GPIOs active: {self.active_gpios}", "○")
        if self.wakeup_irqs:
            for n in self.wakeup_irqs:
                for irq in self.irqs:
                    if irq[0] == int(n):
                        print_color(
                            f"{Headers.WakeTriggeredIrq} {irq[0]}: {irq[1]}", "🥱"
                        )
            if 1 in self.wakeup_irqs and self.cpu_needs_irq1_wa():
                if self.irq1_workaround:
                    print_color("Kernel workaround for IRQ1 issue utilized", "✅")
                else:
                    print_color("IRQ1 found during wakeup", Colors.WARNING)
                    self.failures += [Irq1Workaround()]
        if self.idle_masks:
            bit_changed = 0
            for i, mask_i in enumerate(self.idle_masks):
                for _j, mask_j in enumerate(self.idle_masks[i:], start=i):
                    if mask_i != mask_j:
                        bit_changed = bit_changed | (int(mask_i, 16) & ~int(mask_j, 16))
            if bit_changed:
                for bit in range(0, 31):
                    if bit_changed & BIT(bit):
                        print_color(
                            "Idle mask bit %d (0x%x) changed during suspend"
                            % (bit, BIT(bit)),
                            "○",
                        )
        if self.upep:
            if self.upep_microsoft:
                logging.debug("Used Microsoft uPEP GUID in LPS0 _DSM")
            else:
                logging.debug("Used AMD uPEP GUID in LPS0 _DSM")
        if self.acpi_errors:
            print_color("ACPI BIOS errors found", "❌")
            self.failures += [AcpiBiosError(self.acpi_errors)]
        if self.page_faults:
            print_color("Page faults found", "❌")
            self.failures += [IommuPageFault(self.page_faults)]
        if self.notify_devices:
            print_color(
                f"Notify devices {self.notify_devices} found during suspend", "💤"
            )

    def analyze_masks(self):
        try:
            from common import (
                add_model_checks,
            )  # pylint: disable=import-outside-toplevel

            func = add_model_checks(self.cpu_model, self.cpu_family)
            for mask in self.idle_masks:
                func(mask)
        except ImportError:
            pass

    def analyze_duration(self):
        """Analyze the duration of the last cycle"""
        now = datetime.now()
        self.userspace_duration = now - self.last_suspend
        min_suspend_duration = timedelta(seconds=self.requested_duration * 0.9)
        expected_wake_time = self.last_suspend + min_suspend_duration
        if now > expected_wake_time:
            logging.debug("Userspace suspended for %s", self.userspace_duration)
        else:
            print_color(
                f"Userspace suspended for {self.userspace_duration} (< minimum expected {min_suspend_duration})",
                "❌",
            )
            self.failures += [SpuriousWakeup(self.requested_duration)]
        if self.kernel_duration:
            if self.userspace_duration:
                percent = (
                    float(self.kernel_duration)
                    / self.userspace_duration.total_seconds()
                )
            else:
                percent = 0
            logging.debug(
                "Kernel suspended for total of %s (%.2f%%)",
                timedelta(seconds=self.kernel_duration),
                percent * 100,
            )

    def analyze_results(self):
        """Analyze the results of the last cycle"""
        print_color(Headers.LastCycleResults, Colors.HEADER)
        checks = [
            self.analyze_kernel_log,
            self.check_wakeup_irq,
            self.capture_gpes,
            self.capture_lid,
            self.check_hw_sleep,
            self.check_battery,
            self.check_thermal,
            self.capture_input_wakeup_count,
        ]
        for check in checks:
            check()

    def run_countdown(self, prefix, t):
        """Run a countdown timer"""
        msg = ""
        while t > 0:
            msg = f"{prefix} in {timedelta(seconds=t)}"
            print(msg, end="\r", flush=True)
            time.sleep(1)
            t -= 1
        print(" " * len(msg), end="\r")

    @pm_debugging
    def execute_suspend(self):
        """Execute the suspend operation"""
        if self.logind:
            try:
                bus = dbus.SystemBus()
                obj = bus.get_object(
                    "org.freedesktop.login1", "/org/freedesktop/login1"
                )
                intf = dbus.Interface(obj, "org.freedesktop.login1.Manager")
                propf = dbus.Interface(obj, "org.freedesktop.DBus.Properties")
                intf.Suspend(True)
                while propf.Get("org.freedesktop.login1.Manager", "PreparingForSleep"):
                    time.sleep(1)
                return True
            except dbus.exceptions.DBusException as e:
                print_color(f"Unable to communicate with logind: {e}", "❌")
                return False
        else:
            if self.use_wakeup_count:
                p = os.path.join("/", "sys", "power", "wakeup_count")
                f = read_file(p)
                try:
                    with open(p, "w", encoding="utf-8") as w:
                        w.write(str(int(f)))
                except OSError as e:
                    print_color("Failed to set wakeup count", "❌")
                    logging.debug(e)
                    return False
            p = os.path.join("/", "sys", "power", "state")
            try:
                with open(p, "w") as fd:
                    fd.write("mem")
            except OSError as e:
                print_color("Failed to suspend", "❌")
                logging.debug(e)
                return False
        return True

    def unlock_session(self):
        """Unlock the session after suspend"""
        if self.logind:
            try:
                bus = dbus.SystemBus()
                obj = bus.get_object(
                    "org.freedesktop.login1", "/org/freedesktop/login1"
                )
                intf = dbus.Interface(obj, "org.freedesktop.login1.Manager")
                intf.UnlockSessions()
            except dbus.exceptions.DBusException as e:
                print_color(f"Unable to communicate with logind: {e}", "❌")
                return False
        return True

    def check_asus_rog_ally(self):
        """Check for MCU version on ASUS ROG Ally devices"""
        for dev in self.pyudev.list_devices(subsystem="hid", DRIVER="asus_rog_ally"):
            p = os.path.join(dev.sys_path, "mcu_version")
            if not os.path.exists(p):
                continue
            v = int(read_file(p))
            hid_id = get_property_pyudev(dev.properties, "HID_ID", "")
            if "1ABE" in hid_id:
                minv = 319
            elif "1B4C" in hid_id:
                minv = 313
            else:
                minv = None
            if minv and v < minv:
                print_color(Headers.RogAllyMcuOld, "❌")
                self.failures += [RogAllyOldMcu(minv, v)]
                return False
            else:
                logging.debug("ASUS ROG MCU found with MCU version %d", v)
        for dev in self.pyudev.list_devices(subsystem="firmware-attributes"):
            p = os.path.join(
                dev.sys_path, "attributes", "mcu_powersave", "current_value"
            )
            if not os.path.exists(p):
                continue
            v = int(read_file(p))
            if v < 1:
                print_color(Headers.RogAllyPowerSave, "❌")
                self.failures += [RogAllyMcuPowerSave()]
                return False

        return True

    def test_suspend(self, duration, count, wait):
        """Test suspend for a given duration"""
        if not count:
            return True

        if count > 1:
            length = timedelta(seconds=(duration + wait) * count)
            print_color(
                f"Running {count} cycles (Test finish expected @ {datetime.now() + length})",
                Colors.HEADER,
            )

        self.requested_duration = duration
        logging.debug(
            "%s %s", Headers.SuspendDuration, timedelta(seconds=self.requested_duration)
        )
        wakealarm = None
        for device in self.pyudev.list_devices(subsystem="rtc"):
            wakealarm = os.path.join(device.sys_path, "wakealarm")
        self.toggle_dynamic_debugging(True)

        for i in range(1, count + 1):
            self.capture_gpes()
            self.capture_lid()
            self.capture_input_wakeup_count()
            self.capture_amdgpu_ips_status()
            self.run_countdown("Suspending system", wait / 2)
            self.last_suspend = datetime.now()
            self.kernel_duration = 0
            self.hw_sleep_duration = 0
            if count > 1:
                header = f"{Headers.CycleCount} {i}: "
            else:
                header = ""
            print_color(
                "{header}Started at {start} (cycle finish expected @ {finish})".format(
                    header=header,
                    start=self.last_suspend,
                    finish=datetime.now()
                    + timedelta(seconds=self.requested_duration + wait),
                ),
                Colors.HEADER,
            )
            if wakealarm:
                try:
                    with open(wakealarm, "w") as w:
                        w.write("0")
                    with open(wakealarm, "w") as w:
                        w.write(f"+{self.requested_duration}\n")
                except OSError as e:
                    print_color(
                        "Failed to program wakealarm, please manually wake system", "🚦"
                    )
                    logging.debug(e)
            else:
                print_color("No RTC device found, please manually wake system", "🚦")
            if self.execute_suspend():
                self.unlock_session()
                self.analyze_duration()
                self.run_countdown("Collecting data", wait / 2)
                self.analyze_results()
        self.toggle_dynamic_debugging(False)
        return True

    def get_failure_report(self):
        """Print the failure report"""
        if len(self.failures) == 0:
            return True
        print_color(Headers.ExplanationReport, Colors.HEADER)
        for item in self.failures:
            item.get_failure()
        return False


def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Test for common s2idle problems on systems with AMD processors.",
        epilog="Arguments are optional, and if they are not provided will prompted.\n"
        "To use non-interactively, please populate all optional arguments.",
    )
    parser.add_argument(
        "--log",
        help=Headers.LogDescription,
    )
    parser.add_argument(
        "--duration",
        help=Headers.DurationDescription,
    )
    parser.add_argument(
        "--wait",
        help=Headers.WaitDescription,
    )
    parser.add_argument(
        "--kernel-log-provider",
        default="auto",
        choices=["auto", "systemd", "dmesg"],
        help="Kernel log provider",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Run suspend test even if prerequisites failed",
    )
    parser.add_argument("--count", help=Headers.CountDescription)
    parser.add_argument(
        "--acpidump",
        action="store_true",
        help="Include and extract full ACPI dump in report",
    )
    parser.add_argument(
        "--logind", action="store_true", help="Use logind to suspend system"
    )
    parser.add_argument(
        "--wakeup-count", action="store_true", help="Monitor wakeup count"
    )
    parser.add_argument("--debug-ec", action="store_true", help=Headers.EcDebugging)
    return parser.parse_args()


def configure_log(logf):
    """Configure the log file"""
    if not logf:
        fname = f"{Defaults.log_prefix}-{date.today()}.{Defaults.log_suffix}"
        logf = input(f"{Headers.LogDescription} (default {fname})? ")
        if not logf:
            logf = fname

    # for saving a log file for analysis
    logging.basicConfig(
        format="%(asctime)s %(levelname)s:\t%(message)s",
        filename=logf,
        filemode="w",
        level=logging.DEBUG,
    )


def configure_suspend(duration, wait, count):
    """Configure the suspend test arguments"""
    if not duration:
        duration = input(
            f"{Headers.DurationDescription} (default {Defaults.duration})? "
        )
        if not duration:
            duration = Defaults.duration
    if not wait:
        wait = input(f"{Headers.WaitDescription} (default {Defaults.wait})? ")
        if not wait:
            wait = Defaults.wait
    if not count:
        count = input(f"{Headers.CountDescription} (default {Defaults.count})? ")
        if not count:
            count = Defaults.count
    return [int(duration), int(wait), int(count)]


if __name__ == "__main__":
    arg = parse_args()
    try:
        configure_log(arg.log)
    except KeyboardInterrupt:
        print("")
        sys.exit(0)

    if arg.logind and not DBUS:
        fatal_error("Unable to use logind without dbus, please install python3-dbus")

    app = S0i3Validator(
        arg.acpidump,
        arg.logind,
        arg.debug_ec,
        arg.kernel_log_provider,
        arg.wakeup_count,
    )
    if app.prerequisites() or arg.force:
        try:
            d, w, c = configure_suspend(
                duration=arg.duration, wait=arg.wait, count=arg.count
            )
        except KeyboardInterrupt:
            print("")
            sys.exit(0)
        app.test_suspend(duration=d, wait=w, count=c)
    app.get_failure_report()

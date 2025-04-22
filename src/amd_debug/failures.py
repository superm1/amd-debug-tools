#!/usr/bin/python3
# SPDX-License-Identifier: MIT

from datetime import timedelta
from amd_debug.common import print_color


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
            print(f"For more information on this failure see:{self.url}")

    def get_description(self) -> str:
        """Returns the description of the failure"""
        return self.description

    def __str__(self) -> str:
        if self.url:
            url = f"For more information on this failure see:{self.url}"
        else:
            url = ""
        return f"{self.explanation}{url}"


class RtcAlarmWrong(S0i3Failure):
    """RTC alarm is not configured to use ACPI"""

    def __init__(self):
        super().__init__()
        self.description = "rtc_cmos is not configured to use ACPI alarm"
        self.explanation = (
            "Some problems can occur during wakeup cycles if the HPET RTC "
            "emulation is used to wake systems. This can manifest in "
            "unexpected wakeups or high power consumption."
        )
        self.url = "https://github.com/systemd/systemd/issues/24279"


class MissingAmdgpu(S0i3Failure):
    """AMDGPU driver is missing"""

    def __init__(self):
        super().__init__()
        self.description = "AMDGPU driver is missing"
        self.explanation = (
            "The amdgpu driver is used for hardware acceleration as well "
            "as coordination of the power states for certain IP blocks on the SOC. "
            "Be sure that you have enabled CONFIG_AMDGPU in your kernel."
        )


class MissingAmdgpuFirmware(S0i3Failure):
    """AMDGPU firmware is missing"""

    def __init__(self, errors):
        super().__init__()
        self.description = "AMDGPU firmware is missing"
        self.explanation = (
            "The amdgpu driver loads firmware from /lib/firmware/amdgpu "
            "In some cases missing firmware will prevent a successful "
            "suspend cycle."
            "Upgrade to a newer snapshot at https://gitlab.com/kernel-firmware/linux-firmware"
        )
        self.url = "https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=1053856"
        for error in errors:
            self.explanation += f"{error}"


class AmdgpuPpFeatureMask(S0i3Failure):
    """AMDGPU ppfeaturemask has been changed"""

    def __init__(self):
        super().__init__()
        self.description = "AMDGPU ppfeaturemask changed"
        self.explanation = (
            "The ppfeaturemask for the amdgpu driver has been changed "
            "Modifying this from the defaults may cause the system to not "
            "enter hardware sleep."
        )
        self.url = "https://gitlab.freedesktop.org/drm/amd/-/issues/2808#note_2379968"


class MissingAmdPmc(S0i3Failure):
    """AMD-PMC driver is missing"""

    def __init__(self):
        super().__init__()
        self.description = "AMD-PMC driver is missing"
        self.explanation = (
            "The amd-pmc driver is required for the kernel to instruct the "
            "soc to enter the hardware sleep state. "
            "Be sure that you have enabled CONFIG_AMD_PMC in your kernel. "
            ""
            "If CONFIG_AMD_PMC is enabled but the amd-pmc driver isn't loading "
            "then you may have found a bug and should report it."
        )


class MissingThunderbolt(S0i3Failure):
    """Thunderbolt driver is missing"""

    def __init__(self):
        super().__init__()
        self.description = "thunderbolt driver is missing"
        self.explanation = (
            "The thunderbolt driver is required for the USB4 routers included "
            "with the SOC to enter the proper power states. "
            "Be sure that you have enabled CONFIG_USB4 in your kernel."
        )


class MissingXhciHcd(S0i3Failure):
    """xhci_hcd driver is missing"""

    def __init__(self):
        super().__init__()
        self.description = "xhci_hcd driver is missing"
        self.explanation = (
            "The xhci_hcd driver is required for the USB3 controllers included "
            "with the SOC to enter the proper power states. "
            "Be sure that you have enabled CONFIG_XHCI_PCI in your kernel."
        )


class MissingDriver(S0i3Failure):
    """driver is missing"""

    def __init__(self, slot):
        super().__init__()
        self.description = f"{slot} driver is missing"
        self.explanation = (
            f"No driver has been bound to PCI device {slot} "
            "Without a driver, the hardware may be able to enter a low power. "
            "state, but there may be spurious wake up events."
        )


class AcpiBiosError(S0i3Failure):
    """ACPI BIOS errors detected"""

    def __init__(self, errors):
        super().__init__()
        self.description = "ACPI BIOS Errors detected"
        self.explanation = (
            "When running a firmware component utilized for s2idle "
            "the ACPI interpreter in the Linux kernel encountered some "
            "problems. This usually means it's a bug in the system BIOS "
            "that should be fixed the system manufacturer."
            ""
            "You may have problems with certain devices after resume or high "
            "power consumption when this error occurs."
        )
        for error in errors:
            self.explanation += f"{error}"


class UnsupportedModel(S0i3Failure):
    """Unsupported CPU model"""

    def __init__(self):
        super().__init__()
        self.description = "Unsupported CPU model"
        self.explanation = (
            "This model does not support hardware s2idle. "
            "Attempting to run s2idle will use a pure software suspend "
            "and will not yield tangible power savings."
        )


class UserNvmeConfiguration(S0i3Failure):
    """User has disabled NVME ACPI support"""

    def __init__(self):
        super().__init__()
        self.description = "NVME ACPI support is disabled"
        self.explanation = (
            "The kernel command line has been configured to not support "
            "NVME ACPI support. This is required for the NVME device to "
            "enter the proper power state."
        )


class AcpiNvmeStorageD3Enable(S0i3Failure):
    """NVME device is missing ACPI attributes"""

    def __init__(self, disk, num_ssds):
        super().__init__()
        self.description = f"{disk} missing ACPI attributes"
        self.explanation = (
            "An NVME device was found, but it doesn't specify the StorageD3Enable "
            "attribute in the device specific data (_DSD). "
            "This is a BIOS bug, but it may be possible to work around in the kernel. "
        )
        if num_ssds > 1:
            self.explanation += (
                ""
                "If you added an aftermarket SSD to your system, the system vendor might not have added this "
                "property to the BIOS for the second port which could cause this behavior. "
                ""
                "Please re-run this script with the --acpidump argument and file a bug to "
                "investigate."
            )
        self.url = "https://bugzilla.kernel.org/show_bug.cgi?id=216440"


class DevSlpHostIssue(S0i3Failure):
    """AHCI controller doesn't support DevSlp"""

    def __init__(self):
        super().__init__()
        self.description = "AHCI controller doesn't support DevSlp"
        self.explanation = (
            "The AHCI controller is not configured to support DevSlp. "
            "This must be enabled in BIOS for s2idle in Linux."
        )


class DevSlpDiskIssue(S0i3Failure):
    """SATA disk doesn't support DevSlp"""

    def __init__(self):
        super().__init__()
        self.description = "SATA disk doesn't support DevSlp"
        self.explanation = (
            "The SATA disk does not support DevSlp. "
            "s2idle in Linux requires SATA disks that support this feature."
        )


class SleepModeWrong(S0i3Failure):
    """System is not configured for Modern Standby"""

    def __init__(self):
        super().__init__()
        self.description = (
            "The system hasn't been configured for Modern Standby in BIOS setup"
        )
        self.explanation = (
            "AMD systems must be configured for Modern Standby in BIOS setup "
            "for s2idle to function properly in Linux. "
            "On some OEM systems this is referred to as 'Windows' sleep mode. "
            "If the BIOS is configured for S3 and you manually select s2idle "
            "in /sys/power/mem_sleep, the system will not enter the deepest hardware state."
        )


class DeepSleep(S0i3Failure):
    """Deep sleep is configured on the kernel command line"""

    def __init__(self):
        super().__init__()
        self.description = (
            "The kernel command line is asserting the system to use deep sleep"
        )
        self.explanation = (
            "Adding mem_sleep_default=deep doesn't work on AMD systems. "
            "Please remove it from the kernel command line."
        )


class FadtWrong(S0i3Failure):
    """FADT doesn't support low power idle"""

    def __init__(self):
        super().__init__()
        self.description = (
            "The kernel didn't emit a message that low power idle was supported"
        )
        self.explanation = (
            "Low power idle is a bit documented in the FADT to indicate that "
            "low power idle is supported. "
            "Only newer kernels support emitting this message, so if you run on "
            "an older kernel you may get a false negative. "
            "When launched as root this script will try to directly introspect the "
            "ACPI tables to confirm this."
        )


class Irq1Workaround(S0i3Failure):
    """IRQ1 wakeup source is active"""

    def __init__(self):
        super().__init__()
        self.description = "The wakeup showed an IRQ1 wakeup source, which might be a platform firmware bug"
        self.explanation = (
            "A number of Renoir, Lucienne, Cezanne, & Barcelo platforms have a platform firmware "
            "bug where IRQ1 is triggered during s0i3 resume. "
            "You may have tripped up on this bug as IRQ1 was active during resume. "
            "If you didn't press a keyboard key to wakeup the system then this can be "
            "the cause of spurious wakeups."
            ""
            "To fix it, first try to upgrade to the latest firmware from your manufacturer. "
            "If you're already upgraded to the latest firmware you can use one of two workarounds: "
            " 1. Manually disable wakeups from IRQ1 by running this command each boot: "
            " echo 'disabled' | sudo tee /sys/bus/serio/devices/serio0/power/wakeup "
            " 2. Use the below linked patch in your kernel."
        )
        self.url = "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/drivers/platform/x86/amd/pmc.c?id=8e60615e8932167057b363c11a7835da7f007106"


class KernelRingBufferWrapped(S0i3Failure):
    """Kernel ringbuffer has wrapped"""

    def __init__(self):
        super().__init__()
        self.description = "Kernel ringbuffer has wrapped"
        self.explanation = (
            "This script relies upon analyzing the kernel log for markers. "
            "The kernel's log provided by dmesg uses a ring buffer. "
            "When the ring buffer fills up it will wrap around and overwrite old messages. "
            ""
            "In this case it's not possible to look for some of these markers "
            ""
            "Passing the pre-requisites check won't be possible without rebooting the machine. "
            "If you are sure your system meets pre-requisites, you can re-run the script using. "
            "the systemd logger or with --force."
        )


class AmdHsmpBug(S0i3Failure):
    """AMD HSMP is built into the kernel"""

    def __init__(self):
        super().__init__()
        self.description = "amd-hsmp built in to kernel"
        self.explanation = (
            "The kernel has been compiled with CONFIG_AMD_HSMP=y. "
            "This has been shown to cause suspend failures on some systems. "
            ""
            "Either recompile the kernel without CONFIG_AMD_HSMP, "
            "or use initcall_blacklist=hsmp_plt_init on your kernel command line to avoid triggering problems "
            ""
        )
        self.url = "https://gitlab.freedesktop.org/drm/amd/-/issues/2414"


class WCN6855Bug(S0i3Failure):
    """WCN6855 firmware causes spurious wakeups"""

    def __init__(self):
        super().__init__()
        self.description = "The firmware loaded for the WCN6855 causes spurious wakeups"
        self.explanation = (
            "During s2idle on AMD systems PCIe devices are put into D3cold. During wakeup they're transitioned back "
            "into the state they were before s2idle.  For many implementations this is D3hot. "
            "If an ACPI event has been triggered by the EC, the hardware will resume from s2idle, "
            "but the kernel should process the event and then put it back into s2idle. "
            ""
            "When this bug occurs, a GPIO connected to the WLAN card is active on the system making "
            "he GPIO controller IRQ also active.  The kernel sees that the ACPI event IRQ and GPIO "
            "controller IRQ are both active and resumes the system. "
            ""
            "Some non-exhaustive events that will trigger this behavior: "
            " * Suspending the system and then closing the lid. "
            " * Suspending the system and then unplugging the AC adapter. "
            " * Suspending the system and the EC notifying the OS of a battery level change. "
            ""
            "This issue is fixed by updated WCN6855 firmware which will avoid triggering the GPIO. "
            "The version string containing the fix is 'WLAN.HSP.1.1-03125-QCAHSPSWPL_V1_V2_SILICONZ_LITE-3.6510.23' "
        )
        self.url = "https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git/commit/?id=c7a57ef688f7d99d8338a5d8edddc8836ff0e6de"


class I2CHidBug(S0i3Failure):
    """I2C HID device causes spurious wakeups"""

    def __init__(self, name, remediation):
        super().__init__()
        self.description = f"The {name} device has been reported to cause high power consumption and spurious wakeups"
        self.explanation = (
            "I2C devices work in an initiator/receiver relationship where the device is the receiver. In order for the receiver to indicate "
            "the initiator needs to read data they will assert an attention GPIO pin. "
            "When a device misbehaves it may assert this pin spuriously which can cause the SoC to wakeup prematurely. "
            "This typically manifests as high power consumption at runtime and spurious wakeups at suspend. "
            ""
            "This issue can be worked around by unbinding the device from the kernel using this command: "
            ""
            f"{remediation}"
            ""
            "To fix this issue permanently the kernel will need to avoid binding to this device. "
        )
        self.url = "https://gitlab.freedesktop.org/drm/amd/-/issues/2812"


class SpuriousWakeup(S0i3Failure):
    """System woke up prematurely"""

    def __init__(self, requested, wake):
        super().__init__()
        self.description = (
            f"Userspace wasn't asleep at least {timedelta(seconds=requested)}"
        )
        self.explanation = (
            f"The system was programmed to sleep for {timedelta(seconds=requested)}, but woke up prematurely after {wake}. "
            "This typically happens when the system was woken up from a non-timer based source. "
            "If you didn't intentionally wake it up, then there may be a kernel or firmware bug."
        )


class LowHardwareSleepResidency(S0i3Failure):
    """System had low hardware sleep residency"""

    def __init__(self, duration, percent):
        super().__init__()
        self.description = "System had low hardware sleep residency"
        self.explanation = (
            f"The system was asleep for {timedelta(seconds=duration)}, but only spent {percent:.2%} "
            "of this time in a hardware sleep state.  In sleep cycles that are at least "
            "60 seconds long it's expected you spend above 90 percent of the cycle in "
            "hardware sleep."
        )


class MSRFailure(S0i3Failure):
    """MSR access failed"""

    def __init__(self):
        super().__init__()
        self.description = "PC6 or CC6 state disabled"
        self.explanation = (
            "The PC6 state of the package or the CC6 state of CPU cores was disabled. "
            "This will prevent the system from getting to the deepest sleep state over suspend."
        )


class TaintedKernel(S0i3Failure):
    """Kernel is tainted"""

    def __init__(self):
        super().__init__()
        self.description = "Kernel is tainted"
        self.explanation = (
            "A tainted kernel may exhibit unpredictable bugs that are difficult for this script to characterize. "
            "If this is intended behavior run the tool with --force. "
        )
        self.url = "https://gitlab.freedesktop.org/drm/amd/-/issues/3089"


class DMArNotEnabled(S0i3Failure):
    """DMAr is not enabled"""

    def __init__(self):
        super().__init__()
        self.description = "Pre-boot DMA protection disabled"
        self.explanation = (
            "Pre-boot IOMMU DMA protection has been disabled. "
            "When the IOMMU is enabled this platform requires pre-boot DMA protection for suspend to work. "
        )


class MissingIommuACPI(S0i3Failure):
    """IOMMU ACPI table errors"""

    def __init__(self, device):
        super().__init__()
        self.description = f"Device {device} missing from ACPI tables"
        self.explanation = (
            "The ACPI device {device} is required for suspend to work when the IOMMU is enabled. "
            "Please check your BIOS settings and if configured correctly, report a bug to your system vendor."
        )
        self.url = "https://gitlab.freedesktop.org/drm/amd/-/issues/3738#note_2667140"


class MissingIommuPolicy(S0i3Failure):
    """ACPI table errors"""

    def __init__(self, device):
        super().__init__()
        self.description = f"Device {device} does not have IOMMU policy applied"
        self.explanation = (
            f"The ACPI device {device} is present but no IOMMU policy was set for it."
            "This generally happens if the HID or UID don't match the ACPI IVRS table."
        )


class IommuPageFault(S0i3Failure):
    """IOMMU Page fault"""

    def __init__(self, device):
        super().__init__()
        self.description = f"Page fault reported for {device}"
        self.explanation = (
            f"The IOMMU reports a page fault caused by {device}. This can prevent suspend/resume from functioning properly"
            "The page fault can be the device itself, a problem in the firmware or a problem in the kernel."
            "Report a bug for further triage and investigation."
        )


class SMTNotEnabled(S0i3Failure):
    """SMT is not enabled"""

    def __init__(self):
        super().__init__()
        self.description = "SMT is not enabled"
        self.explanation = (
            "Disabling SMT prevents cores from going into the correct state."
        )


class ASpmWrong(S0i3Failure):
    """ASPM is overridden"""

    def __init__(self):
        super().__init__()
        self.description = "ASPM is overridden"
        self.explanation = (
            " Modifying ASPM may prevent PCIe devices from going into the "
            " correct state and lead to system stability issues. "
        )


class UnservicedGpio(S0i3Failure):
    """GPIO is not serviced"""

    def __init__(self):
        super().__init__()
        self.description = "GPIO interrupt is not serviced"
        self.explanation = (
            "All GPIO controllers interrupts must be serviced to enter "
            "hardware sleep."
            "Make sure that all drivers necessary to service GPIOs are loaded. "
            "The most common cause is that i2c-hid-acpi is not loaded but the "
            "machine contains an I2C touchpad."
        )


class DmiNotSetup(S0i3Failure):
    """DMI isn't setup"""

    def __init__(self):
        super().__init__()
        self.description = "DMI data was not scanned"
        self.explanation = (
            "If DMI data hasn't been scanned then quirks that are dependent "
            "upon DMI won't be loaded. "
            "Most notably, this will prevent the rtc-cmos driver from setting. "
            "up properly by default. It may also prevent other drivers from working."
        )


class LimitedCores(S0i3Failure):
    """Number of CPU cores limited"""

    def __init__(self, actual_cores, max_cores):
        super().__init__()
        self.description = "CPU cores have been limited"
        self.explanation = (
            f"The CPU cores have been limited to {max_cores}, but the system "
            f"actually has {actual_cores}. Limiting the cores will prevent the "
            "the system from going into a hardware sleep state. "
            "This is typically solved by increasing the kernel config CONFIG_NR_CPUS."
        )


class RogAllyOldMcu(S0i3Failure):
    """MCU firwmare is too old"""

    def __init__(self, vmin, actual):
        super().__init__()
        self.description = "Rog Ally MCU firmware is too old"
        self.explanation = (
            f"The MCU is version {actual}, but needs to be at least {vmin}"
            f"to avoid major issues with interactions with suspend"
        )


class RogAllyMcuPowerSave(S0i3Failure):
    """MCU powersave is disabled"""

    def __init__(self):
        super().__init__()
        self.description = "Rog Ally MCU power save is disabled"
        self.explanation = (
            "The MCU powersave feature is disabled which will cause problems "
            "with the controller after suspend/resume."
        )

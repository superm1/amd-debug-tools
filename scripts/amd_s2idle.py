#!/usr/bin/python3
# SPDX-License-Identifier: MIT
"""S0i3/s2idle analysis script for AMD systems"""
import argparse
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime


class colors:
    HEADER = "\033[95m"
    OK = "\033[94m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"
    UNDERLINE = "\033[4m"


class headers:
    Prerequisites = "Checking prerequisites for s2idle"
    BrokenPrerequisites = "Your system does not meet s2idle prerequisites!"
    SuspendDuration = "Suspend programmed for"
    LastCycleResults = "Results from last s2idle cycle"
    CycleCount = "Suspend cycle"
    RootError = "Run as root to test suspend"
    NvmeSimpleSuspend = "platform quirk: setting simple suspend"
    WokeFromIrq = "Woke up from IRQ"
    MissingIasl = "ACPI extraction tool iasl is missing"


def read_file(fn):
    with open(fn, "r") as r:
        return r.read().strip()


def compare_sysfs(fn, expect):
    return read_file(fn) == expect


def print_color(message, color):
    print("{color}{message}{end}".format(color=color, message=message, end=colors.ENDC))


class S0i3Failure:
    def __init__(self):
        self.explanation = ""
        self.url = ""
        self.description = ""

    def get_failure(self):
        if self.description:
            print_color(self.description, colors.WARNING)
        if self.explanation:
            print(self.explanation)
        if self.url:
            print("For more information on this failure see:\n\t%s" % self.url)


class MissingAmdgpu(S0i3Failure):
    def __init__(self):
        super().__init__()
        self.description = "AMDGPU driver is missing"
        self.explanation = (
            "\tThe amdgpu driver is used for hardware acceleration as well\n"
            "\tas coordination of the power states for certain IP blocks on the SOC.\n"
            "\tBe sure that you have enabled CONFIG_AMDGPU in your kernel.\n"
        )


class MissingAmdPmc(S0i3Failure):
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


class AcpiBiosError(S0i3Failure):
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
            self.explanation += "\t%s" % error


class VendorWrong(S0i3Failure):
    def __init__(self):
        super().__init__()
        self.description = "Unsupported CPU vendor"
        self.explanation = (
            "\tThis tool specifically measures requirements utilized\n"
            "\tby AMD's S0i3 architecture.  Some of them may apply to other\n"
            "\tvendors, but definitely some are AMD specific."
        )


class AcpiNvmeStorageD3Enable(S0i3Failure):
    def __init__(self):
        super().__init__()
        self.description = "NVME device missing ACPI attributes"
        self.explanation = (
            "\tAn NVME device was found, but it doesn't specify the StorageD3Enable\n"
            "\tattribute in the device specific data (_DSD).\n"
            "\tThis is a BIOS bug, but it may be possible to work around in the kernel."
        )
        self.url = "https://bugzilla.kernel.org/show_bug.cgi?id=216440"


class DevSlpHostIssue(S0i3Failure):
    def __init__(self):
        super().__init__()
        self.description = "AHCI controller doesn't support DevSlp"
        self.explanation = (
            "\tThe AHCI controller is not configured to support DevSlp.\n"
            "\tThis must be enabled in BIOS for s2idle in Linux.\n"
        )


class DevSlpDiskIssue(S0i3Failure):
    def __init__(self):
        super().__init__()
        self.description = "SATA disk doesn't support DevSlp"
        self.explanation = (
            "\tThe SATA disk does not support DevSlp.\n"
            "\ts2idle in Linux requires SATA disks that support this feature.\n"
        )


class SleepModeWrong(S0i3Failure):
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


def _check_ahci_devslp(line):
    return "sds" in line and "sadm" in line


def _check_ata_devslp(line):
    return "Features" in line and "Dev-Sleep" in line


class S0i3Validator:
    def log(self, message, color):
        if color == colors.FAIL:
            logging.error(message)
        elif color == colors.UNDERLINE or color == colors.WARNING:
            logging.warning(message)
        else:
            logging.info(message)
        print_color(message, color)

    def __init__(self, log):
        # for saving a log file for analysis
        logging.basicConfig(
            format="%(asctime)s %(levelname)s:\t%(message)s",
            filename=log,
            filemode="w",
            level=logging.DEBUG,
        )

        # for analyzing devices
        try:
            import distro

            self.distro = distro.id()
        except ModuleNotFoundError:
            self.distro = ""
        try:
            from pyudev import Context

            self.pyudev = Context()
        except ModuleNotFoundError:
            self.pyudev = False

        if not self.pyudev:
            self.log("pyudev is missing, attempting to install", colors.FAIL)
            if self.distro == "ubuntu" or self.distro == "debian":
                installer = ["apt", "install", "python3-pyudev"]
            else:
                installer = ["python3", "-m", "pip", "install", "--upgrade", "pyudev"]
            subprocess.check_call(installer)
            from pyudev import Context

            self.pyudev = Context()

        try:
            self.iasl = subprocess.call(["iasl", "-v"], stdout=subprocess.DEVNULL) == 0
        except:
            if self.distro == "ubuntu" or self.distro == "debian":
                installer = ["apt", "install", "acpica-tools"]
                self.log("%s: attempting to install" % headers.MissingIasl, colors.OK)
            if installer:
                subprocess.check_call(installer)
            self.iasl = False

        # for analyzing systemd's journal
        try:
            from systemd import journal

            self.journal = journal.Reader()
            self.journal.this_boot()
            self.journal.log_level(journal.LOG_INFO)
            self.journal.add_match(_TRANSPORT="kernel")
            self.journal.add_match(PRIORITY=journal.LOG_DEBUG)
        except ImportError:
            self.journal = False

        # we only want kernel messages from our triggered suspend
        self.last_suspend = datetime.now()

        # failure reasons to display at the end
        self.failures = []

        # for analyzing offline reports
        self.offline = None

    # See https://github.com/torvalds/linux/commit/ec6c0503190417abf8b8f8e3e955ae583a4e50d4
    def check_fadt(self):
        """Check the kernel emitted a message specific to 6.0 or later indicating FADT had a bit set."""
        found = False
        if self.offline:
            for line in self.offline:
                if "Low-power S0 idle used by default for system suspend" in line:
                    found = True
                    break
                # re-entrant; don't re-run
                if "✅ ACPI FADT supports Low-power S0 idle" in line:
                    return
        else:
            for entry in self.journal:
                if (
                    "Low-power S0 idle used by default for system suspend"
                    in entry["MESSAGE"]
                ):
                    found = True
                    break
        if found:
            message = "✅ ACPI FADT supports Low-power S0 idle"
            self.log(message, colors.OK)
        else:
            message = "❌ ACPI FADT doesn't support Low-power S0 idle"
            self.log(message, colors.FAIL)
        return found

    def check_kernel_version(self):
        """Log the kernel version used"""
        self.log(
            "○ Kernel {version}".format(version=platform.uname().release), colors.OK
        )
        return True

    def check_systemd(self):
        if not self.journal:
            self.log(
                "❌ systemd daemon or systemd python module is missing", colors.FAIL
            )
            sys.exit(1)
        return True

    def check_cpu_vendor(self):
        p = os.path.join("/", "proc", "cpuinfo")
        cpu = read_file(p)
        if "AuthenticAMD" in cpu:
            self.log("✅ Supported CPU vendor", colors.OK)
            return True
        self.failures += [VendorWrong()]
        self.log(
            "❌ This tool is not designed for parts from this CPU vendor", colors.FAIL
        )
        return False

    def check_system_vendor(self):
        p = os.path.join("/", "sys", "class", "dmi", "id")
        try:
            vendor = read_file(os.path.join(p, "sys_vendor"))
            product = read_file(os.path.join(p, "product_name"))
            family = read_file(os.path.join(p, "product_family"))
            version = read_file(os.path.join(p, "bios_release"))
            date = read_file(os.path.join(p, "bios_date"))
            self.log(
                "○ {vendor} {product} ({family}) running BIOS {version} released {date}".format(
                    vendor=vendor,
                    product=product,
                    family=family,
                    version=version,
                    date=date,
                ),
                colors.OK,
            )
        except FileNotFoundError:
            pass
        return True

    def check_sleep_mode(self):
        fn = os.path.join("/", "sys", "power", "mem_sleep")
        if not os.path.exists(fn):
            self.log("❌ Kernel doesn't support sleep", colors.FAIL)
            return False
        if not compare_sysfs(fn, "[s2idle]"):
            self.failures += [SleepModeWrong()]
            self.log(
                "❌ System isn't configured for s2idle in firmware setup", colors.FAIL
            )
            return False
        self.log("✅ System is configured for s2idle", colors.OK)
        return True

    def check_storage(self):
        has_nvme = False
        has_sata = False
        valid_nvme = False
        valid_sata = False
        valid_ahci = False

        if self.offline:
            for line in self.offline:
                if "nvme0" in line:
                    has_nvme = True
                if "SATA link up" in line:
                    has_sata = True
                if has_nvme and headers.NvmeSimpleSuspend in line:
                    valid_nvme = True
                if has_sata and _check_ahci_devslp(line):
                    valid_ahci = True
                if has_sata and _check_ata_devslp(line):
                    valid_sata = True
                # re-entrant; don't re-run
                if "✅ NVME" in line:
                    return True
                if "✅ AHCI" in line:
                    return True
                if "✅ SATA" in line:
                    return True

        else:
            for device in self.pyudev.list_devices(subsystem="pci", DRIVER="nvme"):
                has_nvme = True
                break
            for device in self.pyudev.list_devices(subsystem="ata", DRIVER="nvme"):
                has_sata = True
                break

            if has_nvme:
                for entry in self.journal:
                    if not "nvme" in entry["MESSAGE"]:
                        continue
                    if headers.NvmeSimpleSuspend in entry["MESSAGE"]:
                        valid_nvme = True
                        break
            if has_sata:
                # Test AHCI
                for entry in self.journal:
                    if not "ahci" in entry["MESSAGE"]:
                        continue
                    if not "flags" in entry["MESSAGE"]:
                        continue
                    if _check_ahci_devslp(entry["MESSAGE"]):
                        valid_ahci = True
                        break
                # Test SATA
                for entry in self.journal:
                    if not "ata" in entry["MESSAGE"]:
                        continue
                    if _check_ata_devslp(entry["MESSAGE"]):
                        valid_sata = True
                        break
        if has_nvme:
            if valid_nvme:
                message = "✅ NVME is configured for s2idle in BIOS"
                self.log(message, colors.OK)
            else:
                message = "❌ NVME is not configured for s2idle in BIOS"
                self.log(message, colors.FAIL)
                self.failures += [AcpiNvmeStorageD3Enable()]
        if has_sata:
            if valid_sata:
                message = "✅ SATA supports DevSlp feature"
            else:
                message = "❌ SATA does not support DevSlp feature"
                self.log(message, colors.FAIL)
                self.failures += [DevSlpDiskIssue()]

            if valid_ahci:
                message = "✅ AHCI is configured for DevSlp in BIOS"
            else:
                message = "❌ AHCI is not configured for DevSlp in BIOS"
                self.log(message, colors.FAIL)
                self.failures += [DevSlpHostIssue()]

        return (
            (valid_nvme or not has_nvme)
            and (valid_sata or not has_sata)
            and (valid_ahci or not has_sata)
        )

    def check_amd_pmc(self):
        for device in self.pyudev.list_devices(subsystem="platform", DRIVER="amd_pmc"):
            message = "✅ PMC driver `amd_pmc` loaded"
            p = os.path.join(device.sys_path, "smu_program")
            v = os.path.join(device.sys_path, "smu_fw_version")
            if os.path.exists(v):
                smu_version = read_file(v)
                smu_program = read_file(p)
                message += " (Program {program} Firmware {version})".format(
                    program=smu_program, version=smu_version
                )
            self.log(message, colors.OK)
            return True
        self.failures += [MissingAmdPmc()]
        self.log("❌ PMC driver `amd_pmc` not loaded", colors.FAIL)
        return False

    def check_pinctrl_amd(self):
        for device in self.pyudev.list_devices(subsystem="platform", DRIVER="amd_gpio"):
            message = "✅ GPIO driver `pinctrl_amd` available"
            self.log(message, colors.OK)
            # save debug log if we can get it
            if os.geteuid() == 0:
                p = os.path.join("/", "sys", "kernel", "debug", "gpio")
                with open(p, "r") as r:
                    for line in r.readlines():
                        logging.debug(line.strip())
            return True
        self.log("❌ GPIO driver `pinctrl_amd` not loaded", colors.FAIL)
        return False

    def check_amdgpu(self):
        for device in self.pyudev.list_devices(subsystem="pci", DRIVER="amdgpu"):
            self.log("✅ GPU driver `amdgpu` available", colors.OK)
            return True
        self.log("❌ GPU driver `amdgpu` not loaded", colors.FAIL)
        self.failures += [MissingAmdgpu()]
        return False

    def check_wakeup_irq(self):
        p = os.path.join("/", "sys", "power", "pm_wakeup_irq")
        try:
            n = read_file(p)
            p = os.path.join("/", "sys", "kernel", "irq", n)
            chip_name = read_file(os.path.join(p, "chip_name"))
            name = read_file(os.path.join(p, "name"))
            hw = read_file(os.path.join(p, "hwirq"))
            actions = read_file(os.path.join(p, "actions"))
            message = "○ {header} {number} ({chip_name} {hw}-{name} {actions})".format(
                header=headers.WokeFromIrq,
                number=n,
                chip_name=chip_name,
                hw=hw,
                name=name,
                actions=actions,
            )
            self.log(message, colors.OK)
        except OSError:
            pass
        return True

    def check_hw_sleep(self):
        result = False
        if self.hw_sleep:
            result = True
        if not self.hw_sleep:
            p = os.path.join("/", "sys", "kernel", "debug", "amd_pmc", "smu_fw_info")
            try:
                val = read_file(p)
                for line in val.split("\n"):
                    if "Last S0i3 Status" in line:
                        if "Success" in line:
                            result = True
                        continue
                    if "Time (in us) in S0i3" in line:
                        n = int(line.split(":")[1]) / 10 ** 6
            except PermissionError:
                self.log("Run as root to gather more data", colors.WARNING)
                return False
            except FileNotFoundError:
                self.log("○ HW sleep statistics file missing", colors.FAIL)
                return False
        if result:
            self.log(
                "○ Spent {time} seconds in a hardware sleep state".format(
                    time=self.hw_sleep
                ),
                colors.OK,
            )
        else:
            self.log("○ Did not reach hardware sleep state", colors.FAIL)
        return result

    def capture_acpi(self):
        if not self.iasl:
            self.log(headers.MissingIasl, colors.WARNING)
            return True
        if os.geteuid() != 0:
            logging.debug("Unable to capture ACPI tables without root")
            return True
        base = os.path.join("/", "sys", "firmware", "acpi", "tables")
        for root, dirs, files in os.walk(base, topdown=False):
            for fname in files:
                if not "DSDT" in fname and not "SSDT" in fname:
                    continue
                target = os.path.join(root, fname)
                # If later decide to only get table that includes _AEI
                # with open(target, "rb") as f:
                #     s = f.read()
                #     if s.find(b"_AEI") >= 0:
                #         match = True
                try:
                    d = tempfile.mkdtemp()
                    prefix = os.path.join(d, "acpi")
                    subprocess.check_call(
                        ["iasl", "-p", prefix, "-d", target],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    with open("%s.dsl" % prefix, "r") as f:
                        for line in f.readlines():
                            logging.debug(line.rstrip())
                except subprocess.CalledProcessError as e:
                    self.log("Failed to capture ACPI table: %s" % e.output, colors.FAIL)
                finally:
                    shutil.rmtree(d)
        return True

    def prerequisites(self):
        self.log(headers.Prerequisites, colors.HEADER)
        checks = [
            self.check_system_vendor,
            self.check_systemd,
            self.check_cpu_vendor,
            self.check_fadt,
            self.check_kernel_version,
            self.check_amd_pmc,
            self.check_amdgpu,
            self.check_sleep_mode,
            self.check_storage,
            self.check_pinctrl_amd,
            self.capture_acpi,
        ]
        result = True
        for check in checks:
            if not check():
                result = False
        if not result:
            self.log(headers.BrokenPrerequisites, colors.UNDERLINE)
        return result

    def toggle_debugging(self, enable):
        fn = os.path.join("/", "sys", "power", "pm_debug_messages")
        setting = "1" if enable else "0"
        with open(fn, "w") as w:
            w.write(setting)
        fn = os.path.join("/", "sys", "kernel", "debug", "dynamic_debug", "control")
        setting = "+" if enable else "-"
        with open(fn, "w") as w:
            w.write("file drivers/acpi/x86/s2idle.c %sp" % setting)
        with open(fn, "w") as w:
            w.write("file drivers/pinctrl/pinctrl-amd.c %sp" % setting)
        with open(fn, "w") as w:
            w.write("file drivers/platform/x86/amd/pmc.c %sp" % setting)

    def _analyze_kernel_log_line(self, line):
        if "Timekeeping suspended for" in line:
            self.cycle_count += 1
            for f in line.split():
                try:
                    self.total_sleep += float(f)
                except ValueError:
                    pass
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
                    self.hw_sleep += float(f.strip("us")) / 10 ** 6
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

    def analyze_kernel_log(self):
        self.total_sleep = 0
        self.hw_sleep = 0
        self.suspend_count = 0
        self.cycle_count = 0
        self.upep = False
        self.upep_microsoft = False
        self.wakeup_irqs = []
        self.idle_masks = []
        self.acpi_errors = []
        self.active_gpios = []
        if self.offline:
            for line in self.offline:
                self._analyze_kernel_log_line(line)
        else:
            self.journal.seek_realtime(self.last_suspend)
            for entry in self.journal:
                line = entry["MESSAGE"]
                self._analyze_kernel_log_line(line)
                logging.debug(line)
        if self.total_sleep:
            self.log(
                "○ Kernel suspended for total of {:2.4f} seconds".format(
                    self.total_sleep
                ),
                colors.OK,
            )
        if self.suspend_count:
            self.log(
                "○ Suspend count: {count}".format(count=self.suspend_count),
                colors.OK,
            )

        if self.cycle_count:
            self.log(
                "○ Hardware sleep cycle count: {count}".format(count=self.cycle_count),
                colors.OK,
            )
        if self.active_gpios:
            self.log("○ GPIOs active: %s" % self.active_gpios, colors.OK)
        if self.wakeup_irqs:
            self.log("○ Wakeups triggered from IRQs: %s" % self.wakeup_irqs, colors.OK)
        if self.idle_masks:
            bit_changed = 0
            for i in range(0, len(self.idle_masks)):
                for j in range(i, len(self.idle_masks)):
                    if self.idle_masks[i] != self.idle_masks[j]:
                        bit_changed = bit_changed | (
                            int(self.idle_masks[i], 16) & ~int(self.idle_masks[j], 16)
                        )
            if bit_changed:
                for bit in range(0, 31):
                    if bit_changed & (1 << bit):
                        self.log(
                            "○ Idle mask bit %d (0x%x) changed during suspend"
                            % (bit, (1 << bit)),
                            colors.OK,
                        )
        if self.upep:
            if self.upep_microsoft:
                self.log("○ Used Microsoft uPEP GUID", colors.OK)
            else:
                self.log("○ Used AMD uPEP GUID", colors.OK)
        else:
            self.log("❌ uPEP GUID not executed", colors.FAIL)
        if self.acpi_errors:
            self.log("❌ ACPI BIOS errors found", colors.FAIL)
            self.failures += [AcpiBiosError(self.acpi_errors)]

    def analyze_results(self):
        self.log(headers.LastCycleResults, colors.HEADER)
        result = True
        checks = [
            self.analyze_kernel_log,
            self.check_wakeup_irq,
            self.check_hw_sleep,
        ]
        for check in checks:
            check()

    def test_suspend(self, duration, count):
        if os.geteuid() != 0:
            self.log(headers.RootError, colors.FAIL)
            return False
        if not count:
            return True
        self.log("%s +%ds" % (headers.SuspendDuration, duration), colors.HEADER)
        wakealarm = None
        for device in self.pyudev.list_devices(subsystem="rtc"):
            wakealarm = os.path.join(device.sys_path, "wakealarm")
        self.toggle_debugging(True)

        for i in range(0, count):
            if count > 1:
                self.log("%s %d" % (headers.CycleCount, i), colors.HEADER)
            self.last_suspend = datetime.now()
            with open(wakealarm, "w") as w:
                w.write("0")
            with open(wakealarm, "w") as w:
                w.write("+%s\n" % duration)
            p = os.path.join("/", "sys", "power", "state")
            with open(p, "w") as w:
                w.write("mem")
            self.analyze_results()
        self.toggle_debugging(False)
        return True

    def get_failure_report(self):
        if len(self.failures) == 0:
            return True
        print_color("S0i3 failures reported on your system", colors.HEADER)
        for item in self.failures:
            item.get_failure()

    def replay_checks(self):
        header_found = False
        for line in self.offline:
            # don't run on regular dmesg
            if headers.Prerequisites in line:
                header_found = True
            if not header_found:
                return
            line = line.split("INFO:\t")[-1].strip()
            # replay s0i3 reports
            if "✅" in line:
                self.log(line, colors.OK)
            elif "❌" in line:
                self.log(line, colors.FAIL)
            if headers.WokeFromIrq in line:
                self.log(line, colors.OK)
            if (
                headers.Prerequisites in line
                or headers.SuspendDuration in line
                or headers.CycleCount in line
                or headers.LastCycleResults in line
            ):
                self.log(line, colors.HEADER)

    def check_offline(self, input):
        with open(input, "r") as r:
            self.offline = r.readlines()
        checks = [
            self.replay_checks,
            self.check_storage,
            self.check_fadt,
            self.analyze_kernel_log,
            self.check_hw_sleep,
        ]
        for check in checks:
            check()


def parse_args():
    parser = argparse.ArgumentParser(description="Test for common s2idle problems")
    parser.add_argument("--offline", action="store_true", help="Analyze shared logs")
    parser.add_argument(
        "--log",
        default="s2idle_report.txt",
        help="Log file (default s2idle_report.txt)",
    )
    parser.add_argument(
        "--duration",
        default="10",
        help="Duration of s2idle cycle in seconds (default 10)",
    )
    parser.add_argument(
        "--count", default="1", help="Number of times to run s2idle (default 1)"
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.offline:
        if not os.path.exists(args.log):
            sys.exit("{log} is missing".format(log=args.log))
        app = S0i3Validator("/dev/null")
        app.check_offline(args.log)
        app.get_failure_report()
    else:
        print("Logs will be saved to {log}".format(log=args.log))
        app = S0i3Validator(args.log)
        test = app.prerequisites()
        if test:
            app.test_suspend(int(args.duration), int(args.count))
        app.get_failure_report()

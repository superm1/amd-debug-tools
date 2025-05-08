#!/usr/bin/python3
# SPDX-License-Identifier: MIT

import os
from pyudev import Context

from amd_debug.common import read_file


class WakeGPIO:
    """Class for wake GPIOs"""

    def __init__(self, num):
        self.num = int(num)
        self.name = ""

    def __str__(self):
        if self.name:
            return f"{self.num} ({self.name})"
        return f"{self.num}"


class WakeIRQ:
    """Class for wake IRQs"""

    def __init__(self, num, context=Context()):
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


if __name__ == "__main__":
    from tabulate import tabulate

    pyudev = Context()

    p = os.path.join("/sys", "kernel", "irq")
    irqs = []
    for d in os.listdir(p):
        if os.path.isdir(os.path.join(p, d)):
            w = WakeIRQ(d, pyudev)
            irqs.append([int(d), str(WakeIRQ(d, pyudev))])
    irqs.sort()
    print(tabulate(irqs, tablefmt="fancy_grid"))

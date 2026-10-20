# SPDX-License-Identifier: MIT

"""
This module contains the AMD storage and bus related checks for the s2idle
prerequisite validator.
"""

import os

from amd_debug.common import minimum_kernel
from amd_debug.failures import (
    AcpiNvmeStorageD3Enable,
    DevSlpDiskIssue,
    DevSlpHostIssue,
    MissingPcieHotplug,
    MissingThunderbolt,
    MissingXhciHcd,
    WCN6855Bug,
)
from amd_debug.prereq.base_headers import Headers


class AmdStorageChecks:
    """Mixin providing the AMD storage related prerequisite checks"""

    def check_storage(self):
        """Check if storage devices are supported"""
        has_sata = False
        has_ahci = False
        valid_nvme = {}
        invalid_nvme = {}
        valid_sata = False
        valid_ahci = False

        if not self.kernel_log:
            message = "Unable to test storage from kernel log"
            self.db.record_prereq(message, "🚦")
            return True

        for dev in self.pyudev.list_devices(subsystem="pci", DRIVER="nvme"):
            # https://git.kernel.org/torvalds/c/e79a10652bbd3
            if minimum_kernel(6, 10):
                break
            pci_slot_name = dev.properties["PCI_SLOT_NAME"]
            vendor = dev.properties.get("ID_VENDOR_FROM_DATABASE", "")
            model = dev.properties.get("ID_MODEL_FROM_DATABASE", "")
            message = f"{vendor} {model}"
            self.kernel_log.seek()
            pattern = f"{pci_slot_name}.*{Headers.NvmeSimpleSuspend}"
            if self.kernel_log.match_pattern(pattern):
                valid_nvme[pci_slot_name] = message
            if pci_slot_name not in valid_nvme:
                invalid_nvme[pci_slot_name] = message

        for dev in self.pyudev.list_devices(subsystem="pci", DRIVER="ahci"):
            has_ahci = True
            break

        for dev in self.pyudev.list_devices(subsystem="block", ID_BUS="ata"):
            has_sata = True
            break

        # Test AHCI
        if has_ahci:
            self.kernel_log.seek()
            pattern = "ahci.*flags.*sadm.*sds"
            if self.kernel_log.match_pattern(pattern):
                valid_ahci = True
        # Test SATA
        if has_sata:
            self.kernel_log.seek()
            pattern = "ata.*Features.*Dev-Sleep"
            if self.kernel_log.match_pattern(pattern):
                valid_sata = True

        if invalid_nvme:
            for disk, _name in invalid_nvme.items():
                message = f"NVME {invalid_nvme[disk].strip()} is not configured for s2idle in BIOS"
                self.db.record_prereq(message, "❌")
                num = len(invalid_nvme) + len(valid_nvme)
                self.failures += [AcpiNvmeStorageD3Enable(invalid_nvme[disk], num)]
        if valid_nvme:
            for disk, _name in valid_nvme.items():
                message = (
                    f"NVME {valid_nvme[disk].strip()} is configured for s2idle in BIOS"
                )
                self.db.record_prereq(message, "✅")
        if has_sata:
            if valid_sata:
                message = "SATA supports DevSlp feature"
                self.db.record_prereq(message, "✅")
            else:
                message = "SATA does not support DevSlp feature"
                self.db.record_prereq(message, "❌")
                self.failures += [DevSlpDiskIssue()]
        if has_ahci:
            if valid_ahci:
                message = "AHCI is configured for DevSlp in BIOS"
                self.db.record_prereq(message, "✅")
            else:
                message = "AHCI is not configured for DevSlp in BIOS"
                self.db.record_prereq(message, "🚦")
                self.failures += [DevSlpHostIssue()]

        return (
            (len(invalid_nvme) == 0)
            and (valid_sata or not has_sata)
            and (valid_ahci or not has_sata)
        )

    def check_wcn6855_bug(self):
        """Check if WCN6855 WLAN is affected by a bug that causes spurious wakeups"""
        if not self.kernel_log:
            message = "Unable to test for wcn6855 bug from kernel log"
            self.db.record_prereq(message, "🚦")
            return True
        wcn6855 = False
        self.kernel_log.seek()
        if self.kernel_log.match_pattern("ath11k_pci.*wcn6855"):
            match = self.kernel_log.match_pattern("ath11k_pci.*fw_version")
            if match:
                self.db.record_debug(f"WCN6855 version string: {match}")
                objects = match.split()
                for i, obj in enumerate(objects):
                    if obj == "fw_build_id":
                        wcn6855 = objects[i + 1]

        if wcn6855:
            components = wcn6855.split(".")
            if int(components[-1]) >= 37 or int(components[-1]) == 23:
                self.db.record_prereq(
                    f"WCN6855 WLAN (fw build id {wcn6855})",
                    "✅",
                )
            else:
                self.db.record_prereq(
                    f"WCN6855 WLAN may cause spurious wakeups (fw version {wcn6855})",
                    "❌",
                )
                self.failures += [WCN6855Bug()]

        return True

    def check_usb3(self):
        """Check for the USB4 controller"""
        slots = []
        for device in self.pyudev.list_devices(subsystem="pci", PCI_CLASS="C0330"):
            slot = device.properties["PCI_SLOT_NAME"]
            if device.properties.get("DRIVER") != "xhci_hcd":
                self.db.record_prereq(
                    f"USB3 controller for {slot} not using `xhci_hcd` driver", "❌"
                )
                self.failures += [MissingXhciHcd()]
                return False
            slots += [slot]
        if slots:
            self.db.record_prereq(
                f"USB3 driver `xhci_hcd` bound to {', '.join(slots)}", "✅"
            )
        return True

    def check_usb4(self):
        """Check if the thunderbolt driver is loaded"""
        slots = []
        for device in self.pyudev.list_devices(subsystem="pci", PCI_CLASS="C0340"):
            slot = device.properties["PCI_SLOT_NAME"]
            if device.properties.get("DRIVER") != "thunderbolt":
                self.db.record_prereq("USB4 driver `thunderbolt` missing", "❌")
                self.failures += [MissingThunderbolt()]
                return False
            slots += [slot]
        if slots:
            self.db.record_prereq(
                f"USB4 driver `thunderbolt` bound to {', '.join(slots)}", "✅"
            )
        return True

    def check_pcie_hotplug(self):
        """Check if PCIe hotplug support is enabled"""
        if not os.path.exists("/sys/module/pciehp"):
            self.db.record_prereq("PCIe hotplug driver `pciehp` missing", "❌")
            self.failures += [MissingPcieHotplug()]
            return False
        self.db.record_prereq("PCIe hotplug driver `pciehp` loaded", "✅")
        return True

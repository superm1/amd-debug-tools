# SPDX-License-Identifier: MIT

"""
IVRS (IOMMU Virtualization Reporting Structure) parser.

Parses the AMD IVRS ACPI table to extract device and memory mapping entries.
Used to verify IOMMU configuration for s2idle wake support.
"""

from __future__ import annotations

import struct
from abc import ABC, abstractmethod


class IvrsSubtable(ABC):
    """Base class for IVRS subtable entries.

    IVRS subtable header format:
        type (u8) at offset 0
        flags (u8) at offset 1
        length (u16 LE) at offset 2
    """

    def __init__(self, data: bytes, offset: int):
        self.data = data
        self.offset = offset
        # IVRS subtables use u16 length at offset 2
        self.length = struct.unpack_from("<H", data, offset + 2)[0]
        self._validate()

    def _validate(self):
        """Check that the subtable is at least large enough for the header."""
        if self.length < 4:
            raise ValueError(f"Invalid IVRS subtable length: {self.length}")
        if self.offset + self.length > len(self.data):
            raise ValueError(
                f"IVRS subtable at offset {self.offset} extends beyond table "
                f"(length={self.length}, table_size={len(self.data)})"
            )

    @property
    @abstractmethod
    def subtable_type(self) -> int:
        """Return the subtable type byte."""

    @property
    def raw(self) -> bytes:
        """Return the raw subtable bytes."""
        return self.data[self.offset : self.offset + self.length]


class IvhdEntry(IvrsSubtable):
    """IVHD (IOMMU Hardware Definition) subtable."""

    # Device entry types
    TYPE_ENDPOINT = 0x00
    TYPE_IOPORT = 0x01
    TYPE_PCIE_ENDPOINT = 0x02
    TYPE_PCIE_COMPAT = 0x03
    TYPE_LEGACY_PCI = 0x04
    TYPE_MSI_HOTPLUG = 0x06
    TYPE_HID_DEVICE = 0xF0

    # IVHD block header lengths by type.
    HEADER_SIZES = {
        0x10: 24,
        0x11: 40,
        0x40: 40,
    }

    def __init__(self, data: bytes, offset: int):
        super().__init__(data, offset)
        self.type = data[offset]
        self.header_size = self.HEADER_SIZES.get(self.type)
        if self.header_size is None:
            raise ValueError(f"Unsupported IVHD type 0x{self.type:02x}")
        if self.length < self.header_size:
            raise ValueError(
                f"IVHD too short for type 0x{self.type:02x}: {self.length} bytes"
            )

        # IVHD PCI segment is at offset +16 for types 10h/11h/40h.
        self.iommu_segment = struct.unpack_from("<H", data, offset + 16)[0]
        self.flags = data[offset + 1] if self.length > 1 else 0

        # Parse device entries
        self.device_entries = []
        dev_off = offset + self.header_size
        while dev_off + 4 <= offset + self.length:
            entry_length = IvhdDeviceEntry.get_entry_size(
                data, dev_off, offset + self.length
            )
            if entry_length is None or entry_length < 4:
                break
            if dev_off + entry_length > offset + self.length:
                break
            device_entry = IvhdDeviceEntry(data, dev_off, entry_length)
            self.device_entries.append(device_entry)
            dev_off += entry_length

    @property
    def subtable_type(self) -> int:
        return self.type

    def find_hid_device(self, hid: str) -> "IvhdDeviceEntry | None":
        """Find a device entry with the given HID string."""
        for entry in self.device_entries:
            if entry.type == self.TYPE_HID_DEVICE and entry.hid == hid:
                return entry
        return None

    @property
    def device_ids(self) -> set[int]:
        """Return all device IDs defined in this IVHD."""
        return {entry.device_id for entry in self.device_entries}


class IvhdDeviceEntry:
    """A device entry within an IVHD subtable."""

    TYPE_HID_DEVICE = 0xF0

    def __init__(self, data: bytes, offset: int, entry_length: int | None = None):
        self.data = data
        self.offset = offset
        self.type = data[offset]
        self.device_id = struct.unpack_from("<H", data, offset + 1)[0]
        self.flags = data[offset + 3] if (offset + 4) <= len(data) else 0

        if self.type == self.TYPE_HID_DEVICE:
            self._parse_hid_device(entry_length)
        else:
            self.hid = None
            self._length = entry_length or 4

    @classmethod
    def get_entry_size(
        cls, data: bytes, offset: int, ivhd_end: int | None = None
    ) -> int | None:
        """Return the IVHD device-entry length from its type and payload.

        Entry-length rules are defined by the type high bits:
        - 00h-3Fh: 4-byte fixed entries
        - 40h-7Fh: 8-byte fixed entries
        - 80h-FFh: variable-length entries
        """
        entry_type = data[offset]
        if entry_type <= 0x3F:
            return 4
        if entry_type <= 0x7F:
            return 8

        if entry_type == cls.TYPE_HID_DEVICE:
            # F0h entry has a 22-byte fixed prefix plus UID bytes.
            if offset + 22 > len(data):
                return None
            uid_len = data[offset + 21]
            total_len = 22 + uid_len
            if ivhd_end is not None and (offset + total_len > ivhd_end):
                return None
            return total_len

        # Unknown variable-length entry.
        return None

    def _parse_hid_device(self, entry_length: int | None):
        """Parse type 0xF0 ACPI HID device entry."""
        # Format: type(1) + devid(2) + flags(1) + ACPI HID(8) + CID(8) +
        #         UID Format(1) + UID Length(1) + UID(variable)
        if entry_length is None:
            entry_length = self.get_entry_size(self.data, self.offset)
        if entry_length is None:
            self.hid = None
            self._length = 4
            return

        self._length = entry_length
        # Skip to ACPI HID (offset 4 from entry start)
        hid_start = self.offset + 4
        if hid_start + 8 <= len(self.data):
            self.hid = (
                self.data[hid_start : hid_start + 8]
                .rstrip(b"\x00")
                .decode("ascii", errors="replace")
            )
        else:
            self.hid = None

    @property
    def length(self) -> int:
        return self._length


class IvmdMapping(IvrsSubtable):
    """IVMD (IOMMU Memory Definition) subtable.

    IVMD subtable format:
        type (u8) + flags (u8) + length (u16) + device_id (u16) +
        auxiliary_data (u16) + reserved (u64) + start_address (u64) +
        memory_length (u64)

    IVMD subtypes:
        0x20 = Unity map for ALL devices (all-devices mapping)
        0x21 = Unity map for a single device (matching device_id)
        0x22 = Exclusion range for a single device
    """

    FLAG_UNITY_MAP = 0x01
    FLAG_READABLE = 0x02
    FLAG_WRITEABLE = 0x04
    FLAG_EXCLUSION_RANGE = 0x08

    # Subtable types
    TYPE_ALL_DEVICES = 0x20
    TYPE_SINGLE_DEVICE = 0x21
    TYPE_EXCLUSION_RANGE = 0x22

    def __init__(self, data: bytes, offset: int):
        super().__init__(data, offset)
        # IVMD is 32 bytes:
        # type(1) + flags(1) + length(2) + device_id(2) + auxiliary(2) +
        # reserved(8) + start_addr(8) + memory_length(8) = 32 bytes
        if self.length < 32:
            raise ValueError(f"IVMD too short: {self.length} bytes (minimum 32)")

        self.flags = data[offset + 1]
        self.device_id = struct.unpack_from("<H", data, offset + 4)[0]
        self.auxiliary_data = struct.unpack_from("<H", data, offset + 6)[0]
        self.starting_device_id = self.device_id
        self.ending_device_id = self.auxiliary_data
        self.start_address = struct.unpack_from("<Q", data, offset + 16)[0]
        self.memory_length = struct.unpack_from("<Q", data, offset + 24)[0]

    @property
    def is_unity_map(self) -> bool:
        """Return True if this is a unity-mapped region."""
        return bool(self.flags & self.FLAG_UNITY_MAP)

    @property
    def is_exclusion_range(self) -> bool:
        """Return True if this is an exclusion range."""
        return bool(self.flags & self.FLAG_EXCLUSION_RANGE)

    @property
    def has_valid_mapping(self) -> bool:
        """Return True if this entry has a non-zero memory range."""
        return self.memory_length > 0

    @property
    def subtype(self) -> int:
        """Return the IVMD subtype (0x20, 0x21, or 0x22)."""
        return self.data[self.offset]

    @property
    def subtable_type(self) -> int:
        """Return the IVMD subtype."""
        return self.subtype

    def covers_device(self, device_id: int) -> bool:
        """Check if this IVMD entry covers the given device ID.

        - Type 0x20: All-devices mapping, covers all devices regardless of ID.
        - Type 0x21: Single-device mapping, match by exact device ID.
        - Type 0x22: Exclusion range, match by starting device ID.
        """
        if self.subtype == self.TYPE_ALL_DEVICES:
            return self.has_valid_mapping
        if self.subtype == self.TYPE_SINGLE_DEVICE:
            return self.device_id == device_id
        # Type 0x22 applies to a DeviceID range [start, end], inclusive.
        return self.starting_device_id <= device_id <= self.ending_device_id

    def covers_device_id(self, device_id: int) -> bool:
        """Check if this mapping is valid AND covers the device.

        A valid covering mapping must have:
        1. The appropriate flag set (unity-map for 0x20/0x21, exclusion-range for 0x22)
        2. A non-zero memory range
        3. The device must be covered by this entry's scope
        """
        if not self.has_valid_mapping:
            return False

        if self.subtype == self.TYPE_ALL_DEVICES:
            return self.is_unity_map
        if not self.covers_device(device_id):
            return False
        if self.subtype == self.TYPE_SINGLE_DEVICE:
            return self.is_unity_map
        return self.is_exclusion_range


class IvrsParser:
    """Parse an IVRS (IOMMU Virtualization Reporting Structure) ACPI table.

    The IVRS table contains:
    - Main header (48 bytes) with unitCapability at offset 36
    - Subtables starting at offset 48

    Subtable types:
        0x10 = IVHD (IOMMU Hardware Definition) - contains device entries
        0x11 = IVHD v2 (with additional fields)
        0x20 = IVMD (IOMMU Memory Definition) - all-devices unity map
        0x21 = IVMD - single-device unity map
        0x22 = IVMD - exclusion range
        0x40 = IVHD Mixed Format
    """

    # IVRS main table fields
    IVRS_HEADER_SIZE = 48
    UNIT_CAPABILITY_OFFSET = 36  # Virtualization Info at offset 36
    DMA_REMAP_BIT = 0x2

    # Subtable types
    TYPE_IVHD = 0x10
    TYPE_IVHD_V2 = 0x11  # IVHD v2 with additional fields
    TYPE_IVHD_MIXED = 0x40
    TYPE_IVMD_ALL_DEVICES = 0x20
    TYPE_IVMD_SINGLE_DEVICE = 0x21
    TYPE_IVMD_EXCLUSION_RANGE = 0x22

    def __init__(self, data: bytes):
        if len(data) < self.IVRS_HEADER_SIZE:
            raise ValueError(
                f"IVRS table too small: {len(data)} bytes "
                f"(minimum {self.IVRS_HEADER_SIZE})"
            )

        self.data = data
        self.virt_info = struct.unpack_from("I", data, self.UNIT_CAPABILITY_OFFSET)[0]
        self.has_dma_remap = (self.virt_info & self.DMA_REMAP_BIT) != 0

        # Parse subtables starting at offset 48
        self.subtables: list[IvrsSubtable] = []
        self._parse_subtables()

    @property
    def ivhd_entries(self) -> list[IvhdEntry]:
        """Return all IVHD subtables."""
        return [st for st in self.subtables if isinstance(st, IvhdEntry)]

    @property
    def ivmd_mappings(self) -> list[IvmdMapping]:
        """Return all IVMD subtables."""
        return [st for st in self.subtables if isinstance(st, IvmdMapping)]

    def _parse_subtables(self):
        """Parse all subtables starting at offset 48."""
        off = 48
        while off + 4 <= len(self.data):
            length = struct.unpack_from("<H", self.data, off + 2)[0]
            if length == 0:
                break
            if off + length > len(self.data):
                break
            if length < 4:
                break

            sub_type = self.data[off]
            try:
                if sub_type in (
                    self.TYPE_IVHD,
                    self.TYPE_IVHD_V2,
                    self.TYPE_IVHD_MIXED,
                ):
                    subtable = IvhdEntry(self.data, off)
                    self.subtables.append(subtable)
                elif sub_type in (
                    self.TYPE_IVMD_ALL_DEVICES,
                    self.TYPE_IVMD_SINGLE_DEVICE,
                    self.TYPE_IVMD_EXCLUSION_RANGE,
                ):
                    subtable = IvmdMapping(self.data, off)
                    self.subtables.append(subtable)
                else:
                    # Skip unknown subtable types
                    pass
            except ValueError:
                # Malformed subtable, skip it
                pass
            off += length

    def find_msft0201_device_id(self) -> int | None:
        """Find the device ID for MSFT0201 from IVHD HID device entries.

        Returns None if MSFT0201 is not found in any IVHD subtable.
        """
        for ivhd in self.ivhd_entries:
            device = ivhd.find_hid_device("MSFT0201")
            if device:
                return device.device_id
        return None

    def has_msft0201_in_acpi(self) -> bool:
        """Check if MSFT0201 ACPI HID exists in the IVRS table anywhere."""
        return b"MSFT0201" in self.data

    def has_valid_msft0201_mapping(self, msft_device_id: int | None) -> bool:
        """Check if MSFT0201 has a valid memory mapping in IVMD entries.

        A valid mapping requires:
        - Type 0x20 (all-devices): unity_map flag set
        - Type 0x21 (single-device): unity_map flag AND matching device_id
        - Type 0x22 (exclusion range): exclusion_range flag AND matching device_id

        All valid mappings must have a non-zero memory range.
        """
        if msft_device_id is None:
            return False
        for ivmd in self.ivmd_mappings:
            if ivmd.covers_device_id(msft_device_id):
                return True
        return False


def main():
    """CLI entry point for IVRS table analysis."""
    import argparse

    parser = argparse.ArgumentParser(description="Parse and analyze IVRS ACPI tables")
    parser.add_argument("ivrs_file", help="Path to IVRS ACPI table binary")
    parser.add_argument(
        "--ssdt",
        nargs="*",
        help="Optional paths to SSDT tables for ACPI device lookup",
    )
    args = parser.parse_args()

    with open(args.ivrs_file, "rb") as f:
        data = f.read()

    try:
        ivrs = IvrsParser(data)
    except ValueError as e:
        print(f"Error parsing IVRS table: {e}")
        return 1

    print("IVRS Table Analysis")
    print("===================")
    print(f"Table size: {len(data)} bytes")
    print(f"Virtualization info: 0x{ivrs.virt_info:08x}")
    print(f"  DMA Remap enabled: {ivrs.has_dma_remap}")
    print()

    print(f"Subtables: {len(ivrs.subtables)}")
    for st in ivrs.subtables:
        print(
            f"  Type=0x{st.subtable_type:02x}, offset={st.offset}, length={st.length}"
        )

    print()
    if ivrs.ivhd_entries:
        print(f"IVHD entries: {len(ivrs.ivhd_entries)}")
        for i, ivhd in enumerate(ivrs.ivhd_entries):
            print(f"  IVHD #{i}: {len(ivhd.device_entries)} device entries")
            for dev in ivhd.device_entries:
                if dev.hid:
                    print(f"    HID Device: id=0x{dev.device_id:04x}, hid={dev.hid}")

    if ivrs.ivmd_mappings:
        print()
        print(f"IVMD mappings: {len(ivrs.ivmd_mappings)}")
        for ivmd in ivrs.ivmd_mappings:
            print(f"  Type=0x{ivmd.subtype:02x}, devid=0x{ivmd.starting_device_id:04x}")
            print(
                f"    flags=unity={ivmd.is_unity_map}, excl={ivmd.is_exclusion_range}"
            )
            print(f"    memory_length=0x{ivmd.memory_length:x}")

    print()
    print("MSFT0201 check:")
    msft_devid = ivrs.find_msft0201_device_id()
    if msft_devid:
        print(f"  Device ID from IVHD: 0x{msft_devid:04x}")
        print(f"  Valid mapping: {ivrs.has_valid_msft0201_mapping(msft_devid)}")
    else:
        print("  Not found in IVHD device entries")
        if b"MSFT0201" in data:
            print("  But MSFT0201 HID string found in table")
    return 0


if __name__ == "__main__":
    main()

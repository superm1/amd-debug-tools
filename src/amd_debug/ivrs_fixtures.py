# SPDX-License-Identifier: MIT

"""
Helper functions to create test IVRS table fixtures.
"""

from __future__ import annotations

import struct


def _pack_ivrs_header(
    dma_remap: bool = False, unit_id: int = 0, revision: int = 2
) -> bytes:
    """Create an IVRS main table header.

    IVRS table header structure (48 bytes):
        Common ACPI header (28 bytes) + IVRS-specific fields (20 bytes)

    IVRS-specific fields (at offset 28):
        VendorID(2) + DeviceID(2) + Reserved(2) + UnitID(2) +
        UnitCapability(4) + Reserved(8) = 20 bytes

    Args:
        dma_remap: If True, sets bit 0x2 in UnitCapability.
        unit_id: IVRS unit identifier.

    Returns:
        48-byte IVRS main table header.
    """
    header = bytearray(48)
    # Common ACPI table header (28 bytes)
    header[0:4] = b"IVRS"  # Signature
    struct.pack_into("<H", header, 4, 48)  # Length (placeholder)
    header[6] = revision  # Revision
    header[7] = 0x00  # Checksum (placeholder)
    header[8:14] = b"AUTH" + b"\x00" * 2  # OEM ID (6 bytes, padded)
    header[14:22] = b"AMDDBG" + b"\x00" * 2  # OEM Table ID (8 bytes, padded)
    struct.pack_into("<I", header, 22, 0x00000001)  # OEM Revision
    struct.pack_into("<I", header, 26, 0x00000001)  # Creator ID
    struct.pack_into("<I", header, 30, 0x00000001)  # Creator Revision
    # IVRS-specific fields (start at offset 28)
    struct.pack_into("<H", header, 28, 0x0000)  # Vendor ID
    struct.pack_into("<H", header, 30, 0x0000)  # Device ID
    struct.pack_into("<H", header, 32, 0x0000)  # Reserved
    struct.pack_into("<H", header, 34, unit_id)  # Unit ID
    unit_cap = 0
    if dma_remap:
        unit_cap |= 0x2
    struct.pack_into("<I", header, 36, unit_cap)  # UnitCapability
    struct.pack_into("<Q", header, 40, 0x0000000000000000)  # Reserved
    return bytes(header)


def _pack_ivhd_header(ivhd_type: int = 0x40, segment: int = 0, flags: int = 0) -> bytes:
    """Create an IVHD subtable header (type 0x10, 0x11, or 0x40).

    Type 10h header is 24 bytes.
    Type 11h and 40h headers are 40 bytes and include EFR images.

    Args:
        segment: IOMMU PCI segment number.
        flags: IVHD flags.

    Returns:
        IVHD header bytes.
    """
    if ivhd_type not in (0x10, 0x11, 0x40):
        raise ValueError(f"Unsupported IVHD type: 0x{ivhd_type:02x}")

    header_len = 24 if ivhd_type == 0x10 else 40
    header = bytearray(header_len)
    header[0] = ivhd_type
    header[1] = flags
    struct.pack_into("<H", header, 2, header_len)  # length (placeholder)
    struct.pack_into("<H", header, 4, 0x0002)  # device ID
    struct.pack_into("<H", header, 6, 0x0040)  # capability offset
    struct.pack_into("<Q", header, 8, 0xFD200000)  # base address
    struct.pack_into("<H", header, 16, segment)  # PCI segment
    struct.pack_into("<H", header, 18, 0x0000)  # virtualization info
    if ivhd_type == 0x10:
        struct.pack_into("<I", header, 20, 0x80048F6E)  # feature reporting
    else:
        struct.pack_into("<I", header, 20, 0x00000000)  # IOMMU attributes
        struct.pack_into("<Q", header, 24, 0x0000000000000000)  # EFR image
        struct.pack_into("<Q", header, 32, 0x0000000000000000)  # EFR image 2
    return bytes(header)


def _pack_ivhd_header_v2(segment: int = 0, flags: int = 0) -> bytes:
    """Backwards-compatible alias for a type 10h IVHD header."""
    return _pack_ivhd_header(ivhd_type=0x10, segment=segment, flags=flags)


def _pack_ivhd_hid_device(device_id: int, hid: str) -> bytes:
    """Create an IVHD HID device entry (type 0xF0).

    Args:
        device_id: Device ID (u16).
        hid: HID string (e.g., "MSFT0201").

    Returns:
        IVHD device entry bytes.
    """
    hid_bytes = hid.encode("ascii")
    # 0xF0 entry format:
    # type(1) + devid(2) + flags(1) + ACPI HID(8) + CID(8) +
    # UID Format(1) + UID Length(1) + UID(variable)
    uid_length = min(len(hid_bytes), 8)
    entry_len = 4 + 8 + 8 + 1 + 1 + uid_length  # = 22+ for "MSFT0201"
    entry = bytearray(entry_len)
    entry[0] = 0xF0  # type
    struct.pack_into("<H", entry, 1, device_id)  # device ID
    entry[3] = 0x40  # flags
    entry[4:12] = hid_bytes.ljust(8, b"\x00")  # ACPI HID
    entry[12:20] = b"\x00" * 8  # ACPI CID
    entry[20] = 0x01  # UID Format
    entry[21] = uid_length  # UID Length
    entry[22 : 22 + uid_length] = hid_bytes
    return bytes(entry)


def _pack_ivhd_endpoint_device(device_id: int) -> bytes:
    """Create an IVHD endpoint device entry (type 0x00).

    Args:
        device_id: Device ID (u16).

    Returns:
        IVHD device entry bytes.
    """
    # 4-byte select entry (type 0x02): one DeviceID with DTE settings.
    entry = bytearray(4)
    entry[0] = 0x02
    struct.pack_into("<H", entry, 1, device_id)
    entry[3] = 0x00  # flags
    return bytes(entry)


def _pack_ivhd_start_range(device_id: int) -> bytes:
    """Create an IVHD Start of Range device entry (type 0x03).

    Args:
        device_id: Starting device ID.

    Returns:
        IVHD device entry bytes.
    """
    entry = bytearray(4)
    entry[0] = 0x03  # type
    struct.pack_into("<H", entry, 1, device_id)
    entry[3] = 0x00  # flags
    return bytes(entry)


def _pack_ivhd_end_range(device_id: int) -> bytes:
    """Create an IVHD End of Range device entry (type 0x04).

    Args:
        device_id: Ending device ID.

    Returns:
        IVHD device entry bytes.
    """
    entry = bytearray(4)
    entry[0] = 0x04  # type
    struct.pack_into("<H", entry, 1, device_id)
    entry[3] = 0x00  # flags
    return bytes(entry)


def _pack_ivmd_all_devices(device_id: int = 0, memory_length: int = 0x100000) -> bytes:
    """Create an IVMD all-devices unity map subtable (type 0x20).

    Args:
        device_id: Device ID (stored but not used as selector for 0x20).
        memory_length: Size of the unified memory region (u64).

    Returns:
        IVMD subtable bytes (32 bytes).
    """
    entry = bytearray(32)
    entry[0] = 0x20  # type
    entry[1] = 0x07  # flags (unity + readable + writeable)
    struct.pack_into("<H", entry, 2, 32)  # length
    struct.pack_into("<H", entry, 4, device_id)  # device_id
    struct.pack_into("<H", entry, 6, 0x0000)  # auxiliary data
    struct.pack_into("<Q", entry, 8, 0x0000000000000000)  # reserved
    struct.pack_into("<Q", entry, 16, 0x7D900000)  # start_address
    struct.pack_into("<Q", entry, 24, memory_length)  # memory_length
    return bytes(entry)


def _pack_ivmd_single_device(device_id: int, memory_length: int = 0x100000) -> bytes:
    """Create an IVMD single-device unity map subtable (type 0x21).

    Args:
        device_id: Device ID this mapping applies to.
        memory_length: Size of the unity-mapped memory region (u64).

    Returns:
        IVMD subtable bytes (32 bytes).
    """
    entry = bytearray(32)
    entry[0] = 0x21  # type
    entry[1] = 0x07  # flags (unity + readable + writeable)
    struct.pack_into("<H", entry, 2, 32)  # length
    struct.pack_into("<H", entry, 4, device_id)  # device_id
    struct.pack_into("<H", entry, 6, 0x0000)  # auxiliary data
    struct.pack_into("<Q", entry, 8, 0x0000000000000000)  # reserved
    struct.pack_into("<Q", entry, 16, 0x7D900000)  # start_address
    struct.pack_into("<Q", entry, 24, memory_length)  # memory_length
    return bytes(entry)


def _pack_ivmd_exclusion_range(
    device_id: int,
    memory_length: int = 0x100000,
    end_device_id: int | None = None,
) -> bytes:
    """Create an IVMD exclusion range subtable (type 0x22).

    Args:
        device_id: Device ID this exclusion range applies to.
        memory_length: Size of the excluded memory region (u64).

    Returns:
        IVMD subtable bytes (32 bytes).
    """
    entry = bytearray(32)
    entry[0] = 0x22  # type
    entry[1] = 0x08  # flags (exclusion_range)
    struct.pack_into("<H", entry, 2, 32)  # length
    struct.pack_into("<H", entry, 4, device_id)  # device_id
    if end_device_id is None:
        end_device_id = device_id
    struct.pack_into("<H", entry, 6, end_device_id)  # auxiliary data (range end)
    struct.pack_into("<Q", entry, 8, 0x0000000000000000)  # reserved
    struct.pack_into("<Q", entry, 16, 0x77E00000)  # start_address
    struct.pack_into("<Q", entry, 24, memory_length)  # memory_length
    return bytes(entry)


def make_ivrs_table(
    dma_remap: bool = False,
    msft0201_devid: int | None = None,
    ivmd_entries: list[bytes] | None = None,
    extra_devices: list[int] | None = None,
    ivhd_type: int = 0x40,
) -> bytes:
    """Build a complete IVRS table for testing.

    Args:
        dma_remap: If True, enables pre-boot DMA protection.
        msft0201_devid: Device ID for MSFT0201 HID device entry, or None.
        ivmd_entries: List of IVMD subtable bytes to include.
        extra_devices: List of additional endpoint device IDs to include.
        ivhd_type: IVHD type to emit (0x10, 0x11, or 0x40).

    Returns:
        Complete IVRS table bytes.
    """
    ivmd_entries = ivmd_entries or []
    extra_devices = extra_devices or []

    # Main header
    revision = 2 if ivhd_type == 0x40 else 1
    header = _pack_ivrs_header(dma_remap=dma_remap, revision=revision)

    # IVHD subtable
    ivhd_header = _pack_ivhd_header(ivhd_type=ivhd_type)

    # Device entries
    device_entries = bytearray()
    # Add a range entry
    device_entries += _pack_ivhd_start_range(0x0003)
    device_entries += _pack_ivhd_end_range(0xFFFE)
    if msft0201_devid is not None:
        device_entries += _pack_ivhd_hid_device(msft0201_devid, "MSFT0201")
    for devid in extra_devices:
        device_entries += _pack_ivhd_endpoint_device(devid)

    # Complete IVHD subtable
    ivhd = bytearray(ivhd_header) + bytearray(device_entries)
    # Update IVHD length
    struct.pack_into("<H", ivhd, 2, len(ivhd))
    ivhd = bytes(ivhd)

    # Complete IVRS table
    table = bytearray(header) + bytearray(ivhd)
    for ivmd in ivmd_entries:
        table += bytearray(ivmd)

    # Update IVRS header length
    struct.pack_into("<H", table, 4, len(table))

    return bytes(table)

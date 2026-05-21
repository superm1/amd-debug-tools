# SPDX-License-Identifier: MIT
"""Discovery and reading of IIO power monitor rails.

This module discovers power monitoring chips via the Linux IIO (Industrial I/O)
sysfs interface and reads energy accumulator values for suspend power consumption analysis.

Each power monitor chip exposes N rails (typically 1-4). For rail N, the IIO
driver provides:
- in_powerN_label       -- human-readable rail name
- in_energyN_raw        -- raw energy accumulator value
- in_energyN_scale      -- scale factor to convert raw to Joules

We capture energy accumulators before and after suspend, then calculate average
power as: Power (W) = ΔEnergy (J) / Δtime (s)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Set

IIO_DEVICES_ROOT = Path("/sys/bus/iio/devices")

# Supported power monitor chip names (extensible set)
SUPPORTED_POWER_CHIPS: Set[str] = {
    "pac1954",
}

# Maximum channel number to scan (some future chips may have more)
MAX_CHANNELS = 16


def _read_text(path: Path) -> str:
    """Read and strip text from a sysfs file."""
    return path.read_text().strip()


def _read_float(path: Path) -> float:
    """Read a floating-point value from a sysfs file."""
    return float(_read_text(path))


@dataclass(frozen=True)
class PowerRail:
    """A single named power rail on an IIO power monitor chip.

    Attributes:
        device: IIO device name (e.g., "iio:device0")
        channel: Channel number (1..N)
        label: Human-readable rail name (e.g., "CPU_VDDCR_PH1_IN_POWER_1")
        sysfs: Path to the device directory in sysfs
        energy_scale: Scale factor to convert raw energy to Joules
    """

    device: str
    channel: int
    label: str
    sysfs: Path
    energy_scale: float

    def read_energy_raw(self) -> float:
        """Read the current raw energy accumulator value.

        Returns:
            Raw energy accumulator value (units depend on chip, use energy_scale
            to convert to Joules)

        Raises:
            OSError: If the sysfs file cannot be read
        """
        return _read_float(self.sysfs / f"in_energy{self.channel}_raw")


def _discover_chip_rails(device_dir: Path, chip_ids: Set[str] = None) -> list[PowerRail]:
    """Discover all enabled power rails for a single IIO device.

    Args:
        device_dir: Path to the IIO device directory (e.g., /sys/bus/iio/devices/iio:device0)
        chip_ids: Set of supported chip IDs to filter by (default: SUPPORTED_POWER_CHIPS)

    Returns:
        List of PowerRail objects for enabled rails on this device
    """
    if chip_ids is None:
        chip_ids = SUPPORTED_POWER_CHIPS

    # Check if this is a supported power monitor chip
    name_path = device_dir / "name"
    if not name_path.exists():
        return []

    chip_name = _read_text(name_path)
    if chip_name not in chip_ids:
        return []

    device_id = device_dir.name
    rails: list[PowerRail] = []

    # Scan for power rails (channel 1..MAX_CHANNELS)
    for n in range(1, MAX_CHANNELS + 1):
        label_path = device_dir / f"in_power{n}_label"
        if not label_path.exists():
            continue

        label = _read_text(label_path)
        if not label:
            continue  # Unwired or disabled rail

        # Read the energy scale factor
        scale_path = device_dir / f"in_energy{n}_scale"
        if not scale_path.exists():
            continue  # No energy accumulator for this rail

        try:
            energy_scale = _read_float(scale_path)
            rails.append(
                PowerRail(
                    device=device_id,
                    channel=n,
                    label=label,
                    sysfs=device_dir,
                    energy_scale=energy_scale,
                )
            )
        except (FileNotFoundError, ValueError, OSError):
            # Skip rails with missing or invalid scale files
            continue

    return rails


def discover_rails(
    iio_root: Path = IIO_DEVICES_ROOT,
    chip_ids: Set[str] = None,
) -> list[PowerRail]:
    """Discover all IIO power monitor rails on the system.

    Args:
        iio_root: Root directory for IIO devices (default: /sys/bus/iio/devices)
        chip_ids: Set of supported chip IDs (default: SUPPORTED_POWER_CHIPS)

    Returns:
        List of all discovered PowerRail objects, sorted by device name
    """
    if not iio_root.exists():
        return []

    rails: list[PowerRail] = []
    for device_dir in sorted(iio_root.glob("iio:device*")):
        rails.extend(_discover_chip_rails(device_dir, chip_ids))

    return rails


class PowerRails:
    """Manages discovery and reading of IIO power monitor rails.

    This class discovers available power monitor chips at initialization and
    provides methods to read energy accumulator values from the discovered rails.

    Attributes:
        rails: List of discovered PowerRail objects
    """

    def __init__(self, iio_root: Path = IIO_DEVICES_ROOT):
        """Initialize and discover power rails.

        Args:
            iio_root: Root directory for IIO devices (allows testing with mock paths)
        """
        self.iio_root = iio_root
        self.rails = discover_rails(iio_root)

    def get_rails(self) -> list[PowerRail]:
        """Get the list of discovered power rails.

        Returns:
            List of PowerRail objects
        """
        return self.rails

    def read_rail_energy(self, rail: PowerRail) -> float:
        """Read the current energy accumulator for a specific rail.

        Args:
            rail: PowerRail object to read from

        Returns:
            Raw energy accumulator value

        Raises:
            OSError: If the sysfs file cannot be read
        """
        return rail.read_energy_raw()

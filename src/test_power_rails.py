# SPDX-License-Identifier: MIT
"""Unit tests for power_rails module."""

import pytest
from pathlib import Path
from tempfile import TemporaryDirectory

from amd_debug.power_rails import (
    PowerRail,
    PowerRails,
    discover_rails,
    _discover_chip_rails,
    SUPPORTED_POWER_CHIPS,
)


@pytest.fixture
def mock_iio_root(tmp_path):
    """Create a mock IIO sysfs directory structure."""
    iio_root = tmp_path / "iio"
    iio_root.mkdir()
    return iio_root


def create_mock_device(
    iio_root: Path,
    device_num: int,
    chip_name: str,
    rails: dict[int, tuple[str, float]],
):
    """Create a mock IIO power monitor device.

    Args:
        iio_root: Root IIO directory
        device_num: Device number (e.g., 0 for iio:device0)
        chip_name: Chip name (e.g., "pac1954")
        rails: Dict mapping channel number to (label, energy_scale)
    """
    device_dir = iio_root / f"iio:device{device_num}"
    device_dir.mkdir()

    # Write device name
    (device_dir / "name").write_text(f"{chip_name}\n")

    # Write rail attributes
    for channel, (label, energy_scale) in rails.items():
        (device_dir / f"in_power{channel}_label").write_text(f"{label}\n")
        (device_dir / f"in_energy{channel}_scale").write_text(f"{energy_scale}\n")
        (device_dir / f"in_energy{channel}_raw").write_text("1000000\n")

    return device_dir


class TestPowerRailDataclass:
    """Tests for PowerRail dataclass."""

    def test_power_rail_attributes(self, mock_iio_root):
        """Test PowerRail stores attributes correctly."""
        device_dir = mock_iio_root / "iio:device0"
        device_dir.mkdir()
        (device_dir / "in_energy1_raw").write_text("12345\n")

        rail = PowerRail(
            device="iio:device0",
            channel=1,
            label="TEST_RAIL",
            sysfs=device_dir,
            energy_scale=1.5,
        )

        assert rail.device == "iio:device0"
        assert rail.channel == 1
        assert rail.label == "TEST_RAIL"
        assert rail.sysfs == device_dir
        assert rail.energy_scale == 1.5

    def test_read_energy_raw(self, mock_iio_root):
        """Test reading raw energy accumulator."""
        device_dir = mock_iio_root / "iio:device0"
        device_dir.mkdir()
        (device_dir / "in_energy2_raw").write_text("987654321\n")

        rail = PowerRail(
            device="iio:device0",
            channel=2,
            label="TEST_RAIL",
            sysfs=device_dir,
            energy_scale=1.0,
        )

        energy = rail.read_energy_raw()
        assert energy == 987654321.0

    def test_read_energy_raw_missing_file(self, mock_iio_root):
        """Test reading energy when file doesn't exist raises OSError."""
        device_dir = mock_iio_root / "iio:device0"
        device_dir.mkdir()

        rail = PowerRail(
            device="iio:device0",
            channel=3,
            label="TEST_RAIL",
            sysfs=device_dir,
            energy_scale=1.0,
        )

        with pytest.raises((OSError, FileNotFoundError)):
            rail.read_energy_raw()


class TestDiscoverChipRails:
    """Tests for _discover_chip_rails function."""

    def test_discover_pac1954_rails(self, mock_iio_root):
        """Test discovering rails from a PAC1954 chip."""
        device_dir = create_mock_device(
            mock_iio_root,
            0,
            "pac1954",
            {
                1: ("CPU_VDDCR_PH1_IN_POWER_1", 149011.611),
                2: ("CPU_VDDCR_PH2_IN_POWER_2", 149011.611),
                3: ("VDDIO_IN_POWER_3", 23751.3),
                4: ("VCORE_IN_POWER_4", 37502.08),
            },
        )

        rails = _discover_chip_rails(device_dir)

        assert len(rails) == 4
        assert rails[0].device == "iio:device0"
        assert rails[0].channel == 1
        assert rails[0].label == "CPU_VDDCR_PH1_IN_POWER_1"
        assert rails[0].energy_scale == 149011.611
        assert rails[3].label == "VCORE_IN_POWER_4"

    def test_discover_unsupported_chip(self, mock_iio_root):
        """Test that unsupported chips are ignored."""
        device_dir = create_mock_device(
            mock_iio_root,
            2,
            "unsupported_chip",
            {1: ("SOME_RAIL", 1.0)},
        )

        rails = _discover_chip_rails(device_dir)

        assert len(rails) == 0

    def test_discover_with_custom_chip_ids(self, mock_iio_root):
        """Test discovery with custom chip ID set."""
        device_dir = create_mock_device(
            mock_iio_root,
            3,
            "custom_chip",
            {1: ("CUSTOM_RAIL", 2.5)},
        )

        # Should be ignored with default chip IDs
        rails = _discover_chip_rails(device_dir)
        assert len(rails) == 0

        # Should be discovered with custom chip IDs
        rails = _discover_chip_rails(device_dir, chip_ids={"custom_chip"})
        assert len(rails) == 1
        assert rails[0].label == "CUSTOM_RAIL"

    def test_discover_empty_label(self, mock_iio_root):
        """Test that rails with empty labels are skipped."""
        device_dir = mock_iio_root / "iio:device4"
        device_dir.mkdir()
        (device_dir / "name").write_text("pac1954\n")
        (device_dir / "in_power1_label").write_text("\n")  # Empty label
        (device_dir / "in_energy1_scale").write_text("1.0\n")

        rails = _discover_chip_rails(device_dir)

        assert len(rails) == 0

    def test_discover_missing_scale(self, mock_iio_root):
        """Test that rails without energy_scale are skipped."""
        device_dir = mock_iio_root / "iio:device5"
        device_dir.mkdir()
        (device_dir / "name").write_text("pac1954\n")
        (device_dir / "in_power1_label").write_text("TEST_RAIL\n")
        # in_energy1_scale is missing

        rails = _discover_chip_rails(device_dir)

        assert len(rails) == 0

    def test_discover_no_name_file(self, mock_iio_root):
        """Test that devices without name file are ignored."""
        device_dir = mock_iio_root / "iio:device6"
        device_dir.mkdir()
        # No name file

        rails = _discover_chip_rails(device_dir)

        assert len(rails) == 0

    def test_discover_sparse_channels(self, mock_iio_root):
        """Test discovering rails with non-consecutive channel numbers."""
        device_dir = create_mock_device(
            mock_iio_root,
            7,
            "pac1954",
            {
                1: ("RAIL_1", 1.0),
                # Channel 2 is missing
                3: ("RAIL_3", 3.0),
                # Channel 4 is missing
            },
        )

        rails = _discover_chip_rails(device_dir)

        assert len(rails) == 2
        assert rails[0].channel == 1
        assert rails[1].channel == 3

    def test_discover_high_channel_numbers(self, mock_iio_root):
        """Test discovering rails with high channel numbers (for future chips)."""
        device_dir = mock_iio_root / "iio:device8"
        device_dir.mkdir()
        (device_dir / "name").write_text("pac1954\n")
        (device_dir / "in_power7_label").write_text("HIGH_CHANNEL\n")
        (device_dir / "in_energy7_scale").write_text("5.5\n")
        (device_dir / "in_energy7_raw").write_text("123\n")

        rails = _discover_chip_rails(device_dir)

        assert len(rails) == 1
        assert rails[0].channel == 7


class TestDiscoverRails:
    """Tests for discover_rails function."""

    def test_discover_no_iio_root(self, tmp_path):
        """Test discovery when IIO root doesn't exist."""
        non_existent = tmp_path / "nonexistent"

        rails = discover_rails(iio_root=non_existent)

        assert rails == []

    def test_discover_empty_iio_root(self, mock_iio_root):
        """Test discovery with no IIO devices."""
        rails = discover_rails(iio_root=mock_iio_root)

        assert rails == []

    def test_discover_single_device(self, mock_iio_root):
        """Test discovery with a single device."""
        create_mock_device(
            mock_iio_root,
            0,
            "pac1954",
            {1: ("RAIL_A", 1.0), 2: ("RAIL_B", 2.0)},
        )

        rails = discover_rails(iio_root=mock_iio_root)

        assert len(rails) == 2
        assert rails[0].label == "RAIL_A"
        assert rails[1].label == "RAIL_B"

    def test_discover_mixed_supported_unsupported(self, mock_iio_root):
        """Test discovery with mix of supported and unsupported devices."""
        create_mock_device(
            mock_iio_root,
            0,
            "pac1954",
            {1: ("SUPPORTED_RAIL", 1.0)},
        )
        create_mock_device(
            mock_iio_root,
            1,
            "unsupported_device",
            {1: ("UNSUPPORTED_RAIL", 2.0)},
        )

        rails = discover_rails(iio_root=mock_iio_root)

        assert len(rails) == 1
        assert rails[0].label == "SUPPORTED_RAIL"

    def test_discover_with_custom_chip_ids(self, mock_iio_root):
        """Test discover_rails with custom chip IDs."""
        create_mock_device(
            mock_iio_root,
            0,
            "custom_chip",
            {1: ("CUSTOM_RAIL", 5.0)},
        )

        # Should not be discovered with default chips
        rails = discover_rails(iio_root=mock_iio_root)
        assert len(rails) == 0

        # Should be discovered with custom chip IDs
        rails = discover_rails(iio_root=mock_iio_root, chip_ids={"custom_chip"})
        assert len(rails) == 1
        assert rails[0].label == "CUSTOM_RAIL"


class TestPowerRailsClass:
    """Tests for PowerRails class."""

    def test_init_with_devices(self, mock_iio_root):
        """Test PowerRails initialization with devices present."""
        create_mock_device(
            mock_iio_root,
            0,
            "pac1954",
            {1: ("RAIL_1", 1.0), 2: ("RAIL_2", 2.0)},
        )

        pr = PowerRails(iio_root=mock_iio_root)

        assert len(pr.rails) == 2
        assert pr.get_rails() == pr.rails

    def test_init_no_devices(self, mock_iio_root):
        """Test PowerRails initialization with no devices."""
        pr = PowerRails(iio_root=mock_iio_root)

        assert pr.rails == []
        assert pr.get_rails() == []

    def test_read_rail_energy(self, mock_iio_root):
        """Test reading energy from a discovered rail."""
        device_dir = create_mock_device(
            mock_iio_root,
            0,
            "pac1954",
            {1: ("TEST_RAIL", 1.5)},
        )
        (device_dir / "in_energy1_raw").write_text("555666777\n")

        pr = PowerRails(iio_root=mock_iio_root)
        rail = pr.rails[0]

        energy = pr.read_rail_energy(rail)

        assert energy == 555666777.0

    def test_read_rail_energy_multiple_reads(self, mock_iio_root):
        """Test reading energy multiple times (simulating before/after suspend)."""
        device_dir = create_mock_device(
            mock_iio_root,
            0,
            "pac1954",
            {1: ("TEST_RAIL", 1.0)},
        )

        pr = PowerRails(iio_root=mock_iio_root)
        rail = pr.rails[0]

        # First read (before suspend)
        (device_dir / "in_energy1_raw").write_text("1000000\n")
        energy_before = pr.read_rail_energy(rail)
        assert energy_before == 1000000.0

        # Second read (after suspend)
        (device_dir / "in_energy1_raw").write_text("1050000\n")
        energy_after = pr.read_rail_energy(rail)
        assert energy_after == 1050000.0

        # Verify delta
        delta = energy_after - energy_before
        assert delta == 50000.0

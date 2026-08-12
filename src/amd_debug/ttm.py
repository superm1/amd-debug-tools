# SPDX-License-Identifier: MIT
"""TTM configuration tool"""

import argparse
import glob
import os
import subprocess

from amd_debug.common import (
    AmdTool,
    bytes_to_gb,
    gb_to_pages,
    get_system_mem,
    print_color,
    reboot,
    relaunch_sudo,
    version,
)

TTM_PARAM_PATH = "/sys/module/ttm/parameters/pages_limit"
MODPROBE_CONF_PATH = "/etc/modprobe.d/ttm.conf"
# Maximum percentage of total system memory to allow for TTM
MAX_MEMORY_PERCENTAGE = 90


def maybe_reboot() -> bool:
    """Prompt to reboot system"""
    response = input("Would you like to reboot the system now? (y/n): ").strip().lower()
    if response in ("y", "yes"):
        return reboot()
    return True


def is_ttm_in_initramfs(initramfs_path: str) -> bool:
    """
    Check if the ttm module is included in the initramfs.

    Args:
        initramfs_path: Path to the initramfs image (e.g., "/boot/initrd.img-6.12.74-amd64")

    Returns:
        bool: True if "gpu/drm/ttm/ttm.ko" is found, False otherwise
    """
    # Supported initramfs inspection tools
    inspector_tools = [
        (["lsinitramfs", initramfs_path], "initramfs-tools"),
        (["lsinitcpio", initramfs_path], "mkinitcpio"),
        (["lsinitrd", initramfs_path], "dracut"),
    ]

    # Check if "gpu/drm/ttm/ttm.ko" appears in the output
    for cmd, _package in inspector_tools:
        tool = cmd[0]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
            )
            return "gpu/drm/ttm/ttm.ko" in result.stdout.lower()
        except FileNotFoundError:
            continue
        except subprocess.CalledProcessError as e:
            print_color(f"Error running {tool}: {e}", "❌")
            return False

    print_color(
        "Error: no supported initramfs inspection tool found "
        "(tried: lsinitramfs, lsinitcpio, lsinitrd). "
        "Install initramfs-tools, mkinitcpio, or dracut.",
        "❌",
    )
    return False


def check_initramfs_images() -> bool:
    """Check if any initramfs image contains the TTM module.

    Returns:
        True if TTM is included in at least one initramfs image (regeneration needed).
        False if no initramfs images are found or TTM is not in any of them.
    """
    print_color("Checking if the initramfs image needs to be regenerated", "🐧")
    if not os.path.exists("/boot"):
        print_color("Warning: /boot not found. Is it mounted?", "🚦")
        return False

    # Collect initramfs images across all patterns, deduplicated by realpath
    patterns = [
        "/boot/initrd.img-*",  # Debian/Ubuntu
        "/boot/initramfs-*.img",  # Fedora/RHEL
        "/boot/initramfs-*",  # Arch (broadest, catches remaining)
    ]
    seen = set()
    all_images = []
    for pattern in patterns:
        for img in sorted(glob.glob(pattern)):
            real = os.path.realpath(img)
            if real not in seen:
                seen.add(real)
                all_images.append(img)

    if not all_images:
        print_color("No initramfs images found in /boot", "○")
        return False

    print_color(f"Found initramfs images: {all_images}", "🐧")

    for img in all_images:
        if is_ttm_in_initramfs(img):
            print_color(f"TTM module is included in initramfs: {img}", "✅")
            print_color("The initramfs image needs to be regenerated", "🐧")
            return True

    print_color("TTM module is not included in any initramfs image", "○")
    print_color("TTM loads from rootfs; initramfs regeneration not required", "○")
    return False


def regenerate_initramfs():
    """Regenerate initramfs image"""
    if not check_initramfs_images():
        print_color("Skipping initramfs regeneration", "○")
        return

    # Supported initramfs tools: (command, display_name)
    initramfs_tools = [
        (["update-initramfs", "-u"], "update-initramfs"),
        (["dracut", "--force"], "dracut"),
        (["mkinitcpio", "-P"], "mkinitcpio"),
    ]

    for cmd, name in initramfs_tools:
        if os.path.exists(f"/usr/sbin/{cmd[0]}") or os.path.exists(
            f"/usr/bin/{cmd[0]}"
        ):
            print_color(f"Updating initramfs using {name}", "🐧")
            try:
                subprocess.run(cmd, check=True)
                print_color("Initramfs updated successfully", "✅")
                return
            except (subprocess.CalledProcessError, FileNotFoundError) as e:
                print_color(f"Failed to update initramfs using {name}: {e}", "❌")
                continue

    print_color("No supported initramfs tool found", "❌")
    return


class AmdTtmTool(AmdTool):
    """Class for handling TTM page configuration"""

    def __init__(self, logging):
        log_prefix = "ttm" if logging else None
        super().__init__(log_prefix)

    def get(self) -> bool:
        """Read current page limit"""
        try:
            with open(TTM_PARAM_PATH, "r", encoding="utf-8") as f:
                pages = int(f.read().strip())
                gb_value = bytes_to_gb(pages)
                print_color(
                    f"Current TTM pages limit: {pages} pages ({gb_value:.2f} GB)", "💻"
                )
        except FileNotFoundError:
            print_color(f"Error: Could not find {TTM_PARAM_PATH}", "❌")
            return False

        total = get_system_mem()
        if total > 0:
            print_color(f"Total system memory: {total:.2f} GB", "💻")

        return True

    def set(self, gb_value) -> bool:
        """Set a new page limit"""
        relaunch_sudo()

        # Check against system memory
        total = get_system_mem()
        if total > 0:
            max_recommended_gb = total * MAX_MEMORY_PERCENTAGE / 100

            if gb_value > total:
                print_color(
                    f"{gb_value:.2f} GB is greater than total system memory ({total:.2f} GB)",
                    "❌",
                )
                return False

            if gb_value > max_recommended_gb:
                print_color(
                    f"Warning: The requested value ({gb_value:.2f} GB) exceeds {MAX_MEMORY_PERCENTAGE}% of your system memory ({max_recommended_gb:.2f} GB).",
                    "🚦",
                )
                response = (
                    input(
                        "This could cause system instability. Continue anyway? (y/n): "
                    )
                    .strip()
                    .lower()
                )
                if response not in ("y", "yes"):
                    print_color("Operation cancelled.", "🚦")
                    return False

        pages = gb_to_pages(gb_value)

        with open(MODPROBE_CONF_PATH, "w", encoding="utf-8") as f:
            f.write(f"options ttm pages_limit={pages}\n")
        print_color(
            f"Successfully set TTM pages limit to {pages} pages ({gb_value:.2f} GB)",
            "🐧",
        )
        print_color(f"Configuration written to {MODPROBE_CONF_PATH}", "🐧")

        regenerate_initramfs()

        print_color("NOTE: You need to reboot for changes to take effect.", "○")

        return maybe_reboot()

    def clear(self) -> bool:
        """Clears the page limit"""
        if not os.path.exists(MODPROBE_CONF_PATH):
            print_color(f"{MODPROBE_CONF_PATH} doesn't exist", "❌")
            return False

        relaunch_sudo()

        os.remove(MODPROBE_CONF_PATH)
        print_color(f"Configuration {MODPROBE_CONF_PATH} removed", "🐧")

        return maybe_reboot()


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Manage TTM pages limit")
    parser.add_argument("--set", type=float, help="Set pages limit in GB")
    parser.add_argument(
        "--clear", action="store_true", help="Clear a previously set page limit"
    )
    parser.add_argument(
        "--version", action="store_true", help="Show version information"
    )
    parser.add_argument(
        "--tool-debug",
        action="store_true",
        help="Enable tool debug logging",
    )

    return parser.parse_args()


def main() -> None | int:
    """Main function"""

    args = parse_args()
    tool = AmdTtmTool(args.tool_debug)
    ret = False

    if args.version:
        print(version())
        return
    elif args.set is not None:
        if args.set <= 0:
            print("Error: GB value must be greater than 0")
            return 1
        ret = tool.set(args.set)
    elif args.clear:
        ret = tool.clear()
    else:
        ret = tool.get()
    if ret is False:
        return 1
    return

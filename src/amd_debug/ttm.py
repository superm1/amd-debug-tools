# SPDX-License-Identifier: MIT
"""TTM configuration tool"""

import asyncio
import os
import argparse
import glob
import subprocess
from amd_debug.common import (
    AmdTool,
    bytes_to_gb,
    gb_to_pages,
    get_system_mem,
    relaunch_sudo,
    print_color,
    reboot,
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
    try:
        # Run lsinitramfs and search for "ttm" in the output
        result = subprocess.run(
            ["lsinitramfs", initramfs_path],
            capture_output=True,
            text=True,
            check=True
        )

        # Check if "gpu/drm/ttm/ttm.ko" appears in the output
        return "gpu/drm/ttm/ttm.ko" in result.stdout.lower()

    except subprocess.CalledProcessError as e:
        print(f"Error running lsinitramfs: {e}")
        return False
    except FileNotFoundError:
        print("Error: 'lsinitramfs' command not found. Is initramfs-tools installed?")
        return False

def check_initramfs_images() -> bool:
    """Check if initramfs images exist in /boot/"""
    print_color("Checking if the initramfs image needs to be regenerated", "🐧")
    if not os.path.exists("/boot"):
        print_color("Warning: /boot not found. Is it mounted?", "🚦")
        return False

    # Check for common initramfs patterns
    patterns = [
        '/boot/initrd.img-*',    # Debian/Ubuntu
        '/boot/initramfs-*.img', # Fedora/RHEL
        '/boot/initramfs-*'      # Arch
    ]

    for pattern in patterns:
        initramfs_files = glob.glob(pattern)
        if initramfs_files:
            print_color(f"Found initramfs images: {initramfs_files}", "🐧")

            latest_initramfs = max(initramfs_files)
            if is_ttm_in_initramfs(latest_initramfs):
                print_color(f"TTM module is included in initramfs: {latest_initramfs}", "✅")
                print_color("The initramfs image needs to be regenerated", "🐧")
                return True
            else:
                print_color(f"TTM module is not included in initramfs", "○")
                print_color(f"The initramfs image does not need to be regenerated", "○")
    return False

def regenerate_initramfs() -> bool:
    """Regenerate initramfs image"""
    if not check_initramfs_images():
        print_color("No initramfs images found, skipping regeneration", "○")
        return True  # Not an error condition

    # Supported initramfs tools
    initramfs_tools = [
        (["update-initramfs", "-u"], "Debian/Ubuntu"),
        (["dracut", "--force"], "Fedora/RHEL"),
        (["mkinitcpio", "-P"], "Arch Linux")
    ]

    for cmd, distro in initramfs_tools:
        if os.path.exists(f"/usr/sbin/{cmd[0]}") or os.path.exists(f"/usr/bin/{cmd[0]}"):
            print_color(f"Updating initramfs for {distro}...", "🐧")
            try:
                subprocess.run(cmd, check=True)
                print_color("Initramfs updated successfully", "✅")
                return True
            except subprocess.CalledProcessError as e:
                print_color(f"Failed to update initramfs: {e}", "❌")
                continue
            except FileNotFoundError:
                continue

    print_color("No supported initramfs tool found", "❌")
    return False


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

        if not regenerate_initramfs():
            print_color("Warning: Failed to update initramfs", "🚦")

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

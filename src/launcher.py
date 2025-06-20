#!/usr/bin/python3
# SPDX-License-Identifier: MIT
"""
This module is a launcher for the AMD Debug Tools package. It is meant for
launching various tools within the package without installation.
"""

import sys
import os

URL = "git://git.kernel.org/pub/scm/linux/kernel/git/superm1/amd-debug-tools.git"
try:
    import amd_debug
    from amd_debug.common import fatal_error
except ModuleNotFoundError:
    sys.exit(
        f"\033[91m{sys.argv[0]} can not be run standalone.\n"
        f"\033[0m\033[94mCheck out the full branch from {URL}\033[0m"
    )


def main():
    """Main function to launch the appropriate tool based on the script name."""
    try:
        return amd_debug.launch_tool(os.path.basename(sys.argv[0]))
    except ModuleNotFoundError as e:
        fatal_error(
            f"Missing dependency: {e}\n"
            f"Run ./install_deps.py to install dependencies."
        )


if __name__ == "__main__":
    sys.exit(main())

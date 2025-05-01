#!/usr/bin/python3
# SPDX-License-Identifier: MIT
import sys
import os

try:
    import amd_debug
except ModuleNotFoundError:
    sys.exit(
        f"\033[91m{sys.argv[0]} can not be run standalone.\n\033[0m\033[94mCheck out the full branch from git://git.kernel.org/pub/scm/linux/kernel/git/superm1/amd-debug-tools.git\033[0m"
    )

if __name__ == "__main__":
    sys.exit(amd_debug.launch_tool(os.path.basename(sys.argv[0])))

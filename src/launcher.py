#!/usr/bin/python3
# SPDX-License-Identifier: MIT
import sys
import os

try:
    from amd_debug.common import version as _
except ModuleNotFoundError:
    sys.exit(
        f"\033[91m{sys.argv[0]} can not be run standalone.\n\033[0m\033[94mCheck out the full branch from git://git.kernel.org/pub/scm/linux/kernel/git/superm1/amd-debug-tools.git\033[0m"
    )

if __name__ == "__main__":
    exe = os.path.basename(sys.argv[0])
    if exe == "amd_s2idle.py":
        from amd_debug import s2idle

        sys.exit(s2idle.main(False))
    elif exe == "amd_bios.py":
        from amd_debug import bios

        sys.exit(bios.main())
    elif exe == "amd_pstate.py":
        from amd_debug import pstate

        sys.exit(pstate.main())
    else:
        print(f"Unknown exe: {exe}")
        print("Usage: amd_s2idle.py | amd_bios.py | amd_pstate.py")
        sys.exit(1)

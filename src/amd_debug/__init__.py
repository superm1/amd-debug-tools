#!/usr/bin/python3
# SPDX-License-Identifier: MIT


def amd_s2idle():
    """Launch the amd-s2idle tool."""
    from . import s2idle  # pylint: disable=import-outside-toplevel

    return s2idle.main()


def amd_bios():
    """Launch the amd-bios tool."""
    from . import bios  # pylint: disable=import-outside-toplevel

    return bios.main()


def amd_pstate():
    """Launch the amd-pstate tool."""
    from . import pstate  # pylint: disable=import-outside-toplevel

    return pstate.main()


def amd_ttm():
    """Launch the amd-ttm tool."""
    from . import ttm  # pylint: disable=import-outside-toplevel

    return ttm.main()


def install_dep_superset():
    """Install all superset dependencies."""
    from . import installer  # pylint: disable=import-outside-toplevel

    return installer.install_dep_superset()


def launch_tool(tool_name):
    """Launch a tool with the given name and arguments."""
    tools = {
        "amd_s2idle.py": amd_s2idle,
        "amd_bios.py": amd_bios,
        "amd_pstate.py": amd_pstate,
        "amd_ttm.py": amd_ttm,
        "install_deps.py": install_dep_superset,
    }
    if tool_name in tools:
        return tools[tool_name]()
    else:
        print(f"\033[91mUnknown exe: {tool_name}\033[0m")
        return 1

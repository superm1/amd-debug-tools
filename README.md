# Helpful tools for debugging AMD Zen systems

This repository hosts open tools that are useful for debugging issues on AMD systems.

## amd_s2idle.py

`amd_s2idle.py` is a triaging script for common s2idle issues on AMD systems.  It checks
firmware, kernel configuration, and user configuration for known issues and flags them.

It can also be used for collecting statistics about suspend cycles and for stress testing.

## amd_pstate.py

`amd_pstate.py` is a triaging script used for identification of issues with amd-pstate.
It will capture some state from the system as well as from the machine specific registers that
amd-pstate uses.

## amd_bios.py

`amd_bios.py` is a a script that can be used to enable or disable BIOS AML debug logging
and to parse a kernel log that contains BIOS logs.

## psr.py

`psr.py` is a triaging script for capturing information about a sink that supports panel self
refresh.

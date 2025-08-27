# Helpful tools for debugging AMD Zen systems
[![codecov](https://codecov.io/github/superm1/amd-debug-tools/graph/badge.svg?token=Z9WTBZADGT)](https://codecov.io/github/superm1/amd-debug-tools)
[![PyPI](https://img.shields.io/pypi/v/amd-debug-tools.svg)](https://pypi.org/project/amd-debug-tools/)

This repository hosts open tools that are useful for debugging issues on AMD systems.

## Installation
### Distro (Arch)
`amd-debug-tools` has been [packaged for Arch Linux](https://archlinux.org/packages/extra/any/amd-debug-tools/) (and derivatives). You can install it using:

    pacman -Sy amd-debug-tools

### Using a python wheel (Generic)
It is suggested to install tools in a virtual environment either using
`pipx` or `python3 -m venv`.

#### From PyPI
`amd-debug-tools` is distributed as a python wheel, which is a
binary package format for Python. To install from PyPI, run the following
command:

    pipx install amd-debug-tools

### From source
To build the package from source, you will need to the `python3-build`
package natively installed by your distribution package manager. Then you
can generate and install a wheel by running the following commands:

    python3 -m build
    pipx install dist/amd-debug-tools-*.whl

### Ensuring path
If you have not used a `pipx` environment before, you may need to run the following command
to set up the environment:

    pipx ensurepath

This will add the `pipx` environment to your path.

## Running in-tree
Documentation about running directly from a git checkout is available [here](https://github.com/superm1/amd-debug-tools/blob/master/docs/amd-s2idle.md).

## Tools

Each tool has its own individual documentation page:
* [amd-s2idle](https://github.com/superm1/amd-debug-tools/blob/master/docs/amd-s2idle.md)
* [amd-bios](https://github.com/superm1/amd-debug-tools/blob/master/docs/amd-bios.md)
* [amd-pstate](https://github.com/superm1/amd-debug-tools/blob/master/docs/amd-pstate.md)
* [amd-ttm](https://github.com/superm1/amd-debug-tools/blob/master/docs/amd-ttm.md)


def amd_s2idle(packaged=False):
    from . import s2idle

    s2idle.main(packaged)


def amd_bios():
    from . import bios

    bios.main()


def amd_pstate():
    from . import pstate

    pstate.main()

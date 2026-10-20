# SPDX-License-Identifier: MIT

"""
This module contains the Intel specific capture helpers for the sleep
validator.

On Intel platforms the amount of time spent in the S0ix state is tracked by
the ``intel_pmc_core`` driver, which exposes the SLP_S0 residency counter
through debugfs.  The counter is cumulative, so the residency during a
sleep cycle is the difference between the values read before and after the
cycle.
"""

from amd_debug.intel import IntelPmcCore


class IntelCaptureHelpers:
    """Mixin providing the Intel specific capture helpers"""

    def capture_intel_s0ix(self):
        """Capture the S0ix substate information from the PMC core

        This is called before the system suspends so that the residency
        counters can be compared with the values after the resume.
        """
        pmc = IntelPmcCore()
        if not pmc.available:
            self.db.record_debug("Intel PMC core debugfs is not available")
            return
        self.pmc_core = pmc
        pmc.capture()
        self.s0ix_residency_before = pmc.slp_s0_residency
        self.s0ix_substates_before = dict(pmc.substate_residencies)
        # persist the baseline so that the post-resume capture can still
        # calculate the delta when it runs in a different process, e.g.
        # from the systemd sleep hook
        self.db.record_s0ix_baseline(
            self.s0ix_residency_before, self.s0ix_substates_before
        )
        if pmc.slp_s0_residency is not None:
            self.db.record_debug(
                f"SLP_S0 residency before suspend: {pmc.slp_s0_residency} usec"
            )
        if pmc.substate_residencies:
            debug_str = "S0ix substate residency before suspend\n"
            for name, value in pmc.substate_residencies.items():
                debug_str += f"│ {name}: {value}\n"
            self.db.record_debug(debug_str)

    def _intel_pmc(self):
        """Get the PMC core interface, recreating it if necessary

        The post-resume capture can run in a different process than the
        pre-suspend one, in which case the interface needs to be created
        again.
        """
        if getattr(self, "pmc_core", None) is None:
            pmc = IntelPmcCore()
            if not pmc.available:
                return None
            self.pmc_core = pmc
        return self.pmc_core

    def capture_intel_s0ix_residency(self) -> float:
        """Calculate the time spent in the S0ix state during the cycle

        The value is the difference between the SLP_S0 residency counter
        read after the resume and the one read before the suspend.
        """
        pmc = self._intel_pmc()
        if pmc is None:
            return 0
        before = getattr(self, "s0ix_residency_before", None)
        if before is None:
            # the pre-suspend baseline is missing, e.g. when this runs in
            # a different process; restore it from the database
            baseline = self.db.get_s0ix_baseline()
            if baseline is None:
                return 0
            before, self.s0ix_substates_before = baseline
            self.s0ix_residency_before = before
        if before is None:
            # the stored baseline has no counter value
            return 0
        after = pmc.read_slp_s0_residency()
        if after is None:
            return 0
        delta = after - before
        if delta < 0:
            # The counter wrapped or was reset
            return 0
        residency = delta / 10**6
        # store the residency so that capture_hw_sleep can fall back to
        # it when the suspend stats interface is unavailable
        self.s0ix_residency = residency
        if residency > 0:
            self.db.record_cycle_data(
                f"Spent {residency:.2f} seconds in S0ix", "💤"
            )
        return residency

    def capture_intel_substate_delta(self):
        """Capture the change in the S0ix substate residency counters"""
        before = getattr(self, "s0ix_substates_before", None)
        if not before:
            return
        pmc = self._intel_pmc()
        if pmc is None:
            return
        after = pmc.read_substate_residencies()
        if not after:
            return
        debug_str = "S0ix substate residency delta\n"
        for name, value in after.items():
            delta = value - before.get(name, value)
            debug_str += f"│ {name}: {delta}\n"
        self.db.record_debug(debug_str)

    def capture_intel_s0ix_blockers(self):
        """Capture the IPs that are blocking the deeper S0ix substates"""
        pmc = self._intel_pmc()
        if pmc is None:
            return
        requirements = pmc.read_substate_requirements()
        if not requirements:
            return
        from amd_debug.intel import (  # pylint: disable=import-outside-toplevel
            parse_substate_requirements,
        )

        blockers = parse_substate_requirements(requirements)
        if not blockers:
            return
        debug_str = "S0ix substate blockers\n"
        for element, required in blockers:
            debug_str += f"│ {element}: {', '.join(required)}\n"
        self.db.record_debug(debug_str)

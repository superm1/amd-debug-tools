# Platform support

`amd-s2idle` supports both AMD and Intel platforms.  The s2idle (Low Power
S0 Idle) state is an ACPI feature that is implemented by both vendors, but
the way the platform reports whether the deeper low power substates were
reached differs considerably between them.

The tool detects the CPU vendor by reading `/proc/cpuinfo` and then applies
the checks that are meaningful for that platform.

## Common checks

These checks are applied on all platforms:

* The ACPI FADT advertises the Low Power S0 Idle support
* The kernel is using the `s2idle` suspend method rather than `deep`
* The `LPS0` device interface is not disabled with `sleep_no_lps0`
* The kernel log is available and hasn't wrapped
* The Realtek r8169 network interfaces have Wake-on-LAN enabled (checked
  with `ethtool` when it is available; a disabled Wake-on-LAN is reported
  as a warning)
* A known problematic device firmware version is detected (through fwupd,
  when its bindings are available)
* The NVIDIA proprietary driver is configured correctly (if present)

## AMD specific checks

* The `amdgpu` driver is bound to the integrated GPU
* The `amdgpu` `ppfeaturemask` hasn't been overridden
* The `amd_pmc` driver is loaded (it is what puts the SoC into hardware sleep)
* The `pinctrl_amd` GPIO driver is loaded
* The `amd_hsmp` driver isn't conflicting with `amd_pmc`
* The SoC supports hardware sleep over s2idle
* The CPU hasn't been artificially limited with `maxcpus`
* The IOMMU is properly configured on affected platforms
* The storage devices are configured for `DevSlp`/`simple suspend`
* The DMCUB firmware is new enough to power gate the DPIA

## Intel specific checks

* The `intel_pmc_core` driver is loaded

  This driver exposes the residency and status diagnostics used by the
  analysis, and performs platform specific workarounds where they are
  needed for the deeper S0ix substates.

* An Intel graphics driver (`i915` or `xe`) is in use

  The integrated GPU coordinates the power states of the display and other
  IP blocks on the platform.

* The Intel display firmware (DMC) is loaded

  The display firmware needs to be present for the platform to reach the
  deeper substates.  This is only checkable with the `i915` driver, as the
  `xe` driver doesn't expose the same interface.

* The `LPS0` device interface is in use

  If the kernel was started with `sleep_no_lps0` the platform will refuse to
  enter the low power S0 idle state.

### Intel data capture

On Intel platforms the tool additionally captures the data exposed by the
`intel_pmc_core` driver in `/sys/kernel/debug/pmc_core`:

* `slp_s0_residency_usec` - the S0ix residency counter
* `substate_residencies` - the residency of each S0ix substate
* `substate_requirements` - the IP blocks that are required for each substate
* `substate_status_registers` - the latched status of the IP blocks
* `substate_live_status_registers` - the live status of the IP blocks
* `package_cstate_show` - the package C-state residency counters
* `die_c6_us_show` - the die C6 residency counter (the tile based
  successor of the package C6 state)

The residency counters are cumulative, so the tool reads them before the
system suspends and again after it resumes in order to work out how much
time was spent in the S0ix state during that cycle.  The time spent in
the S0ix state is verified through the SLP_S0 residency counter, and the
change in each substate residency counter is reported as well, which
shows which of the substates was actually entered.  The package and die
C-state residency counters are diffed the same way, which shows how deep
the system got below the core C-states.

### C-state capture

On both AMD and Intel platforms the tool captures the cpuidle counters of
every CPU through `/sys/devices/system/cpu/cpu*/cpuidle`.  When the kernel
exposes the suspend specific `s2idle/time` and `s2idle/usage` counters
inside each state directory, those are used, since they only track the
time spent in each C-state while the system is suspended.  Kernels
without them fall back to the regular `time` and `usage` counters, which
accumulate across runtime and suspend alike, so their difference shows
which C-states the CPUs were idling in around the sleep cycle rather
than the suspend residency itself.

The counters are cumulative, so the difference before and after a sleep
cycle shows which C-states the CPUs spent the cycle in and what the
deepest C-state entered was.

The `substate_requirements` file lists the IP blocks that are required for
each substate.  Any IP block that appears in that file is a potential
blocker for the deeper substates, and the tool reports them.

## NVIDIA proprietary driver support

The NVIDIA proprietary driver is supported on both AMD and Intel platforms.
The driver has to be configured properly for the system to reach the S0ix
state during s2idle, so the following is checked:

* The `NVreg_EnableS0ixPowerManagement` module parameter is set to `1`

  Without this the driver keeps the GPU video memory powered during
  s2idle instead of putting it into self refresh mode, or powering it
  off entirely when the memory usage is below the configured threshold.
  That means the GPU stays powered on and the platform can't reach the
  deeper substates.  It can be set with:

  ```
  # /etc/modprobe.d/nvidia.conf
  options nvidia NVreg_EnableS0ixPowerManagement=1
  ```

* The GPU supports video memory self refresh

  This is reported by the driver in
  `/proc/driver/nvidia/gpus/<BDF>/power`.  A GPU that doesn't support it
  can't be powered down during s2idle.

* The driver is notified of the suspend and resume events

  How this happens depends on which NVIDIA kernel modules are in use.

  The open kernel modules can notify the driver through the kernel
  sleep notifiers, which are active when the
  `NVreg_UseKernelSuspendNotifiers` module parameter is set.  The
  driver then handles saving and restoring its state itself:

  ```
  # /etc/modprobe.d/nvidia.conf
  options nvidia NVreg_UseKernelSuspendNotifiers=1
  ```

  The proprietary kernel modules instead rely on the
  `/proc/driver/nvidia/suspend` notification interface.  The
  `nvidia-suspend`, `nvidia-resume` and `nvidia-hibernate` systemd
  units notify the driver through it, and they can be enabled with:

  ```
  sudo systemctl enable nvidia-suspend.service nvidia-resume.service nvidia-hibernate.service
  ```

  When neither method is configured the tool reports the legacy method
  as a possible improvement rather than an error, since recent drivers
  handle the suspend transitions internally.

* The `nvidia-powerd` daemon is available

  The `nvidia-powerd` daemon manages Dynamic Boost on supported laptops,
  shifting power between the CPU and the GPU.  It is not required for
  s2idle; the tool only reports whether it is installed and enabled:

  ```
  sudo systemctl enable --now nvidia-powerd
  ```

  The status of the NVIDIA GPU power management is reported by the driver in
  `/proc/driver/nvidia/gpus/<BDF>/power`:

  ```
  S0ix Power Management:
   Platform Support:          Supported
   Status:                    Enabled
  ```

When the test is run with `--logind`, logind goes through
`systemd-suspend.service`, which runs the `nvidia-suspend` and
`nvidia-resume` units if they are enabled; the units are what notify
the driver in that case.

When the test suspends the system by writing to `/sys/power/state`
directly, the tool notifies the driver itself through
`/proc/driver/nvidia/suspend`.  The enabled units notify the driver on
every suspend regardless of how it was started, so when they are
enabled the tool stays out of the way to keep the driver from being
told about the same event twice.

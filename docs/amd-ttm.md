# Translation Table Manager (TTM) page setting tool
`amd-ttm` is a tool used for managing the TTM memory settings on AMD systems.
It manipulates the amount of memory allocated for the TTM. This amount can be increased or decreased by changing the kernel’s Translation Table Manager (TTM) page setting available at `/sys/module/ttm/parameters/pages_limit`.

## Querying current TTM settings
Running the tool with no arguments will display the current TTM settings.

```
❯ amd-ttm
💻 Current TTM pages limit: 16469033 pages (62.82 GB)
💻 Total system memory: 125.65 GB
```

## Setting new TTM value
Setting a new TTM page size is done by using the `--set` argument with the new limit (in GB).
The system must be rebooted for it to take effect and you will be prompted to do this automatically.

```
❯ amd-ttm --set 100
🐧 Successfully set TTM pages limit to 26214400 pages (100.00 GB)
🐧 Configuration written to /etc/modprobe.d/ttm.conf
○ NOTE: You need to reboot for changes to take effect.
Would you like to reboot the system now? (y/n): y
```

## Clearing the TTM value
To revert back to the kernel defaults, run the tool with the `--clear` argument.
The system must be rebooted for it to take effect and you will be prompted to do this automatically.
The kernel default (at the time of writing) is system memory / 2.

```
❯ amd-ttm --clear
🐧 Configuration /etc/modprobe.d/ttm.conf removed
Would you like to reboot the system now? (y/n): y
```
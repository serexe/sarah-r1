# Optional Ubuntu Touch idle-power helper

`idle_power.py` is source for a privileged helper, not an installed service. It reads a private app event journal and acquires/releases the platform `powerd-cli active` hold. Default lease: 3600 seconds from fresh physical input; operation cap: 300 seconds. Duplicate polls, old boot IDs, stale/replayed events, invalid journals, SSH activity and timers must not extend input leases. The helper never unlocks, injects input or forces suspend.

Review on a non-production device before installing. Required Linux facilities include BOOTTIME clock, no-follow file operations, flock, prctl parent-death handling and Ubuntu Touch powerd-cli. Use exactly one supervised helper instance. State remains helper-owned in `/var/lib/r1-idle-power/state.json`, with a private directory and lock. Do not expose it to the app.

`R1_DEVICE_USER` defaults to the standard Ubuntu Touch platform account `phablet`, not a project owner's identity. Set explicitly for a different OS account. `R1_POWER_EVENTS` optionally overrides the absolute journal path; only a trusted administrator may set it. It must refer to the configured user's mode-0600 regular file with no symlink traversal. App namespace changes require a matching journal path. Do not give the model/device arbitrary helper configuration access.

Native app journaling remains available even when no helper is installed. pytest tests policy, replay/freshness and a fake-holder process lifecycle; it never executes the real powerd-cli. No service units, remote installers, unlock, network-repair or observation scripts are included. Physical battery/suspend behavior was not verified for this candidate.

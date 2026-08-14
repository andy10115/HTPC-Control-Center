# Contributing to HTPC Control Center

HTPC Control Center is intentionally split into independent TV-provider and controller-wake backends. Please preserve that boundary.

## Development setup

Backend tests do not require GTK or physical hardware:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests
bash -n bootstrap.sh install.sh uninstall.sh
```

Running the GUI additionally requires Python 3.10+, GTK4, libadwaita 1.4+, and PyGObject from your distribution.

## Adding another TV operating system

The supported-provider registry lives in `src/htpc_control_center/tv/providers.py`. Android/Google TV is the only v1 provider.

A new provider should:

1. be developed and tested by someone with access to the actual TV platform;
2. implement reliable power control and a readiness/authentication path;
3. support input selection only when the platform exposes it safely and consistently;
4. keep user-facing setup graphical;
5. avoid requiring root unless the platform truly makes it unavoidable;
6. add parser/protocol tests that can run without the physical TV;
7. remain completely independent from `htpc_control_center.controller`.

Provider-specific onboarding can have its own GUI flow after the TV OS selection page. Do not force every platform into Android/ADB assumptions.

## Controller-wake changes

Controller wake can affect suspend reliability. Changes should preserve these invariants unless there is a tested reason not to:

- selection begins with the current `lsusb` identity but persistence is based on the resolved physical USB topology;
- only USB nodes that actually expose `power/wakeup` are written to the persistent rule;
- multiple selected receivers are supported and shared wake targets are deduplicated;
- the GUI remains unprivileged;
- the privileged helper independently re-resolves and validates selected sysfs nodes instead of trusting a wake-target list supplied by the GUI;
- the pre-suspend guard touches only HTPC Control Center's configured wake paths and re-arms them on exit/interruption;
- the default quiet window is currently 5 seconds.

Tests under `tests/test_controller_discovery.py` and `tests/test_controller_rules.py` provide fake sysfs trees specifically so this logic can be changed without guessing.

## Pull requests

Keep changes focused and explain what hardware/software was actually tested. For new TV providers or controller receiver behavior, include the relevant TV model, receiver/controller model, Linux distribution, and suspend mode when known.
## Release process

Application updates and the one-line installer intentionally consume GitHub **Releases**, not arbitrary commits from `main`.

For a stable release:

1. Update the version in `pyproject.toml` and `src/htpc_control_center/__init__.py`.
2. Update the AppStream release entry in `data/io.github.andy10115.HTPCControlCenter.metainfo.xml`.
3. Run the backend tests, Python compile check, and shell syntax checks.
4. Merge/push the release commit.
5. Tag the same commit (for example `v0.2.0`).
6. Publish a non-draft, non-prerelease GitHub Release for that tag.

No custom binary release asset is required for the current updater. GitHub's source tarball for the published release is the installation payload. Drafts and prereleases are deliberately not offered by the normal updater.


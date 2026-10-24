# Xemu Build Toolkit

Select an xemu source, incrementally update it, build it locally, and launch the
result with private configuration and writable media. This repository contains
only tools and instructions: no emulator source, binaries, ROMs, BIOS or saves.

## Sources

| Name | Repository | Source Branch |
| --- | --- | --- |
| `official` | https://github.com/xemu-project/xemu | `master` |
| `michaeljsr` | https://github.com/MichaelJSr/xemu-macos | `master` |
| `cosmicsnow` | https://github.com/CosmicSnow/xemu-for-macos | `master` |

`origin` points to this toolkit on GitHub. The other remotes are local Git
configuration, recreated by `python3 scripts/xemu.py setup` on a new clone.
They are never merged into `main` or pushed to `origin` by these scripts.

Only the source selected for a build is fetched. A detached worktree under
`.local/sources/<name>` uses the same Git object store as this repository, so
shared history is stored once and later downloads are incremental. Each source
has its own build/dependency directory, avoiding incompatible object reuse.
Tracked source changes stop an update rather than being reset or discarded.

## macOS Prerequisites

Install Xcode Command Line Tools and the build tools:

```sh
brew install python@3.13 coreutils pkg-config dylibbundler ninja cmake
```

The first build creates `.local/venv313` and installs the small Python requirement
if needed. The selected project's own `build.sh` provisions its remaining
dependencies. Source-specific dependencies and driver assets may require a first
download. No recursive firmware-submodule clone is performed by this toolkit.

## Build The Selected Source

```sh
./build-selected.sh michaeljsr
```

Replace the name with `official` or `cosmicsnow` to build that source instead.
`--jobs 6` controls build concurrency. The script uses the latest fetched
`master` commit, invokes the selected project's unmodified build script, and
records the exact commit, app hash and log in `.local/builds/<name>.json`.

The app is `.local/apps/<name>/xemu.app`. The last successfully built source is
recorded in `.local/selected.json`; failed builds do not change that selection.
Generated app packaging removes duplicate RPATH entries if present and signs
the local bundle again. Emulator source files are not patched.

## Configure ISO Files And Controller

Build first, connect the gamepad, and detect its SDL identity:

```sh
python3 scripts/xemu.py gamepads michaeljsr
```

The command needs normal hardware access; a restrictive sandbox may hide pads.
Create configuration using existing media and seed files:

```sh
python3 scripts/xemu.py configure michaeljsr \
  --media-root '/path/to/Microsoft - Xbox (OG)' \
  --hdd '/path/to/xbox_hdd.qcow2' \
  --eeprom '/path/to/eeprom.bin'
```

The media directory is expected to contain `Games.ISO/`, MCPX at
`_BIOS (Flash ROM)/Boot ROM (MCPX)/mcpx_1.0.bin`, and debug 4627 BIOS at
`_BIOS (Flash ROM)/Flash ROM/xbox-4627_debug.bin`. This setup uses that debug BIOS
with 128 MB RAM. The default test disc is
`OutRun 2 (Europe) (En,Fr,De,Es,It).xiso.iso`; use `--game` for another exact name.

The HDD and EEPROM are copied to `.local/runtime/<name>/`. Originals remain
untouched. An existing configuration is never overwritten: edit its TOML file
for later changes. One connected gamepad is selected automatically; with zero
or multiple devices pass `--gamepad` with the desired SDL GUID.

Port 1 uses the selected gamepad, port 2 the standard keyboard controller.
MichaelJSr uses Vulkan/MoltenVK, native internal resolution, a 640x480 startup
window and VSync. Official uses OpenGL; CosmicSnow selects Vulkan. A source must
actually build and boot successfully before its compatibility is claimed.

## Launch

```sh
./launch-xemu.command
# Or select a built and configured source explicitly:
python3 scripts/xemu.py launch michaeljsr
```

The launcher selects the private config, and for MichaelJSr also its private
`XEMU_BASE_PATH` for shader caches and other state. It is the user's interactive
launch; automation uses the separate bounded test below.

## Bounded OutRun 2 Boot Test

```sh
python3 scripts/test-boot.py --seconds 90
```

This probe is for MichaelJSr, whose QMP interface supplies real rendered
screenshots and input bindings. It clones the app and writable media into a
unique `.local/tests/` directory, uses the fork's lease/priority policy and
`xemu-fork-auto` marker, and writes frames, source provenance, renderer logs,
input bindings and process exit status. It closes only its own process.

Inspect the saved PNGs before calling the boot successful. Gamepad enumeration
and binding do not establish physical button/axis or rumble behavior. Results
from the separate Libretro core require their own frontend tests.

The initial build and OutRun 2 title-screen result, with its limits, are recorded
in [Local Validation](docs/VALIDATION.md).

## Local Storage And Publication

All source checkouts, dependencies, build products, app bundles, configurations,
media copies, caches, logs and historical evidence are under ignored `.local/`.
Only scripts, source URLs and documentation belong in this repository's `main`.
Building and launching do not commit, push or publish anything.

Keep `.local/runtime/` when cleaning: it contains writable state and saves.
Remove only source-specific generated build/cache directories when needed;
never delete a worktree directory directly. Use `git worktree remove` for a
clean unused source worktree after preserving any required ignored files.

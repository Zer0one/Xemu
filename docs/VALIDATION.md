# Local Validation — 2026-10-24

The initial toolkit setup was tested on Apple M4, macOS 26.5.1.

## Build

- Source: `MichaelJSr/xemu-macos`, branch `master`.
- Commit: `74a27096ed6bd7b5ad6d83ed7fd55230f9e98cb8` (release `v0.16.2`).
- Native ARM64 build using the source's unmodified `build.sh`.
- The toolkit's selected-source fetch/build/package path completed successfully.
- App provenance, SHA-256, dependency versions and complete build logs are kept
  privately under `.local/builds/` and `.local/logs/`.

## OutRun 2 Boot

A 90-second bounded windowed test used private app, HDD, EEPROM and cache copies.
The source's automation lease helper and `xemu-fork-auto` marker were used.

- Runtime logs confirmed Vulkan through **MoltenVK 1.4.2** and the **Apple M4
  Metal presenter**. This was not the official source's OpenGL path.
- The rendered screenshot after 30 seconds showed the OutRun 2 title and Start
  prompt. The final screenshot showed the Start prompt during a white transition.
- QMP recorded advancing display/guest-frame counters: approximately 1,815 at
  the first sample and 5,426 at the second; the displayed picture was not stale.
- The probe finished and reaped its own process with exit code 0.
- The configured Xbox Series X Controller GUID was preserved on port 1. No
  physical gamepad was enumerated during this session, including the emulator's
  own QMP input report. Port 2 had the keyboard controller. Physical buttons,
  axes and rumble remain unverified.

This establishes boot/title rendering, not a full gameplay or performance
qualification. Private PNGs, QMP replies, configs and runtime logs are retained
under `.local/tests/`; no media or private runtime files are published.

## Toolkit Checks

Automated tests cover selected-source-only fetching, rejection of unexpected
remote URLs, refusal to overwrite tracked source changes, isolation of writable
media/configuration, and preservation of a previous app when packaging fails.

```sh
python3 -m unittest discover -s tests -v
```

Official and CosmicSnow source URLs are configured as additional remotes. Their
builds have not been requalified through this toolkit in this setup.

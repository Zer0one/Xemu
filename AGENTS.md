# Xemu Build Toolkit

This repository contains scripts and documentation only. `main` must not contain
emulator sources, ROMs, BIOS, EEPROM, disk images, game saves or built apps.

- `origin` is the user's toolkit repository. `official`, `michaeljsr` and
  `cosmicsnow` are source remotes defined in `sources.json`.
- Fetch only the selected source. Source checkouts are detached worktrees under
  `.local/sources/`; do not merge, cherry-pick or customize emulator code.
- Respect the selected source's AGENTS.md and CONTRIBUTING.md when working there.
- Preserve dirty source checkouts and fail rather than resetting or cleaning them.
- Keep builds, apps, dependencies, configs and evidence under ignored `.local/`.
- Preserve writable HDD/EEPROM copies and never run against original writable media.
- For MichaelJSr automated runs use its lease helper, the `xemu-fork-auto` marker,
  a cloned app, an explicit config and a private `XEMU_BASE_PATH`.
- A built artifact is not boot evidence. Inspect a real rendered screenshot and
  record renderer, selected source commit, input bindings and test exit status.
- Do not infer physical controller operation from successful binding alone.
- Documents are English. Do not commit or push unless authorized by the user.

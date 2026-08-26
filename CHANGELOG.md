# Changelog

Versioning follows Home Assistant CalVer: **`YYYY.M.patch`** (M = month, patch increments for hotfixes — not the calendar day). First release of this repo was `2026.8.26`; hotfixes are `2026.8.26.1`, `.2`, …

## [2026.8.26.2] - 2026-08-26

### Changed

- New app icon (gauge / probe, no text) in repo root `icon.png` (HACS/GitHub) and `custom_components/ezo_complete/brand/` (HA Integrations).

## [2026.8.26.1] - 2026-08-26

### Changed

- Sleep is a switch (not a one-shot button). On = `Sleep`; off = wake. The switch turns off when a reading or a later command shows the circuit is awake.

## [2026.8.26] - 2026-08-26

### Added

- Generic EZO Complete integration: pH and ORP profiles, shared UART session, USB identify.
- pH: mid/low/high calibration, slope, temperature compensation from a HA sensor entity.
- Dated calibration archives + per-device restore file.

[2026.8.26.2]: https://github.com/echavet/ezo-complete/releases/tag/2026.8.26.2
[2026.8.26.1]: https://github.com/echavet/ezo-complete/releases/tag/2026.8.26.1
[2026.8.26]: https://github.com/echavet/ezo-complete/releases/tag/2026.8.26

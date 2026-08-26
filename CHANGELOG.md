# Changelog

Versioning follows Home Assistant CalVer: **`YYYY.M.patch`** (M = month, patch increments for hotfixes — not the calendar day). First release of this repo was `2026.8.26`; hotfixes are `2026.8.26.1`, `.2`, …

## [2026.8.26.4] - 2026-08-26

### Changed

- Calibration slots, reading sensor, extra diagnostics (pH slope / T) and probe-specific UART queries live on the probe profile. No pH/ORP `if` in platforms or coordinator I/O.
- Cal / Export / Import / Factory share `hold_stream()` (`C,0`, pause listen, restore stream).
- One `expected_reply` model (silent Sleep, ack, query, reading, export).
- pH compensation `T,<°C>` is sent only when the HA temperature moves by ≥ 0.1 °C (reset after identify / factory).

### Added

- `StabilityWindow` and `ExportStore` extracted from the coordinator.

## [2026.8.26.3] - 2026-08-26

### Fixed

- Calibration export no longer repeats the same Atlas hex block (pH and ORP). One cycle is kept; short ORP checksum lines (e.g. `9E6B`) are included.

### Added

- Live **reading stable** binary sensor (10 s span ≤ 0.05 pH / 5 mV). Cal buttons stay unavailable until stable. pH/ORP attributes: `source` (`factory` / `calibrated`), `min` / `max` / `span`.

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

[2026.8.26.4]: https://github.com/echavet/ezo-complete/releases/tag/2026.8.26.4
[2026.8.26.3]: https://github.com/echavet/ezo-complete/releases/tag/2026.8.26.3
[2026.8.26.2]: https://github.com/echavet/ezo-complete/releases/tag/2026.8.26.2
[2026.8.26.1]: https://github.com/echavet/ezo-complete/releases/tag/2026.8.26.1
[2026.8.26]: https://github.com/echavet/ezo-complete/releases/tag/2026.8.26

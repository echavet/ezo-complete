# Changelog

Versioning follows Home Assistant CalVer: **`YYYY.M.patch`** (M = month, patch increments for hotfixes — not the calendar day). First release of this repo was `2026.8.26`; hotfixes are `2026.8.26.1`, `.2`, …

## [Unreleased]

### Fixed

- **Stability gating with slow continuous intervals**: With `C,n` set to ≥3 s, the stability window could never accumulate enough samples (5 required in 10 s) to declare the reading stable, leaving calibration buttons permanently unavailable. The required sample count now adapts to the reading interval: `max(3, min(5, ⌊window/interval⌋+1))`. A 1 s interval still requires 5 samples; a 5 s interval requires only 3.

### Changed

- `reading_stable` binary sensor now exposes additional diagnostic attributes: `samples` (current count in window), `required_samples` (adaptive minimum), and `span_threshold`.

## [2026.8.26.5] - 2026-08-29

### Fixed

- pH slope sensor now keeps Atlas's third field (mid-point offset in mV). State is `acid%,base%[,offset_mV]`; attributes `acid` / `base` / `offset_mv`.
- `Slope,?` is queried right after a pH calibration so the sensor updates without reloading the integration.
- Periodic diagnostics while `C,n` is running no longer fire on every coordinator tick after 60 s (`_last_diag_at` was never refreshed). They now run at most once a minute, pause the stream (`C,0`) for the query burst, and leave `C,?` out of that burst so the continuous switch does not flicker.
- pH `T,<°C>` updates no longer write on top of a live continuous stream.

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

[2026.8.26.5]: https://github.com/echavet/ezo-complete/releases/tag/2026.8.26.5
[2026.8.26.4]: https://github.com/echavet/ezo-complete/releases/tag/2026.8.26.4
[2026.8.26.3]: https://github.com/echavet/ezo-complete/releases/tag/2026.8.26.3
[2026.8.26.2]: https://github.com/echavet/ezo-complete/releases/tag/2026.8.26.2
[2026.8.26.1]: https://github.com/echavet/ezo-complete/releases/tag/2026.8.26.1
[2026.8.26]: https://github.com/echavet/ezo-complete/releases/tag/2026.8.26

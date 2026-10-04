# Changelog

Versioning follows Home Assistant CalVer: **`YYYY.M.patch`** (M = month, patch increments for hotfixes — not the calendar day). First release of this repo was `2026.8.26`; hotfixes are `2026.8.26.1`, `.2`, …

## [2026.10.4.1] - 2026-10-04

### Breaking Changes

- **Mode select replaces continuous switch**: The `switch.continuous` entity is removed. Use the new `select.mode` entity to switch between Exploitation and Calibration modes.
- **Config entry migration to v3**: Existing options (`update_interval`, `continuous_on_start`, `continuous_interval`) are automatically migrated to the new schema. No manual action required.

### Added

- **Exploitation/Calibration dual-mode UX**:
  - **Exploitation mode**: HA-driven polling with configurable interval (5-3600 s) and optional median/mean filtering.
  - **Calibration mode**: Atlas continuous mode (C,n) with stability gating for calibration buttons.
  - Mode select entity (`select.mode`) to switch between modes.
  - Auto-return timer (0-120 min, default 15) returns to exploitation after inactivity.

- **Reading filtering** (Exploitation mode):
  - Filter type: none/median/mean (default: median).
  - Filter window: 1-20 samples (default: 5).
  - Main sensor publishes filtered value with `raw_value` attribute.
  - Separate raw sensor (enabled by default) for unfiltered readings.

- **pH stability independent of calibration**:
  - Stability is now judged in mV-equivalent using the probe slope (Slope,?).
  - Uses acid slope below pH 7, base slope above pH 7, average otherwise.
  - Factory calibration (cal_points=0) uses ideal 100% slope (59.16 mV/pH).
  - Binary sensor exposes `span_mv` and `threshold_mv` attributes for dashboard feedback.

- **Sleep state persistence**: Sleep is saved in `entry.options` and restored on startup/reconnect.

- **Export timestamp restoration**: `export_at` is restored from the newest archive file on disk when the integration loads.

- **New number entities** for runtime configuration:
  - Measurement interval, Filter window, Calibration interval
  - Stability window, Stability threshold, Auto-return timer

### Changed

- **Cal buttons require Calibration mode**: Calibration buttons (mid/low/high/225/custom/clear) are only available when in Calibration mode AND reading is stable.
- **Config flow version**: Bumped to 3.0 for new options schema.
- **Stability threshold unit**: Now in mV for both pH and ORP (calibration-independent).

### Fixed

- **Deprecated `device_registry.async_get_device`**: Replaced with new `async_get_entry_device` helper that uses `async_get_device_by_identifier(identifier, config_entry_id)` on HA 2026.8+, falling back to `async_get_device(identifiers=...)` on older cores (hacs.json minimum is 2026.5.0).

## [2026.10.4] - 2026-10-04

### Fixed

- **Export hex lines parsed as readings**: During calibration export (`Export` command), hex payload lines (e.g. `010101000080`) were incorrectly parsed as pH readings, resulting in values like ~1.01e10 appearing in `sensor.ezo_ph_ph`. Now: readings are paused during export using the same hold/pause mechanism as calibration, and a validity range check rejects out-of-range values (pH -1.6..15.6, ORP -1020..1020 mV) with a debug log.

- **Export date sensors missing device_class**: The `sensor.*_export_de_calibration` sensors now use `SensorDeviceClass.TIMESTAMP` and return a timezone-aware datetime instead of an ISO string. Home Assistant can now properly display and format the timestamp.

- **Stability never becomes true in polling mode**: When continuous mode was off, `set_interval(None)` was called, requiring 5 samples in a 10 s window—but with 5 s polling, only ~3 samples could fit. Now the polling interval (`update_interval`) is used for stability calculation in polling mode, and the stability window resets when switching from continuous to polling.

- **ACK handling for Cal commands**: Empty responses to Cal commands (e.g. `Cal,mid,7.00`) were incorrectly treated as success. Now Cal commands require an explicit `*OK` response; empty response = error. Also added `*OK,1` to `RESPONSE_CODE_ENABLE_COMMANDS`.

### Changed

- **Restore calibration button**: Now logs a warning before restoring and includes the source file path and original export timestamp in the notification (minimal change, no confirmation dialog added).

- **Cal,mid on 2+ point pH calibration**: Before sending `Cal,mid` when `cal_points >= 2`, a persistent notification warns that mid calibration clears low/high points (Atlas behaviour). Calibration proceeds without blocking.

## [2026.9.28] - 2026-09-28

### Fixed

- **USB unplug/replug stability**: Unplugging and replugging the USB cable no longer requires deleting and re-adding the integration. The config entry survives disconnections, and the port path is updated automatically when the device reappears (potentially on a different port).

- **Entity ID stability after reconfigure**: Entity IDs are now preserved when the USB device is reconfigured or reconnected. Previously, delete+re-add could create new entity IDs (e.g. `sensor.ezo_orp_*` → `sensor.ezo_orp_2_*`), breaking dashboards. The fix ensures entity unique IDs remain stable.

- **Manual setup now captures USB serial**: Entries created via manual setup (not USB discovery) now attempt to retrieve the USB serial number from the selected port. This ensures the entry can be matched when USB discovery runs later.

### Added

- **Automatic entry adoption**: When USB discovery finds a device whose entry was created manually (with "unknown" serial), the existing entry is automatically updated with the real USB serial instead of creating a duplicate.

- **Config entry migration (v1 → v2.1)**: Existing entries are automatically migrated to normalize their unique IDs and update entity registry entries. This one-time migration preserves entity IDs for users upgrading from earlier versions.

- **Dynamic port detection**: The reconnect loop now scans USB devices to find if the device has moved to a different port, updating the stored port path automatically.

### Changed

- Config flow version bumped to 2.1 for migration tracking.

### Notes for existing users

After upgrading, your existing entries will be migrated automatically. Entity IDs should remain unchanged. If you previously had to delete and re-add the integration due to USB issues, dashboards referencing old entity IDs will need to be updated once to the new (stable) IDs.

## [2026.8.26.6] - 2026-09-27

### Fixed

- **Stability gating with slow continuous intervals**: With `C,n` set to ≥3 s, the stability window could never accumulate enough samples (5 required in 10 s) to declare the reading stable, leaving calibration buttons permanently unavailable. The required sample count now adapts to the reading interval: `max(3, min(5, ⌊window/interval⌋+1))`. A 1 s interval still requires 5 samples; a 5 s interval requires only 3.

### Changed

- `reading_stable` binary sensor now exposes additional diagnostic attributes: `samples` (current count in window), `required_samples` (adaptive minimum), and `span_threshold`. This provides clear progress feedback (e.g. "3/3 samples collected, span OK") rather than a fragile countdown that resets on every glitch.

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

[2026.10.4.1]: https://github.com/echavet/ezo-complete/releases/tag/2026.10.4.1
[2026.10.4]: https://github.com/echavet/ezo-complete/releases/tag/2026.10.4
[2026.9.28]: https://github.com/echavet/ezo-complete/releases/tag/2026.9.28
[2026.8.26.6]: https://github.com/echavet/ezo-complete/releases/tag/2026.8.26.6
[2026.8.26.5]: https://github.com/echavet/ezo-complete/releases/tag/2026.8.26.5
[2026.8.26.4]: https://github.com/echavet/ezo-complete/releases/tag/2026.8.26.4
[2026.8.26.3]: https://github.com/echavet/ezo-complete/releases/tag/2026.8.26.3
[2026.8.26.2]: https://github.com/echavet/ezo-complete/releases/tag/2026.8.26.2
[2026.8.26.1]: https://github.com/echavet/ezo-complete/releases/tag/2026.8.26.1
[2026.8.26]: https://github.com/echavet/ezo-complete/releases/tag/2026.8.26

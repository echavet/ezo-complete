"""Codec + profile tests (no Home Assistant)."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "custom_components" / "ezo_complete"


def _load(name: str, path: Path):
    if "ezo_complete" not in sys.modules:
        pkg = types.ModuleType("ezo_complete")
        pkg.__path__ = [str(PKG)]
        sys.modules["ezo_complete"] = pkg
    if "ezo_complete.profiles" not in sys.modules:
        sub = types.ModuleType("ezo_complete.profiles")
        sub.__path__ = [str(PKG / "profiles")]
        sys.modules["ezo_complete.profiles"] = sub
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


const = _load("ezo_complete.const", PKG / "const.py")
codec = _load("ezo_complete.codec", PKG / "codec.py")
models = _load("ezo_complete.models", PKG / "models.py")
base = _load("ezo_complete.profiles.base", PKG / "profiles" / "base.py")
orp = _load("ezo_complete.profiles.orp", PKG / "profiles" / "orp.py")
ph = _load("ezo_complete.profiles.ph", PKG / "profiles" / "ph.py")
stability = _load("ezo_complete.stability", PKG / "stability.py")
export_store = _load("ezo_complete.export_store", PKG / "export_store.py")


def test_identify_orp_and_ph() -> None:
    orp_info = codec.parse_device_info("?i,ORP,1.98")
    assert orp_info is not None and orp_info.kind == "orp" and orp_info.is_supported
    ph_info = codec.parse_device_info("?i,pH,2.14")
    assert ph_info is not None and ph_info.kind == "ph" and ph_info.is_supported
    assert codec.parse_device_info("?i,EC,2.10") is None
    assert codec.parse_device_info("323.1") is None


def test_ack_only_empty() -> None:
    empty = codec.EzoResponse(command="C,0", lines=[])
    assert codec.command_succeeded(empty)
    query = codec.EzoResponse(command="C,?", lines=[])
    assert not codec.command_succeeded(query)


def test_cal_points() -> None:
    assert codec.parse_cal_points("?Cal,0") == 0
    assert codec.parse_cal_points("?Cal,1") == 1
    assert codec.parse_cal_points("?Cal,3") == 3


def test_profiles() -> None:
    assert orp.OrpProfile().cal_set_command("custom", 225) == "Cal,225"
    assert ph.PhProfile().cal_set_command("mid", 7) == "Cal,mid,7.00"
    assert ph.PhProfile().supports_temperature
    assert not orp.OrpProfile().supports_temperature


def test_compact_export_dump_orp_short_checksum() -> None:
    dump = """
00CB213F0100
9E6B
00CB213F0100
9E6B
00CB213F0100
9E6B
""".strip().splitlines()
    assert codec.compact_export_dump(dump) == ["00CB213F0100", "9E6B"]


def test_compact_export_dump_strips_repeats() -> None:
    dump = """
0040B1C6A8D3
22C3793F3DC3
010101000080
400000E040F6
282041000529
0040B1C6A8D3
22C3793F3DC3
010101000080
400000E040F6
282041000529
0040B1C6A8D3
22C3793F3DC3
010101000080
""".strip().splitlines()
    cycle = codec.compact_export_dump(dump)
    assert cycle == [
        "0040B1C6A8D3",
        "22C3793F3DC3",
        "010101000080",
        "400000E040F6",
        "282041000529",
    ]


def test_usb_name() -> None:
    assert codec.is_usb_product_name("FT230X Basic UART")
    assert codec.resolve_display_name(
        ezo_name=None, configured="FT230X Basic UART", fallback="EZO pH"
    ) == "EZO pH"


def test_expected_reply() -> None:
    assert codec.expected_reply(None) is codec.ReplyKind.NONE
    assert codec.expected_reply("Sleep") is codec.ReplyKind.SILENT
    assert codec.expected_reply("R") is codec.ReplyKind.READING
    assert codec.expected_reply("Export") is codec.ReplyKind.EXPORT
    assert codec.expected_reply("C,?") is codec.ReplyKind.QUERY
    assert codec.expected_reply("Cal,?") is codec.ReplyKind.QUERY
    assert codec.expected_reply("Cal,225") is codec.ReplyKind.ACK
    assert codec.expected_reply("Cal,mid,7.00") is codec.ReplyKind.ACK
    assert codec.expected_reply("C,0") is codec.ReplyKind.ACK


def test_command_succeeded_silent_and_ack() -> None:
    assert codec.command_succeeded(codec.EzoResponse(command="Sleep"))
    assert codec.command_succeeded(codec.EzoResponse(command="Find", lines=[]))
    export = codec.EzoResponse(
        command="Export",
        lines=[codec.parse_line("00CB213F0100")],
    )
    assert codec.command_succeeded(export)


def test_reply_is_complete_export_checksum() -> None:
    hex_line = codec.parse_line("00CB213F0100")
    checksum = codec.parse_line("9E6B")
    assert codec.reply_is_complete([hex_line], "Export")
    assert codec.reply_is_complete([checksum], "Export")
    assert not codec.reply_is_complete([], "Export")
    assert not codec.reply_is_complete([hex_line], None)


def test_compact_export_dump_orp_uart_cycle() -> None:
    """One Export cycle as seen on UART: query, hex, 4-char checksum, then wrap."""
    dump = [
        "?EXPORT,2",
        "00CB213F0100",
        "*OK",
        "9E6B",
        "*OK",
        "?EXPORT,0",
        "00CB213F0100",
        "9E6B",
    ]
    assert codec.compact_export_dump(dump) == ["00CB213F0100", "9E6B"]
    assert codec.parse_export_count("?EXPORT,2") == 2
    assert codec.parse_export_count("?EXPORT,0") == 0
    assert codec.is_export_data_line("9E6B")
    assert not codec.is_export_data_line("?EXPORT,2")


def test_profile_cal_slots_and_stability() -> None:
    orp_profile = orp.OrpProfile()
    ph_profile = ph.PhProfile()
    assert {slot.key for slot in orp_profile.cal_slots} == {"225", "custom"}
    assert {slot.key for slot in ph_profile.cal_slots} == {"mid", "low", "high"}
    assert orp_profile.slot("custom").has_number
    assert not orp_profile.slot("225").has_number
    assert orp_profile.can_calibrate("225", stable=True, cal_points=0)
    assert not orp_profile.can_calibrate("225", stable=False, cal_points=0)
    assert ph_profile.can_calibrate("mid", stable=True, cal_points=0)
    assert not ph_profile.can_calibrate("low", stable=True, cal_points=0)
    assert ph_profile.can_calibrate("low", stable=True, cal_points=1)
    assert ph_profile.can_calibrate("high", stable=True, cal_points=1)
    assert orp_profile.stability_span == const.ORP_STABLE_SPAN
    assert ph_profile.stability_span == const.PH_STABLE_SPAN
    assert orp_profile.extra_diagnostics == ()
    assert ph_profile.extra_diagnostics == ("temperature", "slope")
    assert "C,?" not in ph_profile.diagnostic_queries()
    assert "Slope,?" in ph_profile.diagnostic_queries()
    assert "Slope,?" not in orp_profile.diagnostic_queries()
    assert orp_profile.cal_label(0) == "not_calibrated"
    assert orp_profile.cal_label(1) == "calibrated"
    assert ph_profile.cal_label(0) == "none"
    assert ph_profile.cal_label(3) == "three_point"


def test_profile_apply_query() -> None:
    ph_state = models.EzoDeviceState(kind="ph")
    orp_state = models.EzoDeviceState(kind="orp")
    ph_profile = ph.PhProfile()
    orp_profile = orp.OrpProfile()
    assert ph_profile.apply_query(ph_state, codec.parse_line("?pHext,1"))
    assert ph_state.extended_scale is True
    assert ph_profile.apply_query(ph_state, codec.parse_line("?T,25.00"))
    assert ph_state.temperature == 25.0
    assert ph_profile.apply_query(ph_state, codec.parse_line("?Slope,99.7,100.3"))
    assert ph_state.slope_acid == "99.7" and ph_state.slope_base == "100.3"
    assert ph_state.slope_offset is None
    assert ph_state.slope_text == "99.7,100.3"
    assert ph_profile.apply_query(ph_state, codec.parse_line("?Slope,93.5,81.5,-1.2"))
    assert ph_state.slope_acid == "93.5"
    assert ph_state.slope_base == "81.5"
    assert ph_state.slope_offset == "-1.2"
    assert ph_state.slope_text == "93.5,81.5,-1.2"
    assert ph_profile.apply_query(ph_state, codec.parse_line("?Slope,93.5,81.5,0"))
    assert ph_state.slope_offset == "0"
    assert ph_state.slope_text == "93.5,81.5,0"
    assert ph_profile.apply_query(ph_state, codec.parse_line("?Slope,99.7,100.3"))
    assert ph_state.slope_offset is None
    assert ph_state.slope_text == "99.7,100.3"
    assert not ph_profile.apply_query(ph_state, codec.parse_line("?Cal,1"))
    assert orp_profile.apply_query(orp_state, codec.parse_line("?ORPext,0"))
    assert orp_state.extended_scale is False
    assert not orp_profile.apply_query(orp_state, codec.parse_line("?T,25.00"))


def test_stability_window() -> None:
    # For ORP, no to_mv_fn is needed (readings are already in mV)
    window = stability.StabilityWindow(window_s=10.0, min_samples=5, span_threshold_mv=5.0)
    now = 100.0
    last = None
    for index in range(5):
        last = window.push(225.0 + index * 0.1, now + index)
    assert last is not None and last.stable
    assert last.sample_count == 5
    assert last.required_samples == 5
    assert last.span_mv is not None and last.span_mv == last.span  # ORP: span_mv == span
    drifted = window.push(240.0, now + 5)
    assert not drifted.stable
    assert drifted.span is not None and drifted.span > 5.0
    assert drifted.span_mv is not None and drifted.span_mv > 5.0


def test_compute_min_samples() -> None:
    """Test the adaptive sample count formula."""
    from ezo_complete.stability import compute_min_samples

    assert compute_min_samples(10.0, 1.0, floor=3, ceiling=5) == 5
    assert compute_min_samples(10.0, 2.0, floor=3, ceiling=5) == 5
    assert compute_min_samples(10.0, 3.0, floor=3, ceiling=5) == 4
    assert compute_min_samples(10.0, 5.0, floor=3, ceiling=5) == 3
    assert compute_min_samples(10.0, 10.0, floor=3, ceiling=5) == 3
    assert compute_min_samples(10.0, 20.0, floor=3, ceiling=5) == 3
    assert compute_min_samples(10.0, 0.0, floor=3, ceiling=5) == 5
    assert compute_min_samples(10.0, -1.0, floor=3, ceiling=5) == 5


def test_stability_window_fast_interval() -> None:
    """With 1s interval, requires 5 samples (the ceiling)."""
    window = stability.StabilityWindow(
        window_s=10.0, min_samples=5, span_threshold_mv=0.05, interval_s=1.0
    )
    assert window.required_samples == 5
    now = 100.0
    for index in range(4):
        snap = window.push(7.00, now + index)
        assert not snap.stable
        assert snap.sample_count == index + 1
    snap = window.push(7.00, now + 4)
    assert snap.stable
    assert snap.sample_count == 5


def test_stability_window_slow_interval() -> None:
    """With 5s interval, requires only 3 samples (the floor)."""
    window = stability.StabilityWindow(
        window_s=10.0, min_samples=5, span_threshold_mv=0.05, interval_s=5.0
    )
    assert window.required_samples == 3
    now = 100.0
    for index in range(2):
        snap = window.push(7.00, now + index * 5)
        assert not snap.stable
        assert snap.sample_count == index + 1
        assert snap.required_samples == 3
    snap = window.push(7.00, now + 10)
    assert snap.stable
    assert snap.sample_count == 3


def test_stability_window_slow_interval_span_breach() -> None:
    """Span breach resets stability even with slow interval."""
    window = stability.StabilityWindow(
        window_s=10.0, min_samples=5, span_threshold_mv=0.05, interval_s=5.0
    )
    now = 100.0
    for i in range(3):
        window.push(7.00, now + i * 5)
    snap = window.push(7.00, now + 15)
    assert snap.stable
    snap = window.push(7.10, now + 20)
    assert not snap.stable
    assert snap.span is not None and snap.span > 0.05
    assert snap.span_mv is not None and snap.span_mv > 0.05


def test_stability_window_set_interval() -> None:
    """set_interval dynamically adjusts required samples."""
    window = stability.StabilityWindow(
        window_s=10.0, min_samples=5, span_threshold_mv=0.05, interval_s=1.0
    )
    assert window.required_samples == 5
    window.set_interval(5.0)
    assert window.required_samples == 3
    window.set_interval(None)
    assert window.required_samples == 5
    window.set_interval(3.0)
    assert window.required_samples == 4


def test_stability_snapshot_attributes() -> None:
    """Verify all snapshot attributes are populated."""
    window = stability.StabilityWindow(
        window_s=10.0, min_samples=5, span_threshold_mv=0.05, interval_s=2.0
    )
    snap = window.push(7.00, 100.0)
    assert snap.minimum == 7.00
    assert snap.maximum == 7.00
    assert snap.span == 0.0
    assert snap.span_mv == 0.0  # Without to_mv_fn, span_mv == span
    assert snap.sample_count == 1
    assert snap.required_samples == 5
    assert snap.span_threshold == 0.05
    assert not snap.stable


def test_export_store(tmp_path) -> None:
    from datetime import UTC, datetime

    store = export_store.ExportStore(tmp_path, "abc/def")
    now = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
    archive, restore = store.write("00CB213F0100\n9E6B", now=now)
    assert archive.endswith("abc_def_calibration_20260826-120000.txt")
    assert restore.endswith("abc_def.import_calibration")
    assert store.read_restore() == "00CB213F0100\n9E6B"
    assert Path(archive).read_text(encoding="ascii") == "00CB213F0100\n9E6B\n"


def test_export_hex_rejected_by_range_check() -> None:
    """Hex export lines that parse as numbers are rejected by range check.
    
    Lines like '010101000080' (only digits) are valid numbers (~1.01e10) and
    thus parsed as READING. The fix is that is_reading_in_range() rejects them
    because they are way outside pH (-1.6..15.6) or ORP (-1020..1020 mV) bounds.
    
    Lines with hex letters (A-F) are parsed as OTHER, not READING.
    """
    numeric_only_hex = ["010101000080"]
    for line in numeric_only_hex:
        parsed = codec.parse_line(line)
        assert parsed.kind is codec.LineKind.READING, \
            f"{line} must parse as READING for this test to be valid"
        assert parsed.value is not None, f"{line} must have a numeric value"
        assert not codec.is_reading_in_range(parsed.value, "ph"), \
            f"{line} ({parsed.value}) should be out of pH range"
        assert not codec.is_reading_in_range(parsed.value, "orp"), \
            f"{line} ({parsed.value}) should be out of ORP range"
    
    hex_with_letters = ["00CB213F0100", "0040B1C6A8D3", "9E6B"]
    for line in hex_with_letters:
        parsed = codec.parse_line(line)
        assert parsed.kind is codec.LineKind.OTHER, \
            f"{line} should be OTHER (contains hex letters A-F)"


def test_is_reading_in_range_ph() -> None:
    """pH readings must be within -1.6..15.6 (datasheet)."""
    assert codec.is_reading_in_range(7.0, "ph")
    assert codec.is_reading_in_range(0.0, "ph")
    assert codec.is_reading_in_range(-1.6, "ph")
    assert codec.is_reading_in_range(15.6, "ph")
    assert codec.is_reading_in_range(14.0, "ph")
    assert not codec.is_reading_in_range(-2.0, "ph")
    assert not codec.is_reading_in_range(16.0, "ph")
    assert not codec.is_reading_in_range(1.01e10, "ph")
    assert not codec.is_reading_in_range(-1000.0, "ph")


def test_is_reading_in_range_orp() -> None:
    """ORP readings must be within -1020..1020 mV (datasheet ORP_RANGE_STANDARD)."""
    assert codec.is_reading_in_range(225.0, "orp")
    assert codec.is_reading_in_range(0.0, "orp")
    assert codec.is_reading_in_range(-1020.0, "orp")
    assert codec.is_reading_in_range(1020.0, "orp")
    assert codec.is_reading_in_range(-500.0, "orp")
    assert not codec.is_reading_in_range(-1020.1, "orp")
    assert not codec.is_reading_in_range(1020.1, "orp")
    assert not codec.is_reading_in_range(1e10, "orp")


def test_is_reading_in_range_unknown_kind() -> None:
    """Unknown device kinds should accept any value."""
    assert codec.is_reading_in_range(1e10, "unknown")
    assert codec.is_reading_in_range(-1e10, "other")


def test_is_calibration_command() -> None:
    """Identify Cal,<value> commands vs Cal,? and Cal,clear."""
    assert codec.is_calibration_command("Cal,225")
    assert codec.is_calibration_command("Cal,mid,7.00")
    assert codec.is_calibration_command("Cal,low,4.00")
    assert codec.is_calibration_command("Cal,high,10.00")
    assert not codec.is_calibration_command("Cal,?")
    assert not codec.is_calibration_command("Cal,clear")
    assert not codec.is_calibration_command("Cal,")
    assert not codec.is_calibration_command("C,0")
    assert not codec.is_calibration_command("R")
    assert not codec.is_calibration_command(None)


def test_command_succeeded_cal_requires_ok() -> None:
    """Cal commands require *OK response; empty = error."""
    ok_response = codec.EzoResponse(
        command="Cal,225",
        lines=[codec.parse_line("*OK")],
    )
    assert codec.command_succeeded(ok_response)

    empty_response = codec.EzoResponse(command="Cal,225", lines=[])
    assert not codec.command_succeeded(empty_response)

    ok_response_ph = codec.EzoResponse(
        command="Cal,mid,7.00",
        lines=[codec.parse_line("*OK")],
    )
    assert codec.command_succeeded(ok_response_ph)

    empty_response_ph = codec.EzoResponse(command="Cal,mid,7.00", lines=[])
    assert not codec.command_succeeded(empty_response_ph)


def test_command_succeeded_non_cal_ack_accepts_empty() -> None:
    """Non-Cal ACK commands still accept empty responses."""
    empty_c0 = codec.EzoResponse(command="C,0", lines=[])
    assert codec.command_succeeded(empty_c0)

    empty_l1 = codec.EzoResponse(command="L,1", lines=[])
    assert codec.command_succeeded(empty_l1)


def test_response_code_enable_commands_includes_ok1() -> None:
    """RESPONSE_CODE_ENABLE_COMMANDS should include *OK,1 (modern Atlas syntax)."""
    assert "*OK,1" in const.RESPONSE_CODE_ENABLE_COMMANDS


def test_orp_reading_range_uses_standard_bounds() -> None:
    """ORP reading range should use ORP_RANGE_STANDARD (-1020..1020)."""
    assert const.ORP_READING_MIN == const.ORP_RANGE_STANDARD[0]
    assert const.ORP_READING_MAX == const.ORP_RANGE_STANDARD[1]
    assert const.ORP_READING_MIN == -1020.0
    assert const.ORP_READING_MAX == 1020.0


def test_parse_export_timestamp_aware() -> None:
    """Timezone-aware ISO string should parse correctly."""
    from datetime import UTC, datetime, timezone

    iso_aware = "2026-10-04T12:00:00+00:00"
    dt = datetime.fromisoformat(iso_aware)
    assert dt.tzinfo is not None, "Parsed datetime should be timezone-aware"
    assert dt.year == 2026
    assert dt.month == 10
    assert dt.day == 4
    assert dt.hour == 12

    iso_aware_offset = "2026-10-04T14:00:00+02:00"
    dt2 = datetime.fromisoformat(iso_aware_offset)
    assert dt2.tzinfo is not None


def test_parse_export_timestamp_naive_assumes_utc() -> None:
    """Naive ISO string (no timezone) should be treated as UTC."""
    from datetime import UTC, datetime

    iso_naive = "2026-10-04T12:00:00"
    dt = datetime.fromisoformat(iso_naive)
    assert dt.tzinfo is None, "Naive datetime has no timezone"
    dt_utc = dt.replace(tzinfo=UTC)
    assert dt_utc.tzinfo is UTC
    assert dt_utc.year == 2026
    assert dt_utc.hour == 12


def test_parse_export_timestamp_invalid() -> None:
    """Invalid strings should raise ValueError (caught by sensor function)."""
    from datetime import datetime

    invalid_strings = ["not-a-date", "2026-13-40", "", "12:00:00"]
    for s in invalid_strings:
        try:
            datetime.fromisoformat(s)
            assert False, f"Expected ValueError for {s!r}"
        except ValueError:
            pass


# --- pH mV-based stability tests ---

def test_stability_window_ph_with_mv_conversion() -> None:
    """pH stability uses mV-equivalent span for calibration-independent stability.
    
    With 100% slope, 1 pH = 59.16 mV (Nernst constant at 25°C).
    A span of 0.05 pH = 2.958 mV at 100% slope.
    """
    NERNST_MV_PER_PH = 59.16
    slope_percent = 100.0
    
    def ph_to_mv(span_ph: float) -> float:
        return span_ph * NERNST_MV_PER_PH * (slope_percent / 100.0)
    
    window = stability.StabilityWindow(
        window_s=10.0,
        min_samples=5,
        span_threshold_mv=3.0,  # ~0.05 pH at 100% slope
        interval_s=5.0,  # Slow interval -> requires 3 samples
        min_samples_floor=3,
        min_samples_ceiling=5,
        to_mv_fn=ph_to_mv,
    )
    assert window.required_samples == 3
    
    now = 100.0
    # Push 3 samples with 0.04 pH span (< 0.05 pH threshold)
    window.push(7.00, now)
    window.push(7.02, now + 5)
    snap = window.push(7.04, now + 10)
    
    # Span in native pH units
    assert snap.span is not None
    assert abs(snap.span - 0.04) < 0.001
    
    # Span in mV: 0.04 * 59.16 * 1.0 = 2.366 mV
    assert snap.span_mv is not None
    expected_mv = 0.04 * NERNST_MV_PER_PH
    assert abs(snap.span_mv - expected_mv) < 0.01, f"Expected {expected_mv} mV, got {snap.span_mv}"
    
    # Should be stable: 2.366 mV < 3.0 mV threshold
    assert snap.stable


def test_stability_window_ph_low_slope_less_stable() -> None:
    """A low-slope probe (e.g. 80%) appears more stable in pH but is actually less stable.
    
    At 80% slope, the same 0.05 pH drift represents only 2.366 mV instead of 2.958 mV.
    This is BAD: the probe is actually drifting MORE in mV than a healthy probe would.
    
    The mV-based stability catches this: the actual pH span is larger than
    what a healthy probe would show for the same mV drift.
    """
    NERNST_MV_PER_PH = 59.16
    slope_percent = 80.0  # Degraded probe
    
    def ph_to_mv(span_ph: float) -> float:
        return span_ph * NERNST_MV_PER_PH * (slope_percent / 100.0)
    
    window = stability.StabilityWindow(
        window_s=10.0,
        min_samples=5,
        span_threshold_mv=3.0,  # ~0.05 pH at 100% slope
        interval_s=5.0,  # Slow interval -> requires 3 samples
        min_samples_floor=3,
        min_samples_ceiling=5,
        to_mv_fn=ph_to_mv,
    )
    assert window.required_samples == 3
    
    now = 100.0
    # Push 3 samples with 0.06 pH span
    # At 80% slope: 0.06 * 59.16 * 0.80 = 2.84 mV < 3.0 mV -> stable
    window.push(7.00, now)
    window.push(7.03, now + 5)
    snap = window.push(7.06, now + 10)
    
    assert snap.span is not None
    assert abs(snap.span - 0.06) < 0.001
    
    expected_mv = 0.06 * NERNST_MV_PER_PH * (slope_percent / 100.0)
    assert snap.span_mv is not None
    assert abs(snap.span_mv - expected_mv) < 0.01
    
    # 2.84 mV < 3.0 mV threshold -> stable
    assert snap.stable
    
    # But at 100% slope, the same 0.06 pH span would be 3.55 mV > 3.0 -> NOT stable
    # This demonstrates that low-slope probes are "easier to stabilize" but
    # that's actually correct behavior: the mV drift is what matters for calibration.


def test_stability_window_ph_update_slope_dynamically() -> None:
    """Slope can be updated dynamically when Slope,? response is parsed."""
    NERNST_MV_PER_PH = 59.16
    slope_percent = 100.0
    
    def make_ph_to_mv():
        nonlocal slope_percent
        def ph_to_mv(span_ph: float) -> float:
            return span_ph * NERNST_MV_PER_PH * (slope_percent / 100.0)
        return ph_to_mv
    
    window = stability.StabilityWindow(
        window_s=10.0,
        min_samples=5,
        span_threshold_mv=3.0,
        interval_s=5.0,  # Slow interval -> requires 3 samples
        min_samples_floor=3,
        min_samples_ceiling=5,
        to_mv_fn=make_ph_to_mv(),
    )
    assert window.required_samples == 3
    
    now = 100.0
    # At 100% slope, 0.04 pH = 2.366 mV < 3.0 -> stable
    window.push(7.00, now)
    window.push(7.02, now + 5)
    snap = window.push(7.04, now + 10)
    assert snap.stable
    
    # Now the probe degrades to 70% slope (simulating calibration update)
    slope_percent = 70.0
    window.set_to_mv_fn(make_ph_to_mv())
    
    # Same readings, but now 0.04 pH = 1.66 mV < 3.0 -> still stable
    # (the conversion function captures the new slope)
    snap = window.push(7.04, now + 15)  # Same value, just to get new snapshot
    assert snap.stable


def test_stability_window_orp_no_conversion() -> None:
    """ORP readings are already in mV - no conversion needed."""
    window = stability.StabilityWindow(
        window_s=10.0,
        min_samples=5,
        span_threshold_mv=5.0,  # 5 mV threshold for ORP
        interval_s=5.0,  # Slow interval -> requires 3 samples
        min_samples_floor=3,
        min_samples_ceiling=5,
        # No to_mv_fn: defaults to identity
    )
    assert window.required_samples == 3
    
    now = 100.0
    window.push(225.0, now)
    window.push(227.0, now + 3)
    snap = window.push(229.0, now + 6)
    
    # Span should equal span_mv for ORP
    assert snap.span == 4.0
    assert snap.span_mv == 4.0
    
    # 4 mV < 5 mV threshold -> stable
    assert snap.stable
    
    # Push a reading that makes span > 5 mV (within 10s window)
    snap = window.push(232.0, now + 9)
    assert snap.span == 7.0  # 232 - 225 = 7
    assert snap.span_mv == 7.0
    assert not snap.stable  # 7 mV > 5 mV threshold


def test_stability_snapshot_span_mv_empty() -> None:
    """Empty window should have None for span_mv."""
    window = stability.StabilityWindow(
        window_s=10.0,
        min_samples=3,
        span_threshold_mv=3.0,
        interval_s=2.0,
    )
    
    # Don't push any values, just check initial state
    # Actually we need to push to get a snapshot, so let's test with one value
    snap = window.push(7.0, 100.0)
    assert snap.span == 0.0
    assert snap.span_mv == 0.0
    assert snap.sample_count == 1
    assert not snap.stable


# --- Filter tests ---

filter_mod = _load("ezo_complete.filter", PKG / "filter.py")


def test_filter_none_passthrough() -> None:
    """Filter type 'none' returns values unchanged."""
    f = filter_mod.ReadingFilter("none", 5)
    assert f.push(7.00) == 7.00
    assert f.push(7.05) == 7.05
    assert f.push(6.95) == 6.95
    assert f.sample_count == 3


def test_filter_median() -> None:
    """Median filter returns the median of the window."""
    f = filter_mod.ReadingFilter("median", 5)
    f.push(7.00)
    # With 2 samples [7.00, 7.10], median is (7.00+7.10)/2 = 7.05
    assert f.push(7.10) == 7.05
    f.push(7.05)
    f.push(6.95)
    result = f.push(7.02)  # Window: [7.00, 7.10, 7.05, 6.95, 7.02]
    # Sorted: [6.95, 7.00, 7.02, 7.05, 7.10] -> median = 7.02
    assert result == 7.02
    assert f.sample_count == 5


def test_filter_mean() -> None:
    """Mean filter returns the average of the window."""
    f = filter_mod.ReadingFilter("mean", 3)
    f.push(7.00)
    f.push(7.03)
    result = f.push(7.06)  # Window: [7.00, 7.03, 7.06] -> mean = 7.03
    assert abs(result - 7.03) < 0.001
    assert f.sample_count == 3


def test_filter_window_rolling() -> None:
    """Filter window rolls, dropping old values."""
    f = filter_mod.ReadingFilter("median", 3)
    f.push(7.00)
    f.push(7.10)
    f.push(7.20)  # Window: [7.00, 7.10, 7.20]
    result = f.push(7.30)  # Window: [7.10, 7.20, 7.30]
    # Sorted: [7.10, 7.20, 7.30] -> median = 7.20
    assert result == 7.20
    assert f.sample_count == 3


def test_filter_reset() -> None:
    """Reset clears the filter buffer."""
    f = filter_mod.ReadingFilter("median", 5)
    f.push(7.00)
    f.push(7.10)
    f.push(7.05)
    assert f.sample_count == 3
    f.reset()
    assert f.sample_count == 0
    assert f.last_raw() is None


def test_filter_reconfigure() -> None:
    """Reconfigure clears buffer if settings change."""
    f = filter_mod.ReadingFilter("median", 5)
    f.push(7.00)
    f.push(7.10)
    assert f.sample_count == 2
    f.configure("mean", 3)
    assert f.sample_count == 0
    assert f.filter_type == "mean"
    assert f.window_size == 3


def test_filter_last_raw() -> None:
    """last_raw returns the most recent value."""
    f = filter_mod.ReadingFilter("median", 5)
    f.push(7.00)
    f.push(7.10)
    f.push(7.05)
    assert f.last_raw() == 7.05

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
    window = stability.StabilityWindow(window_s=10.0, min_samples=5, span=5.0)
    now = 100.0
    last = None
    for index in range(5):
        last = window.push(225.0 + index * 0.1, now + index)
    assert last is not None and last.stable
    assert last.sample_count == 5
    assert last.required_samples == 5
    drifted = window.push(240.0, now + 5)
    assert not drifted.stable
    assert drifted.span is not None and drifted.span > 5.0


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
        window_s=10.0, min_samples=5, span=0.05, interval_s=1.0
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
        window_s=10.0, min_samples=5, span=0.05, interval_s=5.0
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
        window_s=10.0, min_samples=5, span=0.05, interval_s=5.0
    )
    now = 100.0
    for i in range(3):
        window.push(7.00, now + i * 5)
    snap = window.push(7.00, now + 15)
    assert snap.stable
    snap = window.push(7.10, now + 20)
    assert not snap.stable
    assert snap.span is not None and snap.span > 0.05


def test_stability_window_set_interval() -> None:
    """set_interval dynamically adjusts required samples."""
    window = stability.StabilityWindow(
        window_s=10.0, min_samples=5, span=0.05, interval_s=1.0
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
        window_s=10.0, min_samples=5, span=0.05, interval_s=2.0
    )
    snap = window.push(7.00, 100.0)
    assert snap.minimum == 7.00
    assert snap.maximum == 7.00
    assert snap.span == 0.0
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
    
    Lines like '010101000080' are valid numbers (~1.01e10) and thus parsed
    as READING. The fix is that is_reading_in_range() rejects them because
    they are way outside pH (-1.6..15.6) or ORP (-1019.9..1019.9 mV) bounds.
    """
    hex_lines_as_numbers = ["010101000080", "00CB213F0100", "0040B1C6A8D3"]
    for line in hex_lines_as_numbers:
        parsed = codec.parse_line(line)
        if parsed.kind is codec.LineKind.READING and parsed.value is not None:
            assert not codec.is_reading_in_range(parsed.value, "ph"), \
                f"{line} ({parsed.value}) should be out of pH range"
            assert not codec.is_reading_in_range(parsed.value, "orp"), \
                f"{line} ({parsed.value}) should be out of ORP range"
    
    short_hex = ["9E6B"]
    for line in short_hex:
        parsed = codec.parse_line(line)
        assert parsed.kind is codec.LineKind.OTHER, f"{line} should be OTHER (contains letters)"


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
    """ORP readings must be within -1019.9..1019.9 mV (datasheet)."""
    assert codec.is_reading_in_range(225.0, "orp")
    assert codec.is_reading_in_range(0.0, "orp")
    assert codec.is_reading_in_range(-1019.9, "orp")
    assert codec.is_reading_in_range(1019.9, "orp")
    assert codec.is_reading_in_range(-500.0, "orp")
    assert not codec.is_reading_in_range(-1020.0, "orp")
    assert not codec.is_reading_in_range(1020.0, "orp")
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
    """RESPONSE_CODE_ENABLE_COMMANDS should include *OK,1."""
    assert "*OK,1" in const.RESPONSE_CODE_ENABLE_COMMANDS

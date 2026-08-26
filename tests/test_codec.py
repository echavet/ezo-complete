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
base = _load("ezo_complete.profiles.base", PKG / "profiles" / "base.py")
orp = _load("ezo_complete.profiles.orp", PKG / "profiles" / "orp.py")
ph = _load("ezo_complete.profiles.ph", PKG / "profiles" / "ph.py")


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


def test_usb_name() -> None:
    assert codec.is_usb_product_name("FT230X Basic UART")
    assert codec.resolve_display_name(
        ezo_name=None, configured="FT230X Basic UART", fallback="EZO pH"
    ) == "EZO pH"

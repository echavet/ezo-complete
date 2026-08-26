"""Probe profiles (Strategy): pH vs ORP."""

from __future__ import annotations

from .base import CalSlot, ProbeProfile
from .orp import OrpProfile
from .ph import PhProfile


def profile_for(kind: str) -> ProbeProfile:
    token = (kind or "").strip().lower()
    if token == "ph":
        return PhProfile()
    if token == "orp":
        return OrpProfile()
    raise ValueError(f"Unsupported EZO kind: {kind}")

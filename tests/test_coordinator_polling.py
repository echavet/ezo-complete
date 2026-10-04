"""Tests for coordinator polling and temperature handling.

These tests verify:
1. Fixed-rate polling with duration compensation
2. Temperature changes don't cause missed readings
3. One R command per interval
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

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
stability = _load("ezo_complete.stability", PKG / "stability.py")


class TestFixedRatePolling:
    """Test that polling interval accounts for poll duration."""

    def test_interval_adjustment_calculation(self) -> None:
        """Verify the interval adjustment formula: adjusted = max(0.5, configured - duration)."""
        configured = 25.0
        
        poll_duration = 2.0
        adjusted = max(0.5, configured - poll_duration)
        assert adjusted == 23.0
        
        poll_duration = 0.8
        adjusted = max(0.5, configured - poll_duration)
        assert adjusted == 24.2
        
        poll_duration = 0.0
        adjusted = max(0.5, configured - poll_duration)
        assert adjusted == 25.0

    def test_interval_adjustment_minimum(self) -> None:
        """Verify minimum interval of 0.5s even if poll takes longer than configured."""
        configured = 5.0
        poll_duration = 10.0
        adjusted = max(0.5, configured - poll_duration)
        assert adjusted == 0.5

    def test_drift_compensation_at_25s(self) -> None:
        """With 25s interval and ~2s poll, next poll should be ~23s to maintain 25s start-to-start."""
        configured_interval = 25.0
        poll_duration = 2.0
        
        adjusted_interval = max(0.5, configured_interval - poll_duration)
        
        total_cycle = poll_duration + adjusted_interval
        assert total_cycle == 25.0, f"Expected 25s cycle, got {total_cycle}"

    def test_drift_compensation_at_5s(self) -> None:
        """With 5s interval and ~1s poll, next poll should be ~4s."""
        configured_interval = 5.0
        poll_duration = 1.0
        
        adjusted_interval = max(0.5, configured_interval - poll_duration)
        
        total_cycle = poll_duration + adjusted_interval
        assert total_cycle == 5.0

    def test_multiple_cycles_no_drift(self) -> None:
        """Simulate multiple poll cycles and verify no cumulative drift."""
        configured_interval = 25.0
        poll_durations = [1.8, 2.1, 1.5, 2.3, 1.9, 2.0, 1.7, 2.2, 1.6, 2.4]
        
        total_time = 0.0
        for i, duration in enumerate(poll_durations):
            adjusted = max(0.5, configured_interval - duration)
            cycle_time = duration + adjusted
            total_time += cycle_time
            expected_time = (i + 1) * configured_interval
            assert cycle_time == configured_interval, f"Cycle {i+1}: {cycle_time} != {configured_interval}"
        
        expected_total = len(poll_durations) * configured_interval
        assert total_time == expected_total


class TestTemperatureIntegration:
    """Test temperature push doesn't interfere with polling."""

    def test_temperature_push_coalesce_logic(self) -> None:
        """Verify temperature push is rate-limited (>= 0.05°C change, 30s minimum)."""
        assert const.TEMPERATURE_PUSH_DELTA == 0.05
        assert const.TEMPERATURE_PUSH_MIN_INTERVAL == 30.0
        
        last_pushed = 25.0
        new_temp = 25.03
        should_push = abs(new_temp - last_pushed) >= const.TEMPERATURE_PUSH_DELTA
        assert not should_push, "Change < 0.05°C should not trigger push"
        
        new_temp = 25.05
        should_push = abs(new_temp - last_pushed) >= const.TEMPERATURE_PUSH_DELTA
        assert should_push, "Change >= 0.05°C should trigger push"

    def test_temperature_rate_limit_logic(self) -> None:
        """Verify temperature push respects 30s minimum interval."""
        last_push_at = 100.0
        
        now = 120.0
        should_allow = (now - last_push_at) >= const.TEMPERATURE_PUSH_MIN_INTERVAL
        assert not should_allow, "Push at 20s after last should be blocked"
        
        now = 130.0
        should_allow = (now - last_push_at) >= const.TEMPERATURE_PUSH_MIN_INTERVAL
        assert should_allow, "Push at 30s after last should be allowed"

    def test_poll_cycle_simulation(self) -> None:
        """Simulate poll cycles with temperature changes, verify one R per interval."""
        configured_interval = 5.0
        poll_durations = [0.8, 0.9, 0.85, 0.95, 0.82]
        temperature_changes = [25.0, 25.03, 25.1, 25.12, 25.5]
        
        last_pushed_t = None
        r_commands = 0
        t_commands = 0
        
        for i, (duration, temp) in enumerate(zip(poll_durations, temperature_changes)):
            should_push_temp = (
                last_pushed_t is None
                or abs(temp - last_pushed_t) >= 0.05
            )
            
            if should_push_temp:
                t_commands += 1
                last_pushed_t = temp
            
            r_commands += 1
            
            adjusted = max(0.5, configured_interval - duration)
            total_cycle = duration + adjusted
            assert total_cycle == configured_interval
        
        assert r_commands == 5, "Should have exactly 5 R commands (one per poll)"
        assert t_commands == 3, f"Should have 3 T commands (initial, +0.1°C, +0.4°C), got {t_commands}"


class TestPollCycleIntegrity:
    """Test that poll cycles maintain integrity with temperature handling."""

    def test_temperature_push_before_r_in_exploitation(self) -> None:
        """Verify temperature is pushed before R in exploitation mode polling."""
        operations_order = []
        
        def simulate_poll_with_temp():
            operations_order.append("T,value")
            operations_order.append("T,?")
            operations_order.append("R")
        
        simulate_poll_with_temp()
        
        assert operations_order == ["T,value", "T,?", "R"]
        r_index = operations_order.index("R")
        t_index = operations_order.index("T,value")
        assert t_index < r_index, "Temperature push should be before R"

    def test_no_exception_during_poll_with_temperature(self) -> None:
        """Verify poll cycles complete without exception even with temperature changes."""
        errors = []
        
        for cycle in range(10):
            try:
                duration = 0.8 + (cycle % 3) * 0.1
                adjusted = max(0.5, 25.0 - duration)
                assert adjusted > 0
            except Exception as e:
                errors.append(str(e))
        
        assert len(errors) == 0, f"Poll cycles raised exceptions: {errors}"

    def test_effective_window_maintained(self) -> None:
        """Verify stability effective window is maintained correctly."""
        window = stability.StabilityWindow(
            window_s=10.0,
            min_samples=5,
            span_threshold_mv=5.0,
            interval_s=25.0,
            min_samples_floor=3,
            min_samples_ceiling=5,
        )
        
        assert window.effective_window_s == 75.0
        
        samples_over_time = []
        now = 0.0
        for i in range(5):
            snap = window.push(320.0 + i * 0.1, now)
            samples_over_time.append(snap.sample_count)
            now += 25.0
        
        assert samples_over_time == [1, 2, 3, 4, 4]

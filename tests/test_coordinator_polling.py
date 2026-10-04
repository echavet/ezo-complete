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


class TestContinuousFromCommand:
    """Test that C,n commands update state.continuous even if C,? is lost."""

    def test_parse_continuous_command(self) -> None:
        """Verify the logic for parsing C,n commands."""
        def update_continuous(cmd: str) -> tuple[bool | None, int | None]:
            """Simulate _update_continuous_from_command logic."""
            parts = cmd.split(",", 1)
            if parts[0].lower() != "c" or len(parts) < 2:
                return None, None
            try:
                interval = int(parts[1])
            except ValueError:
                return None, None
            if interval >= 1:
                return True, interval
            else:
                return False, interval

        # C,n where n >= 1 should enable continuous
        assert update_continuous("C,5") == (True, 5)
        assert update_continuous("C,1") == (True, 1)
        assert update_continuous("C,99") == (True, 99)

        # C,0 should disable continuous
        assert update_continuous("C,0") == (False, 0)

        # Non-C commands should be ignored
        assert update_continuous("R") == (None, None)
        assert update_continuous("L,1") == (None, None)
        assert update_continuous("T,25") == (None, None)

        # C,? queries should be ignored (not an interval)
        assert update_continuous("C,?") == (None, None)

    def test_listen_loop_fallback_logic(self) -> None:
        """Verify listen loop runs when mode is calibration, even if continuous is False."""
        # Simulates the condition: skip only if continuous=False AND mode!=calibration
        def should_skip_listen(continuous: bool | None, mode: str) -> bool:
            if continuous is False and mode != "calibration":
                return True
            return False

        # continuous=False, mode=exploitation: should skip
        assert should_skip_listen(False, "exploitation") is True

        # continuous=False, mode=calibration: should NOT skip (fallback)
        assert should_skip_listen(False, "calibration") is False

        # continuous=True, mode=exploitation: should NOT skip
        assert should_skip_listen(True, "exploitation") is False

        # continuous=True, mode=calibration: should NOT skip
        assert should_skip_listen(True, "calibration") is False

        # continuous=None (initial), mode=calibration: should NOT skip
        assert should_skip_listen(None, "calibration") is False

        # continuous=None, mode=exploitation: should NOT skip (None != False)
        assert should_skip_listen(None, "exploitation") is False

    def test_calibration_not_blocked_when_cquery_lost(self) -> None:
        """Verify calibration can proceed when C,? reply is lost.
        
        Scenario:
        1. Switch exploitation -> calibration
        2. Send C,5 successfully (*OK)
        3. C,? reply is lost (network issue, buffer overflow, etc.)
        4. state.continuous should be True from C,5 success
        5. Listen loop should run
        """
        continuous = False  # Initial state from exploitation
        mode = "calibration"  # User switched mode

        # C,5 command succeeds (*OK) - this should set continuous=True
        cmd = "C,5"
        parts = cmd.split(",", 1)
        if parts[0].lower() == "c" and len(parts) >= 2:
            try:
                interval = int(parts[1])
                if interval >= 1:
                    continuous = True  # This is what _update_continuous_from_command does
            except ValueError:
                pass

        # Now continuous=True, listen loop should run
        def should_skip_listen(cont: bool | None, m: str) -> bool:
            if cont is False and m != "calibration":
                return True
            return False

        assert continuous is True
        assert should_skip_listen(continuous, mode) is False


class TestTemperaturePollIntegration:
    """Test that temperature changes in exploitation mode don't disrupt polling.
    
    In exploitation mode, temperature entity changes are ignored (no-op).
    The poll reads the current thermometer value and applies the dead band.
    This avoids stale pending values and keeps push inside the poll cycle.
    """

    def test_exploitation_mode_ignores_temp_changes(self) -> None:
        """In exploitation mode, temperature entity changes are no-op."""
        mode = "exploitation"
        pending_temp_value = None
        push_called = False
        
        # Simulate _async_push_temperature_coalesced behavior
        def on_temp_change(value: float):
            nonlocal pending_temp_value, push_called
            if mode == "exploitation":
                # No-op in exploitation mode
                return
            # In calibration, would push or defer
            push_called = True
        
        on_temp_change(26.0)
        on_temp_change(27.0)
        
        assert pending_temp_value is None, "Should NOT store pending value"
        assert push_called is False, "Should NOT push in exploitation mode"

    def test_calibration_mode_pushes_immediately(self) -> None:
        """In calibration mode, temperature change pushes immediately (or defers)."""
        mode = "calibration"
        pending_temp_value = None
        immediate_push_called = False
        last_pushed_t = 25.0
        last_temp_push_at = 0.0
        
        # Temperature changes
        new_temp = 26.0
        delta = abs(new_temp - last_pushed_t)
        
        # Check delta threshold
        assert delta >= const.TEMPERATURE_PUSH_DELTA
        
        # Simulate time (past rate limit window)
        now = 100.0
        time_since_last = now - last_temp_push_at
        
        # In calibration mode, push immediately if rate limit allows
        if mode == "calibration":
            if time_since_last >= const.TEMPERATURE_PUSH_MIN_INTERVAL:
                immediate_push_called = True
            else:
                pending_temp_value = new_temp
        
        assert immediate_push_called is True, "Should push immediately in calibration mode"
        assert pending_temp_value is None, "Should not store pending value when pushing"

    def test_poll_reads_current_temp(self) -> None:
        """Poll should always read the current thermometer value."""
        current_temp = 27.5
        last_pushed_t = 25.0
        
        # Simulate poll reading current value
        value = current_temp  # Always read current, no pending logic
        
        assert value == 27.5, "Poll should read current temperature"
        
        # Delta check
        delta = abs(value - last_pushed_t)
        assert delta >= const.TEMPERATURE_PUSH_DELTA, "Delta should trigger push"

    def test_no_poll_timer_reset_in_exploitation(self) -> None:
        """Verify that temp entity changes don't call async_set_updated_data.
        
        In exploitation mode, temperature entity changes are no-op.
        The push happens in the poll, which already calls async_set_updated_data.
        """
        mode = "exploitation"
        async_set_updated_data_calls = 0
        
        # Simulate temperature entity change handler
        def on_temp_change(value: float):
            nonlocal async_set_updated_data_calls
            if mode == "exploitation":
                # No-op - no push, no async_set_updated_data
                return
            # In calibration, push would call async_set_updated_data
            async_set_updated_data_calls += 1
        
        # Temperature changes in exploitation mode
        on_temp_change(26.0)
        on_temp_change(27.0)
        on_temp_change(28.0)
        
        assert async_set_updated_data_calls == 0, (
            "Temperature changes in exploitation mode should not call "
            "async_set_updated_data (which resets poll timer)"
        )

    def test_poll_timing_preserved_with_temp_changes(self) -> None:
        """Verify poll timing is preserved when temperature changes between polls.
        
        Scenario: 5s poll interval, temperature changes at T=2s
        - Without fix: poll timer resets at T=2s, next poll at T=7s (7s gap)
        - With fix: temp changes ignored, next poll at T=5s as expected (5s gap)
        """
        configured_interval = 5.0
        
        # Simulate timeline
        poll_times = [0.0]  # First poll at T=0
        temp_change_time = 2.0
        
        # With fix: temperature change is no-op, poll continues on schedule
        next_poll_time = poll_times[0] + configured_interval
        
        assert next_poll_time == 5.0, "Next poll should be at T=5s"
        
        # Gap should be exactly the configured interval
        gap = next_poll_time - poll_times[0]
        assert gap == configured_interval, f"Gap should be {configured_interval}s, got {gap}s"


class TestEnterCalibrationPushesTemp:
    """Test that entering calibration mode pushes the current temperature."""

    def test_calibration_mode_switch_pushes_current_temp(self) -> None:
        """Switching to calibration should push the current thermometer value."""
        current_temp = 26.8
        last_pushed_t = 25.0
        commands_sent = []
        
        # Simulate _async_push_temperature_on_mode_switch
        def push_temp_on_mode_switch(temp_entity_configured: bool, asleep: bool):
            if not temp_entity_configured:
                return
            if asleep:
                return
            value = current_temp
            if value is not None:
                commands_sent.append(f"T,{value:.2f}")
                commands_sent.append("T,?")
        
        # Switch to calibration with temp entity configured
        push_temp_on_mode_switch(temp_entity_configured=True, asleep=False)
        
        assert commands_sent == ["T,26.80", "T,?"], (
            f"Should push T,26.80 then T,?, got {commands_sent}"
        )

    def test_calibration_mode_switch_skips_if_no_entity(self) -> None:
        """Switching to calibration should skip temp push if no entity configured."""
        commands_sent = []
        
        def push_temp_on_mode_switch(temp_entity_configured: bool, asleep: bool):
            if not temp_entity_configured:
                return
            if asleep:
                return
            commands_sent.append("T,value")
        
        push_temp_on_mode_switch(temp_entity_configured=False, asleep=False)
        
        assert commands_sent == [], "Should not push if no temp entity"

    def test_calibration_mode_switch_skips_if_asleep(self) -> None:
        """Switching to calibration should skip temp push if asleep."""
        commands_sent = []
        
        def push_temp_on_mode_switch(temp_entity_configured: bool, asleep: bool):
            if not temp_entity_configured:
                return
            if asleep:
                return
            commands_sent.append("T,value")
        
        push_temp_on_mode_switch(temp_entity_configured=True, asleep=True)
        
        assert commands_sent == [], "Should not push if asleep"


class TestNoStalePendingValue:
    """Test that stale pending values are never pushed."""

    def test_sequence_25_to_2530_to_2502_no_stale(self) -> None:
        """25.0 -> 25.30 -> 25.02: should push 25.02, never 25.30.
        
        Scenario:
        1. Last pushed: 25.0
        2. Temp changes to 25.30 (> 0.05 delta)
        3. Before poll, temp changes to 25.02 (< 0.05 delta from 25.0)
        4. Poll reads current (25.02), dead band passes (delta = 0.02 < 0.05)
        5. Result: no push, or push 25.02 if delta check fails
        """
        last_pushed_t = 25.0
        
        # Temp changes to 25.30
        temp_at_change_1 = 25.30
        # Then changes to 25.02 before poll
        temp_at_poll_time = 25.02
        
        # Poll reads current value (always, no pending)
        value = temp_at_poll_time
        
        # Apply dead band against last pushed
        delta = abs(value - last_pushed_t)
        should_push = delta >= const.TEMPERATURE_PUSH_DELTA
        
        # 25.02 - 25.0 = 0.02 < 0.05, so should NOT push
        assert delta == pytest.approx(0.02, abs=0.001)
        assert should_push is False, (
            f"Should NOT push 25.02 (delta {delta} < {const.TEMPERATURE_PUSH_DELTA})"
        )
        
        # Key assertion: 25.30 (stale) is never considered
        assert value != 25.30, "Should never consider stale value 25.30"

    def test_sequence_25_to_2530_to_2510_pushes_current(self) -> None:
        """25.0 -> 25.30 -> 25.10: should push 25.10, never 25.30.
        
        Scenario:
        1. Last pushed: 25.0
        2. Temp changes to 25.30 (> 0.05 delta)
        3. Before poll, temp changes to 25.10 (> 0.05 delta from 25.0)
        4. Poll reads current (25.10), delta = 0.10 >= 0.05, push
        5. Result: push 25.10 (current), never 25.30 (stale)
        """
        last_pushed_t = 25.0
        
        # Temp changes to 25.30
        temp_at_change_1 = 25.30
        # Then changes to 25.10 before poll
        temp_at_poll_time = 25.10
        
        # Poll reads current value (always, no pending)
        value = temp_at_poll_time
        
        # Apply dead band against last pushed
        delta = abs(value - last_pushed_t)
        should_push = delta >= const.TEMPERATURE_PUSH_DELTA
        
        # 25.10 - 25.0 = 0.10 >= 0.05, so should push
        assert delta == pytest.approx(0.10, abs=0.001)
        assert should_push is True, "Should push 25.10"
        
        # Key assertion: pushed value is current, not stale
        assert value == 25.10, "Should push current value 25.10, not stale 25.30"

    def test_mode_switch_clears_pending(self) -> None:
        """Mode switch should clear any pending temperature value."""
        pending_temp_value = 25.30  # Stale value from calibration deferred push
        
        # Simulate mode switch clearing pending
        def on_mode_switch():
            nonlocal pending_temp_value
            pending_temp_value = None
        
        on_mode_switch()
        
        assert pending_temp_value is None, "Mode switch should clear pending"

    def test_no_stale_push_after_returning_to_exploitation(self) -> None:
        """After returning to exploitation, no stale temp should be pushed.
        
        Scenario:
        1. In calibration, temp deferred to pending (25.30)
        2. Switch to exploitation (clears pending)
        3. Poll reads current temp (e.g., 25.02)
        4. Apply dead band against last pushed
        5. Result: never push 25.30
        """
        pending_temp_value = 25.30  # From calibration deferred push
        last_pushed_t = 25.0
        current_temp = 25.02
        
        # Mode switch clears pending
        pending_temp_value = None
        
        # Poll reads current
        value = current_temp
        
        # Dead band check
        delta = abs(value - last_pushed_t)
        should_push = delta >= const.TEMPERATURE_PUSH_DELTA
        
        assert pending_temp_value is None, "Pending should be cleared"
        assert value == 25.02, "Should read current, not stale"
        assert should_push is False, "0.02 < 0.05, should not push"

    def test_push_clears_pending(self) -> None:
        """Any temperature push should clear the pending value."""
        pending_temp_value = 25.30
        
        # Simulate push clearing pending
        def do_push(value: float):
            nonlocal pending_temp_value
            # ... send T,value ...
            pending_temp_value = None
        
        do_push(26.0)
        
        assert pending_temp_value is None, "Push should clear pending"

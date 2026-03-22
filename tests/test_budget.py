"""Integration tests for the core budget logic.

These exercise consume/recover/set/extra with real AppState objects and
real sidecar files in a temp directory, but don't need Windows APIs or
a running monitor process.
"""

import os
import sys
import tempfile
import shutil

import pytest

# Redirect state files to a temp directory before importing anything that
# reads config.STATE_DIR at import time.
_tmp = tempfile.mkdtemp(prefix="hotturkey_test_")

import hotturkey.config as config

_orig_state_dir = config.STATE_DIR
_orig_state_file = config.STATE_FILE

config.STATE_DIR = _tmp
config.STATE_FILE = os.path.join(_tmp, "state.json")

from hotturkey.state import (
    AppState,
    save_state,
    load_state,
    save_extra_minutes_pending,
    load_extra_minutes_pending,
    save_set_minutes,
    load_set_minutes,
    EXTRA_FILE,
    SET_FILE,
)

# Patch the file paths that were computed at import time from the original STATE_DIR
import hotturkey.state as state_mod

state_mod.EXTRA_FILE = os.path.join(_tmp, "extra.json")
state_mod.SET_FILE = os.path.join(_tmp, "set.json")
state_mod.RELOAD_STATE_FLAG = os.path.join(_tmp, ".reload_state")

from hotturkey.monitor import (
    clamp_elapsed_for_budget,
    consume_budget,
    recover_budget,
    apply_pending_set_time,
    apply_pending_extra_time,
)
from hotturkey.utils import format_duration


@pytest.fixture(autouse=True)
def clean_state_dir():
    """Wipe temp state files between tests."""
    for f in os.listdir(_tmp):
        path = os.path.join(_tmp, f)
        if os.path.isfile(path):
            os.remove(path)
    yield


def _fresh_state(**overrides) -> AppState:
    state = AppState()
    for k, v in overrides.items():
        setattr(state, k, v)
    return state


# ---------- format_duration ----------


def test_clamp_elapsed_for_budget_normal_tick_unchanged():
    pi = float(config.POLL_INTERVAL)
    assert clamp_elapsed_for_budget(pi) == pi
    assert clamp_elapsed_for_budget(60.0) == 60.0


def test_clamp_elapsed_for_budget_clamps_long_gap_to_one_poll():
    """Sleep/suspend gaps must not become one huge idle recovery tick."""
    pi = float(config.POLL_INTERVAL)
    assert clamp_elapsed_for_budget(3600.0) == pi


def test_format_duration():
    assert format_duration(0) == "0:00"
    assert format_duration(59) == "0:59"
    assert format_duration(60) == "1:00"
    assert format_duration(924) == "15:24"
    assert format_duration(3600) == "1:00:00"
    assert format_duration(3661) == "1:01:01"
    assert format_duration(-10) == "0:00"


# ---------- consume_budget ----------


def test_consume_subtracts_from_budget():
    state = _fresh_state(remaining_budget_seconds=600.0, overtime_seconds=0.0)
    consume_budget(state, 10.0)
    assert state.remaining_budget_seconds == 590.0
    assert state.overtime_seconds == 0.0


def test_consume_past_zero_creates_overtime():
    state = _fresh_state(remaining_budget_seconds=5.0, overtime_seconds=0.0)
    consume_budget(state, 15.0)
    assert state.remaining_budget_seconds == 0.0
    assert state.overtime_seconds == 10.0


def test_consume_when_already_overtime():
    state = _fresh_state(remaining_budget_seconds=0.0, overtime_seconds=20.0)
    consume_budget(state, 5.0)
    assert state.remaining_budget_seconds == 0.0
    assert state.overtime_seconds == 25.0


# ---------- recover_budget ----------


def test_recover_pays_overtime_first():
    state = _fresh_state(remaining_budget_seconds=0.0, overtime_seconds=100.0)
    recover_budget(state, 20.0)
    assert state.overtime_seconds == pytest.approx(
        100.0 - 20.0 * config.BUDGET_RECOVERY_PER_SECOND_RATIO
    )
    assert state.remaining_budget_seconds == 0.0


def test_recover_fills_budget_after_overtime_cleared():
    state = _fresh_state(remaining_budget_seconds=0.0, overtime_seconds=5.0)
    recover_budget(state, 200.0)
    recovered = 200.0 * config.BUDGET_RECOVERY_PER_SECOND_RATIO
    leftover = recovered - 5.0
    assert state.overtime_seconds == 0.0
    assert state.remaining_budget_seconds == pytest.approx(
        min(leftover, config.MAX_PLAY_BUDGET)
    )


def test_recover_caps_at_max_budget():
    state = _fresh_state(
        remaining_budget_seconds=float(config.MAX_PLAY_BUDGET) - 1.0,
        overtime_seconds=0.0,
    )
    recover_budget(state, 99999.0)
    assert state.remaining_budget_seconds == float(config.MAX_PLAY_BUDGET)


# ---------- apply_pending_set_time ----------


def test_set_positive_sets_budget_and_clears_overtime():
    state = _fresh_state(remaining_budget_seconds=100.0, overtime_seconds=50.0)
    save_set_minutes(30.0)
    apply_pending_set_time(state)
    assert state.remaining_budget_seconds == 1800.0
    assert state.overtime_seconds == 0.0
    assert load_set_minutes() == 0.0


def test_set_negative_sets_overtime_and_zeros_budget():
    state = _fresh_state(remaining_budget_seconds=500.0, overtime_seconds=0.0)
    save_set_minutes(-10.0)
    apply_pending_set_time(state)
    assert state.remaining_budget_seconds == 0.0
    assert state.overtime_seconds == 600.0
    assert load_set_minutes() == 0.0


def test_set_zero_is_noop():
    state = _fresh_state(remaining_budget_seconds=500.0, overtime_seconds=10.0)
    save_set_minutes(0.0)
    apply_pending_set_time(state)
    assert state.remaining_budget_seconds == 500.0
    assert state.overtime_seconds == 10.0


# ---------- apply_pending_extra_time ----------


def test_extra_positive_adds_to_budget():
    state = _fresh_state(remaining_budget_seconds=300.0, overtime_seconds=0.0)
    save_extra_minutes_pending(5.0)
    apply_pending_extra_time(state)
    assert state.remaining_budget_seconds == 600.0
    assert load_extra_minutes_pending() == 0.0


def test_extra_positive_clears_overtime_first():
    state = _fresh_state(remaining_budget_seconds=0.0, overtime_seconds=180.0)
    save_extra_minutes_pending(5.0)
    apply_pending_extra_time(state)
    assert state.overtime_seconds == 0.0
    assert state.remaining_budget_seconds == 120.0


def test_extra_negative_deducts_from_budget():
    state = _fresh_state(remaining_budget_seconds=600.0, overtime_seconds=0.0)
    save_extra_minutes_pending(-5.0)
    apply_pending_extra_time(state)
    assert state.remaining_budget_seconds == 300.0
    assert state.overtime_seconds == 0.0


def test_extra_negative_overdraw_becomes_overtime():
    state = _fresh_state(remaining_budget_seconds=60.0, overtime_seconds=0.0)
    save_extra_minutes_pending(-5.0)
    apply_pending_extra_time(state)
    assert state.remaining_budget_seconds == 0.0
    assert state.overtime_seconds == 240.0


# ---------- state round-trip ----------


def test_state_save_load_round_trip():
    state = _fresh_state(
        remaining_budget_seconds=1234.5,
        overtime_seconds=67.8,
        overtime_escalation_level=2,
    )
    save_state(state)
    loaded = load_state()
    assert loaded.remaining_budget_seconds == pytest.approx(1234.5)
    assert loaded.overtime_seconds == pytest.approx(67.8)
    assert loaded.overtime_escalation_level == 2

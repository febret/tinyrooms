"""Unit tests for tinyrooms.gameplay module."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest

from tinyrooms import gameplay as gp


# ---------------------------------------------------------------------------
# compute_level
# ---------------------------------------------------------------------------

class TestComputeLevel:
    def test_zero_kudos_is_level_0(self):
        info = gp.compute_level(0)
        assert info["level"] == 0
        assert info["title"] == "Guest"
        assert info["next_threshold"] == 10

    def test_exact_boundary_promotes(self):
        """Exactly meeting a threshold advances to that level."""
        info = gp.compute_level(10)
        assert info["level"] == 1
        assert info["title"] == "Novice"
        assert info["next_threshold"] == 20

    def test_just_below_boundary_stays(self):
        info = gp.compute_level(9)
        assert info["level"] == 0

    def test_max_level(self):
        info = gp.compute_level(100)
        assert info["level"] == 10
        assert info["title"] == "Grandmaster"
        assert info["next_threshold"] is None

    def test_above_max_stays_at_max(self):
        info = gp.compute_level(999)
        assert info["level"] == 10

    @pytest.mark.parametrize("kudos,expected_level", [
        (0, 0),
        (10, 1),
        (20, 2),
        (30, 3),
        (40, 4),
        (50, 5),
        (60, 6),
        (70, 7),
        (80, 8),
        (90, 9),
        (100, 10),
    ])
    def test_all_level_boundaries(self, kudos, expected_level):
        assert gp.compute_level(kudos)["level"] == expected_level


# ---------------------------------------------------------------------------
# max_juice
# ---------------------------------------------------------------------------

class TestMaxJuice:
    def test_level_0_base(self):
        assert gp.max_juice(0) == pytest.approx(gp.BASE_MAX_JUICE)

    def test_scales_with_level(self):
        for lvl in range(11):
            expected = gp.BASE_MAX_JUICE + lvl * gp.JUICE_PER_LEVEL
            assert gp.max_juice(lvl) == pytest.approx(expected)

    def test_higher_level_has_more_juice(self):
        assert gp.max_juice(5) > gp.max_juice(0)
        assert gp.max_juice(10) > gp.max_juice(5)


# ---------------------------------------------------------------------------
# base_juice_rate / juice_rate_for_user
# ---------------------------------------------------------------------------

class TestJuiceRate:
    def test_base_rate_level_0(self):
        assert gp.base_juice_rate(0) == pytest.approx(gp.BASE_JUICE_RATE)

    def test_base_rate_scales(self):
        for lvl in range(11):
            expected = gp.BASE_JUICE_RATE + lvl * gp.JUICE_RATE_PER_LEVEL
            assert gp.base_juice_rate(lvl) == pytest.approx(expected)

    def test_juice_rate_for_user_no_traits(self):
        user_obj = MagicMock()
        user_obj.level = 0
        user_obj.traits = []
        rate = gp.juice_rate_for_user(user_obj)
        assert rate == pytest.approx(gp.BASE_JUICE_RATE)

    def test_juice_rate_for_user_with_modifier(self):
        """A user with an energetic trait should have a higher rate."""
        user_obj = MagicMock()
        user_obj.level = 0
        user_obj.traits = ["energetic"]
        rate = gp.juice_rate_for_user(user_obj)
        # energetic multiplies rate by 1.5
        assert rate > gp.BASE_JUICE_RATE


# ---------------------------------------------------------------------------
# compute_juice_recovery
# ---------------------------------------------------------------------------

class TestComputeJuiceRecovery:
    def test_no_elapsed_time(self):
        now_iso = datetime.now(timezone.utc).isoformat()
        assert gp.compute_juice_recovery(now_iso, 10.0) == pytest.approx(0.0, abs=0.1)

    def test_one_minute_elapsed(self):
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        recovered = gp.compute_juice_recovery(past, 10.0)
        # Should be approximately 10 juice/min * 1 min = 10
        assert recovered == pytest.approx(10.0, abs=0.5)

    def test_half_minute_elapsed(self):
        past = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
        recovered = gp.compute_juice_recovery(past, 20.0)
        # 20 juice/min * 0.5 min = 10
        assert recovered == pytest.approx(10.0, abs=1.0)

    def test_invalid_timestamp_returns_zero(self):
        assert gp.compute_juice_recovery("not-a-date", 10.0) == pytest.approx(0.0)
        assert gp.compute_juice_recovery("", 10.0) == pytest.approx(0.0)

    def test_future_timestamp_returns_zero(self):
        future = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        assert gp.compute_juice_recovery(future, 10.0) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# juice_cost_per_message
# ---------------------------------------------------------------------------

class TestJuiceCostPerMessage:
    def test_cost_is_positive(self):
        assert gp.juice_cost_per_message() > 0

    def test_cost_is_float(self):
        assert isinstance(gp.juice_cost_per_message(), float)


# ---------------------------------------------------------------------------
# daily_bops
# ---------------------------------------------------------------------------

class TestDailyBops:
    def test_level_0(self):
        assert gp.daily_bops(0) == gp.BASE_DAILY_BOPS

    def test_scales_with_level(self):
        for lvl in range(11):
            expected = gp.BASE_DAILY_BOPS + lvl * gp.BOPS_PER_LEVEL
            assert gp.daily_bops(lvl) == expected

    def test_higher_level_earns_more(self):
        assert gp.daily_bops(5) > gp.daily_bops(0)
        assert gp.daily_bops(10) > gp.daily_bops(5)


# ---------------------------------------------------------------------------
# JUICE_PACKS
# ---------------------------------------------------------------------------

class TestJuicePacks:
    def test_packs_exist(self):
        assert "small" in gp.JUICE_PACKS
        assert "medium" in gp.JUICE_PACKS
        assert "large" in gp.JUICE_PACKS

    def test_packs_have_required_keys(self):
        for pack_name, pack in gp.JUICE_PACKS.items():
            assert "bops_cost" in pack, f"{pack_name} missing bops_cost"
            assert "juice_amount" in pack, f"{pack_name} missing juice_amount"

    def test_larger_packs_cost_more(self):
        assert gp.JUICE_PACKS["small"]["bops_cost"] < gp.JUICE_PACKS["medium"]["bops_cost"]
        assert gp.JUICE_PACKS["medium"]["bops_cost"] < gp.JUICE_PACKS["large"]["bops_cost"]

    def test_larger_packs_give_more_juice(self):
        assert gp.JUICE_PACKS["small"]["juice_amount"] < gp.JUICE_PACKS["medium"]["juice_amount"]
        assert gp.JUICE_PACKS["medium"]["juice_amount"] < gp.JUICE_PACKS["large"]["juice_amount"]

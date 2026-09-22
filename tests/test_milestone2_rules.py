"""Milestone 2 pure-rules tests: stats, counters, statuses, and buffs."""

from __future__ import annotations

from datetime import timedelta
import unittest

from server.content.gameplay import load_gameplay_content
from server.game.buffs import TIMED, BuffInstance, active_modifiers, apply_buff, expire
from server.game.modifiers import Modifier, clamp_counter, combine, effective_value
from server.game.state import compute_effective_state
from server.security import utc_now
from tests.common import REPO_ROOT


def load_content():
    """Load the checked-in core gameplay content for tests."""

    return load_gameplay_content(REPO_ROOT / "data" / "core")


class ModifierRulesTests(unittest.TestCase):
    """Modifier ordering, rounding, and bounds."""

    def test_combination_applies_flat_then_summed_percent(self) -> None:
        modifiers = [
            Modifier(target="constitution", flat=2),
            Modifier(target="constitution", percent=0.10),
            Modifier(target="constitution", percent=0.20),
        ]
        self.assertAlmostEqual(combine(10, modifiers), 15.6)

    def test_effective_value_floors_once_and_respects_minimum(self) -> None:
        self.assertEqual(effective_value(10, [Modifier(target="constitution", flat=2)], minimum=0), 12)
        self.assertEqual(
            effective_value(
                10,
                [Modifier(target="constitution", flat=2), Modifier(target="constitution", percent=0.3)],
                minimum=0,
            ),
            15,
        )
        self.assertEqual(effective_value(1, [Modifier(target="constitution", flat=-5)], minimum=0), 0)

    def test_current_value_clamp_retains_fractions(self) -> None:
        self.assertEqual(clamp_counter(150, 100), 100)
        self.assertEqual(clamp_counter(50.5, 100), 50.5)
        self.assertEqual(clamp_counter(-3.2, 100), 0.0)


class EffectiveStateTests(unittest.TestCase):
    """Stat, counter-max, and status calculations."""

    def setUp(self) -> None:
        self.content = load_content()

    def test_base_stats_and_maxima(self) -> None:
        state = compute_effective_state(
            self.content,
            level=0,
            counters={"health": 50, "energy": 80, "cleanliness": 100},
        )
        self.assertEqual(state.stats, {"constitution": 1, "dexterity": 1, "charisma": 1, "fanciness": 1})
        self.assertEqual(state.max_health, 50)
        self.assertEqual(state.max_energy, 80)
        self.assertEqual(state.max_cleanliness, 100)

    def test_constitution_two_doubles_max_health(self) -> None:
        state = compute_effective_state(
            self.content,
            level=0,
            counters={"health": 50, "energy": 80, "cleanliness": 100},
            modifiers=[Modifier(target="constitution", flat=1)],
        )
        self.assertEqual(state.stats["constitution"], 2)
        self.assertEqual(state.max_health, 100)

    def test_sick_drops_constitution_but_health_floor_preserved(self) -> None:
        state = compute_effective_state(
            self.content,
            level=0,
            counters={"health": 0, "energy": 80, "cleanliness": 100},
        )
        self.assertIn("sick", state.statuses)
        self.assertEqual(state.stats["constitution"], 0)
        self.assertEqual(state.stats["dexterity"], 0)
        self.assertGreaterEqual(state.max_health, 1)

    def test_stinky_drops_charisma_and_fanciness(self) -> None:
        state = compute_effective_state(
            self.content,
            level=0,
            counters={"health": 50, "energy": 80, "cleanliness": 0},
        )
        self.assertIn("stinky", state.statuses)
        self.assertEqual(state.stats["charisma"], 0)
        self.assertEqual(state.stats["fanciness"], 0)

    def test_tired_applies_at_zero_and_clears_at_ten_percent(self) -> None:
        applied = compute_effective_state(
            self.content,
            level=0,
            counters={"health": 50, "energy": 0, "cleanliness": 100},
        )
        self.assertIn("tired", applied.statuses)
        cleared = compute_effective_state(
            self.content,
            level=0,
            counters={"health": 50, "energy": 8, "cleanliness": 100},
            previous_statuses=("tired",),
        )
        self.assertNotIn("tired", cleared.statuses)

    def test_max_energy_uses_level_table_with_modifiers(self) -> None:
        state = compute_effective_state(
            self.content,
            level=1,
            counters={"health": 100, "energy": 100, "cleanliness": 100},
            modifiers=[Modifier(target="max_energy", flat=10)],
        )
        self.assertEqual(state.max_energy, 110)


class BuffRulesTests(unittest.TestCase):
    """Timed and stackable buff expiration behavior."""

    def _instance(self, buff_id: str, *, stackable: bool, max_stacks: int, expires_at):
        return BuffInstance(
            id=buff_id,
            label=buff_id.title(),
            kind=TIMED,
            expires_at=expires_at,
            modifiers=(Modifier(target="constitution", flat=1),),
            stackable=stackable,
            max_stacks=max_stacks,
        )

    def test_timed_buff_expires(self) -> None:
        now = utc_now()
        instances = [self._instance("haste", stackable=False, max_stacks=1, expires_at=now + timedelta(seconds=1))]
        self.assertEqual(len(expire(instances, now)), 1)
        self.assertEqual(len(expire(instances, now + timedelta(seconds=2))), 0)

    def test_non_stackable_reapplication_refreshes_without_stacking(self) -> None:
        now = utc_now()
        first = self._instance("haste", stackable=False, max_stacks=1, expires_at=now + timedelta(minutes=1))
        refreshed = self._instance("haste", stackable=False, max_stacks=1, expires_at=now + timedelta(minutes=5))
        result = apply_buff([first], refreshed, now)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].expires_at, refreshed.expires_at)

    def test_stackable_buff_replaces_earliest_at_limit(self) -> None:
        now = utc_now()
        early = self._instance("shield", stackable=True, max_stacks=2, expires_at=now + timedelta(minutes=1))
        late = self._instance("shield", stackable=True, max_stacks=2, expires_at=now + timedelta(minutes=5))
        incoming = self._instance("shield", stackable=True, max_stacks=2, expires_at=now + timedelta(minutes=3))
        result = apply_buff([early, late], incoming, now)
        self.assertEqual(len(result), 2)
        self.assertNotIn(early.expires_at, [instance.expires_at for instance in result])
        self.assertIn(incoming.expires_at, [instance.expires_at for instance in result])

    def test_active_modifiers_ignore_expired(self) -> None:
        now = utc_now()
        fresh = self._instance("haste", stackable=False, max_stacks=1, expires_at=now + timedelta(minutes=1))
        stale = self._instance("slow", stackable=False, max_stacks=1, expires_at=now - timedelta(minutes=1))
        self.assertEqual(len(active_modifiers([fresh, stale], now)), 1)


if __name__ == "__main__":
    unittest.main()

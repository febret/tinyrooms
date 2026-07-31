"""Unit tests for tinyrooms.traits module."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tinyrooms import traits as traits_module
from tinyrooms.traits import (
    TraitRepository,
    TraitDef,
    TraitBuff,
    get_buffs_for_traits,
    get_kudos_rate_modifier,
    get_juice_rate_modifier,
    get_vibe_modifier,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def trait_yaml(tmp_path: Path) -> Path:
    """Write a minimal traits YAML file for testing and return its parent dir."""
    traits_dir = tmp_path / "traits"
    traits_dir.mkdir()
    data = {
        "brave": {
            "label": "🦁 Brave",
            "description": "Fearless in the face of danger.",
            "opposite": "cowardly",
            "buffs": [
                {"stat": "strength", "amount": 15},
                {"stat": "constitution", "amount": 5},
            ],
            "vibe_modifier": 8,
            "kudos_rate_modifier": 1.2,
            "juice_rate_modifier": 1.1,
        },
        "cowardly": {
            "label": "😱 Cowardly",
            "description": "Retreats at the first sign of trouble.",
            "opposite": "brave",
            "buffs": [
                {"stat": "strength", "amount": -10},
            ],
            "vibe_modifier": -3,
            "kudos_rate_modifier": 0.9,
        },
        "witty": {
            "label": "🤡 Witty",
            "description": "Quick with a joke.",
            "buffs": [
                {"stat": "charisma", "amount": 20},
            ],
            "vibe_modifier": 5,
        },
    }
    (traits_dir / "test_traits.yaml").write_text(yaml.safe_dump(data))
    return traits_dir


@pytest.fixture
def repo(trait_yaml: Path) -> TraitRepository:
    return TraitRepository(traits_root=trait_yaml)


# ---------------------------------------------------------------------------
# TraitRepository
# ---------------------------------------------------------------------------

class TestTraitRepository:
    def test_loads_all_traits(self, repo: TraitRepository):
        all_traits = repo.all()
        assert set(all_traits) == {"brave", "cowardly", "witty"}

    def test_get_known_trait(self, repo: TraitRepository):
        td = repo.get("brave")
        assert td is not None
        assert isinstance(td, TraitDef)
        assert td.trait_id == "brave"
        assert td.label == "🦁 Brave"

    def test_get_unknown_trait_returns_none(self, repo: TraitRepository):
        assert repo.get("nonexistent") is None

    def test_list_ids_sorted(self, repo: TraitRepository):
        ids = repo.list_ids()
        assert ids == sorted(ids)

    def test_trait_buffs_parsed(self, repo: TraitRepository):
        td = repo.get("brave")
        assert td is not None
        assert len(td.buffs) == 2
        buff_stats = {b.stat for b in td.buffs}
        assert buff_stats == {"strength", "constitution"}

    def test_trait_opposite(self, repo: TraitRepository):
        td = repo.get("brave")
        assert td is not None
        assert td.opposite == "cowardly"

    def test_trait_no_opposite(self, repo: TraitRepository):
        td = repo.get("witty")
        assert td is not None
        assert td.opposite is None

    def test_trait_rate_modifiers(self, repo: TraitRepository):
        td = repo.get("brave")
        assert td is not None
        assert td.kudos_rate_modifier == pytest.approx(1.2)
        assert td.juice_rate_modifier == pytest.approx(1.1)

    def test_missing_rate_modifiers_default_to_one(self, repo: TraitRepository):
        td = repo.get("witty")
        assert td is not None
        assert td.kudos_rate_modifier == pytest.approx(1.0)
        assert td.juice_rate_modifier == pytest.approx(1.0)

    def test_reload_clears_cache(self, repo: TraitRepository):
        _ = repo.all()
        repo.reload()
        assert not repo._loaded
        _ = repo.all()
        assert repo._loaded

    def test_missing_directory_returns_empty(self, tmp_path: Path):
        empty_repo = TraitRepository(traits_root=tmp_path / "no_such_dir")
        assert empty_repo.all() == {}

    def test_invalid_yaml_skipped_gracefully(self, tmp_path: Path):
        traits_dir = tmp_path / "traits"
        traits_dir.mkdir()
        (traits_dir / "bad.yaml").write_text("this is not: {valid yaml]")
        r = TraitRepository(traits_root=traits_dir)
        # Should not raise; just returns empty
        result = r.all()
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# get_buffs_for_traits
# ---------------------------------------------------------------------------

class TestGetBuffsForTraits:
    def test_single_trait_buffs(self, repo: TraitRepository, monkeypatch):
        monkeypatch.setattr(traits_module, "_repo", repo)
        buffs = get_buffs_for_traits(["brave"])
        assert buffs["strength"] == pytest.approx(15)
        assert buffs["constitution"] == pytest.approx(5)

    def test_two_traits_merge_same_stat(self, repo: TraitRepository, monkeypatch):
        monkeypatch.setattr(traits_module, "_repo", repo)
        # brave: strength +15, cowardly: strength -10 → net +5
        buffs = get_buffs_for_traits(["brave", "cowardly"])
        assert buffs["strength"] == pytest.approx(5)

    def test_empty_trait_list(self, repo: TraitRepository, monkeypatch):
        monkeypatch.setattr(traits_module, "_repo", repo)
        assert get_buffs_for_traits([]) == {}

    def test_unknown_traits_ignored(self, repo: TraitRepository, monkeypatch):
        monkeypatch.setattr(traits_module, "_repo", repo)
        buffs = get_buffs_for_traits(["brave", "undefined_trait"])
        assert "strength" in buffs


# ---------------------------------------------------------------------------
# get_kudos_rate_modifier / get_juice_rate_modifier
# ---------------------------------------------------------------------------

class TestRateModifiers:
    def test_kudos_modifier_single(self, repo: TraitRepository, monkeypatch):
        monkeypatch.setattr(traits_module, "_repo", repo)
        mod = get_kudos_rate_modifier(["brave"])
        assert mod == pytest.approx(1.2)

    def test_kudos_modifier_two_traits_multiplied(self, repo: TraitRepository, monkeypatch):
        monkeypatch.setattr(traits_module, "_repo", repo)
        mod = get_kudos_rate_modifier(["brave", "cowardly"])
        assert mod == pytest.approx(1.2 * 0.9)

    def test_juice_modifier_single(self, repo: TraitRepository, monkeypatch):
        monkeypatch.setattr(traits_module, "_repo", repo)
        mod = get_juice_rate_modifier(["brave"])
        assert mod == pytest.approx(1.1)

    def test_juice_modifier_no_trait(self, repo: TraitRepository, monkeypatch):
        monkeypatch.setattr(traits_module, "_repo", repo)
        assert get_juice_rate_modifier([]) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# get_vibe_modifier
# ---------------------------------------------------------------------------

class TestGetVibeModifier:
    def test_matching_trait_adds_modifier(self, repo: TraitRepository, monkeypatch):
        monkeypatch.setattr(traits_module, "_repo", repo)
        # Both have "brave": vibe_modifier = 8
        vibe = get_vibe_modifier(["brave"], ["brave"])
        assert vibe == pytest.approx(8)

    def test_opposite_trait_subtracts_modifier(self, repo: TraitRepository, monkeypatch):
        monkeypatch.setattr(traits_module, "_repo", repo)
        # A has brave (vibe_modifier=8), B has cowardly (opposite of brave)
        vibe = get_vibe_modifier(["brave"], ["cowardly"])
        assert vibe == pytest.approx(-8)

    def test_unrelated_traits_return_zero(self, repo: TraitRepository, monkeypatch):
        monkeypatch.setattr(traits_module, "_repo", repo)
        vibe = get_vibe_modifier(["brave"], ["witty"])
        assert vibe == pytest.approx(0)

    def test_empty_traits_return_zero(self, repo: TraitRepository, monkeypatch):
        monkeypatch.setattr(traits_module, "_repo", repo)
        assert get_vibe_modifier([], []) == pytest.approx(0)

    def test_multiple_matching_traits(self, repo: TraitRepository, monkeypatch):
        monkeypatch.setattr(traits_module, "_repo", repo)
        # Both brave (8) and witty (5) match
        vibe = get_vibe_modifier(["brave", "witty"], ["brave", "witty"])
        assert vibe == pytest.approx(13)

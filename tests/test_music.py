"""Tests for authored room music defaults and runtime overrides."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from server.commands.music import music_command
from server.commands.outcomes import CommandError
from server.commands.parser import parse_command
from server.services.music import MusicService
from tests.common import REPO_ROOT, load_test_world


class MusicServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.world = load_test_world(REPO_ROOT / "worlds" / "tutorial")
        self.service = MusicService(self.world)

    def test_default_set_off_and_reset(self) -> None:
        default = self.service.current("hub")
        self.assertEqual(default["song"], "GEAwVG1x")

        self.service.set("hub", "custom-song", label="Custom", updated_by="Tester")
        self.assertEqual(
            self.service.current("hub"),
            {"song": "custom-song", "label": "Custom", "updated_by": "Tester"},
        )
        self.assertTrue(self.service.is_overridden("hub"))

        self.service.silence("hub", updated_by="Tester")
        self.assertIsNone(self.service.current("hub"))

        self.service.reset("hub", updated_by="Tester")
        self.assertEqual(self.service.current("hub")["song"], "GEAwVG1x")
        self.assertFalse(self.service.is_overridden("hub"))

    def test_non_owner_cannot_change_music(self) -> None:
        context = SimpleNamespace(
            account=SimpleNamespace(id="account-1", username_display="Tester"),
            connection=SimpleNamespace(room_id="hub"),
            ownership=Mock(),
            powers=Mock(),
            music=self.service,
        )
        context.ownership.owner_of.return_value = "someone-else"
        context.powers.has_power.return_value = False

        with self.assertRaises(CommandError):
            asyncio.run(music_command(context, parse_command(".music set custom-song")))
        self.assertFalse(self.service.is_overridden("hub"))

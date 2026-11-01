from __future__ import annotations

import unittest

from server.commands.core import build_registry


class ActivityInputCommandTests(unittest.TestCase):
    def test_activity_input_is_silent(self) -> None:
        spec = build_registry().get("activity_input")
        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertFalse(spec.toast)
        self.assertFalse(spec.log)

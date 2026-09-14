"""Tests for the client command grammar ported from app/js/commands.js."""

from __future__ import annotations

import unittest

from server.client.commands import (
    build_drop_command,
    build_favorite_command,
    build_go_command,
    build_pickup_command,
    chat_to_command,
    parse_target_token,
    quote,
    tokenize,
)


class CommandGrammarTests(unittest.TestCase):
    """Command parsing, quoting, and building utilities."""

    def test_chat_quoting_round_trips_unicode_and_special_chars(self) -> None:
        text = 'Hello "tiny" room \\ sunshine ☀'
        self.assertEqual(tokenize(chat_to_command(text)), [".say", text])
        self.assertEqual(tokenize(quote(text)), [text])
        self.assertEqual(chat_to_command(" .help "), ".help")
        self.assertEqual(chat_to_command("  "), "")

    def test_target_and_action_builders_preserve_protocol_ids(self) -> None:
        self.assertEqual(parse_target_token("@card:world:stack-1"), {"type": "card", "id": "world:stack-1"})
        self.assertEqual(parse_target_token("@sunbeam"), {"type": "username", "id": "sunbeam"})
        self.assertIsNone(parse_target_token("sunbeam"))
        self.assertEqual(build_go_command("hub"), ".go @way:hub")
        self.assertEqual(build_favorite_command("room"), ".favorite @card:room")
        self.assertEqual(build_pickup_command("stack-1", 2), ".pickup @card:stack-1 2")
        self.assertEqual(build_drop_command("stack-1", 1), ".drop @card:stack-1 1")


if __name__ == "__main__":
    unittest.main()
"""Shared macro-page defaults and normalization for profile-backed chat macros."""

from __future__ import annotations

MACRO_PAGES = 5
MACROS_PER_PAGE = 6
MACRO_COUNT = MACRO_PAGES * MACROS_PER_PAGE
MAX_MACRO_LENGTH = 80

# Four starter pages of short expressions; the last page stays free for the
# player. Empty strings are intentional editable slots.
DEFAULT_MACROS: tuple[str, ...] = (
    "Yes 👍",
    "No 👎",
    "Welcome! 👋",
    "Thanks! 🙏",
    "Hello! 😊",
    "Goodbye! 👋",
    "Please 🙂",
    "Sorry 😔",
    "Help! 🆘",
    "Nice! 👍",
    "Wow! 😮",
    "Haha 😄",
    "Good morning ☀️",
    "Good night 🌙",
    "I agree ✅",
    "I disagree ❌",
    "Wait ✋",
    "Let's go! 🚀",
    "Good job! 👏",
    "I'm here 🙋",
    "See you! 👋",
    "Love it! ❤️",
    "Cool! 😎",
    "Oops! 😅",
    "",
    "",
    "",
    "",
    "",
    "",
)


def normalize_macro_text(raw: object) -> str:
    """Collapse a macro to one trimmed line capped at the profile limit."""

    if not isinstance(raw, str):
        return ""
    return " ".join(raw.split())[:MAX_MACRO_LENGTH]


def normalize_macros(raw: object) -> list[str]:
    """Return a full 5x6 macro grid, preserving blanks the player cleared."""

    values = list(DEFAULT_MACROS)
    if not isinstance(raw, list):
        return values
    for index, value in enumerate(raw[:MACRO_COUNT]):
        values[index] = normalize_macro_text(value)
    return values

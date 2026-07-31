from __future__ import annotations

from collections import OrderedDict
from typing import Any, Callable

from .registry import CommandSpec


_GROUP_LABELS: dict[str, str] = {
    "any-user": "Available commands",
    "realtor": "Realtor commands",
    "builder": "Builder commands",
    "admin": "Admin power commands",
    "moderator": "Moderator commands",
    "game-master": "Game-master commands",
}


def _summary_from_handler(spec: CommandSpec) -> str:
    if spec.summary:
        return spec.summary
    doc = (spec.handler.__doc__ or "").strip()
    if doc:
        return doc.splitlines()[0].strip().rstrip(".")
    return "Run this command"


def _group_key(spec: CommandSpec) -> str:
    return spec.power or "any-user"


def build_help_text(user_obj: Any, commands: list[CommandSpec], linker: Callable[[str, str], str]) -> str:
    powers = sorted(user_obj.powers) if getattr(user_obj, "powers", None) else []
    lines: list[str] = [
        f"**User:** {user_obj.username}",
        f"**Powers:** {', '.join(powers) if powers else '(none)'}",
        "",
    ]

    grouped: "OrderedDict[str, list[CommandSpec]]" = OrderedDict()
    for spec in commands:
        if spec.power and not user_obj.has_power(spec.power):
            continue
        grouped.setdefault(_group_key(spec), []).append(spec)

    for group, specs in grouped.items():
        lines.append(f"**{_GROUP_LABELS.get(group, group.title() + ' commands')}:**")
        seen: set[str] = set()
        for spec in specs:
            key = f"{spec.pattern}|{spec.power or ''}"
            if key in seen:
                continue
            seen.add(key)
            cmd_text = f":{spec.pattern}"
            link = linker(cmd_text, cmd_text)
            lines.append(f"  {link} — {_summary_from_handler(spec)}")
        lines.append("")

    if lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


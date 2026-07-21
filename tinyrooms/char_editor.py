from __future__ import annotations

import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import user_data, icons, sprites, utils
from .icons import DEFAULT_USER_ASSETS


UNSET = object()


def _sprite_reference(scope: str, filename: str, sprite_id: str) -> str:
    if scope == "server":
        return f"$/{filename}/{sprite_id}"
    return f"${filename}/{sprite_id}"


def list_available_sprite_options(sprite_repo: sprites.SpriteRepository) -> list[dict[str, Any]]:
    available: list[dict[str, Any]] = []
    for record in sprite_repo.list_sets():
        sprite_set = record.sprite_set
        if sprite_set is None:
            continue
        for sprite_id in sprite_set.sprites:
            sprite_ref = _sprite_reference(sprite_set.scope, sprite_set.filename, sprite_id)
            parsed = sprites.parse_sprite_reference(sprite_ref)
            if parsed is None:
                continue
            resolved = sprites.resolve_sprite_reference(parsed, sprite_repo)
            available.append(
                {
                    "sprite_ref": sprite_ref,
                    "scope": sprite_set.scope,
                    "filename": sprite_set.filename,
                    "sprite_id": sprite_id,
                    "label": sprite_set.label or f"{sprite_set.filename}/{sprite_id}",
                    "set_label": sprite_set.label or sprite_set.filename,
                    "set_description": sprite_set.description or "",
                    "image_url": resolved["image_url"],
                    "frame": resolved["frame"],
                    "background_color": resolved.get("background_color"),
                }
            )
    available.sort(
        key=lambda item: (
            0 if item["scope"] == "world" else 1,
            str(item["filename"]),
            str(item["sprite_id"]),
        )
    )
    return available


def _current_sprite_asset(username: str, current_sprite: Any) -> str | None:
    if not isinstance(current_sprite, str) or not current_sprite.strip():
        return None
    normalized = current_sprite.strip()
    if sprites.parse_sprite_reference(normalized) is not None:
        return normalized
    candidate = user_data.user_root(username) / normalized
    if not candidate.exists() or not candidate.is_file():
        return None
    return user_data.user_asset_url(username, normalized)


def resolve_character_sprite_preview(
    username: str,
    current_sprite: Any,
    sprite_repo: sprites.SpriteRepository,
) -> dict[str, Any] | None:
    if not isinstance(current_sprite, str) or not current_sprite.strip():
        return None
    normalized = current_sprite.strip()
    sprite_ref = sprites.parse_sprite_reference(normalized)
    if sprite_ref is None:
        return {
            "sprite_ref": normalized,
            "image_url": user_data.user_asset_url(username, normalized),
            "frame": None,
        }
    resolved = sprites.resolve_sprite_reference(sprite_ref, sprite_repo)
    return {
        "sprite_ref": normalized,
        "scope": resolved["scope"],
        "filename": resolved["filename"],
        "sprite_id": resolved["sprite_id"],
        "image_url": resolved["image_url"],
        "frame": resolved["frame"],
        "background_color": resolved.get("background_color"),
        "animation": resolved.get("animation"),
    }


def build_character_display_assets(
    username: str,
    char: dict[str, Any],
    world_root_path: str | Path,
    sprite_repo: sprites.SpriteRepository | None = None,
) -> dict[str, Any]:
    main_image = char.get("main_image")
    main_image_asset = DEFAULT_USER_ASSETS["img"]
    if isinstance(main_image, str) and main_image.strip():
        main_image_asset = user_data.user_asset_url(username, main_image)
    sprite_asset = _current_sprite_asset(username, char.get("current_sprite")) or main_image_asset
    return icons.build_display_assets(
        {
            "img": main_image_asset,
            "icon": main_image_asset,
            "sprite": sprite_asset,
        },
        world_root_path,
        sprite_repo=sprite_repo,
    )


class CharacterEditorService:
    def __init__(self, make_image_script: Path, temp_root: Path):
        self._make_image_script = Path(make_image_script)
        self._temp_root = Path(temp_root)

    def stop(self):
        return None

    def profile(self, username: str, sprite_repo: sprites.SpriteRepository) -> dict[str, Any]:
        char = user_data.read_char(username)
        return {
            "available_sprites": self.list_available_sprites(sprite_repo),
            "char": self._char_for_client(username, char, sprite_repo),
        }

    def update_profile(
        self,
        username: str,
        sprite_repo: sprites.SpriteRepository,
        description: str | None = None,
        current_sprite: str | None | object = UNSET,
    ) -> dict[str, Any]:
        current = user_data.read_char(username)
        next_description = self.validate_description(
            description if description is not None else current.get("description", "")
        )
        next_sprite = self.validate_current_sprite(
            username,
            current.get("current_sprite") if current_sprite is UNSET else current_sprite,
            sprite_repo,
        )
        updated = user_data.write_char(
            username,
            description=next_description,
            current_sprite=next_sprite,
            main_image=current.get("main_image"),
        )
        return self._char_for_client(username, updated, sprite_repo)

    def generate_main_image(
        self,
        username: str,
        sprite_repo: sprites.SpriteRepository,
        description: str | None = None,
        current_sprite: str | None | object = UNSET,
    ) -> dict[str, Any]:
        current = user_data.read_char(username)
        next_description = self.validate_description(
            description if description is not None else current.get("description", "")
        )
        next_sprite = self.validate_current_sprite(
            username,
            current.get("current_sprite") if current_sprite is UNSET else current_sprite,
            sprite_repo,
        )
        main_image_rel = self._generate_and_persist_main_image(
            username=username,
            description=next_description,
            previous_main_image=current.get("main_image"),
        )
        updated = user_data.write_char(
            username,
            description=next_description,
            current_sprite=next_sprite,
            main_image=main_image_rel,
        )
        return self._char_for_client(username, updated, sprite_repo)

    def list_available_sprites(self, sprite_repo: sprites.SpriteRepository) -> list[dict[str, Any]]:
        return list_available_sprite_options(sprite_repo)

    def validate_description(self, description: Any) -> str:
        if description is None:
            return ""
        if not isinstance(description, str):
            raise ValueError("description must be a string")
        normalized = description.strip()
        if len(normalized) > 280:
            raise ValueError("description is too long")
        return normalized

    def validate_current_sprite(
        self,
        username: str,
        current_sprite: Any,
        sprite_repo: sprites.SpriteRepository,
    ) -> str | None:
        if current_sprite is None:
            return None
        if not isinstance(current_sprite, str):
            raise ValueError("current_sprite must be a string or null")
        normalized = current_sprite.strip()
        if not normalized:
            return None
        sprite_ref = sprites.parse_sprite_reference(normalized)
        if sprite_ref is not None:
            sprites.resolve_sprite_reference(sprite_ref, sprite_repo)
            return normalized
        if "/" in normalized or "\\" in normalized:
            candidate = user_data.user_root(username) / normalized
            if candidate.exists() and candidate.is_file():
                return normalized.replace("\\", "/")
        raise ValueError("invalid current_sprite")

    def _char_for_client(
        self,
        username: str,
        char: dict[str, Any],
        sprite_repo: sprites.SpriteRepository,
    ) -> dict[str, Any]:
        out = dict(char)
        main_image = out.get("main_image")
        out["main_image_url"] = (
            user_data.user_asset_url(username, main_image)
            if isinstance(main_image, str) and main_image.strip()
            else None
        )
        preview = resolve_character_sprite_preview(username, out.get("current_sprite"), sprite_repo)
        out["current_sprite_preview"] = preview
        out["current_sprite_url"] = preview.get("image_url") if preview else None
        out["current_sprite_id"] = preview.get("sprite_id") if preview else None
        return out

    def _generate_and_persist_main_image(
        self,
        username: str,
        description: str,
        previous_main_image: Any,
    ) -> str:
        prompt = f"portrait of a game character. {description}" if description else "portrait of a game character"
        output_name = f"char_main_{uuid.uuid4().hex[:12]}.png"
        temp_output = self._temp_root / output_name
        temp_output.parent.mkdir(parents=True, exist_ok=True)
        utils.run_image_subprocess(
            self._make_image_script,
            temp_output,
            log_label=f"char-main:{username}",
            extra_args=["--description", prompt],
        )

        _, _, images_dir, _ = user_data.ensure_user_paths(username)
        final_name = f"main_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.png"
        final_path = images_dir / final_name
        try:
            shutil.move(str(temp_output), str(final_path))
        except OSError as err:
            raise ValueError(f"failed to persist main image: {err}") from err

        if isinstance(previous_main_image, str) and previous_main_image.startswith("images/"):
            previous_path = user_data.user_root(username) / previous_main_image
            if previous_path.exists() and previous_path.is_file():
                previous_path.unlink(missing_ok=True)

        return f"images/{final_name}"


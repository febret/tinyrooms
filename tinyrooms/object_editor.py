from __future__ import annotations

import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import yaml

from . import char_data, char_editor, sprites


def _images_dir(username: str) -> Path:
    return char_data.user_root(username) / "thing_images"


def _ensure_images_dir(username: str) -> Path:
    char_data.ensure_user_paths(username)
    images_dir = _images_dir(username)
    images_dir.mkdir(parents=True, exist_ok=True)
    return images_dir


def image_rel_path(image_id: str) -> str:
    if not image_id or "/" in image_id or "\\" in image_id:
        raise ValueError("invalid image id")
    return f"thing_images/{image_id}"


def image_url(username: str, rel_path: str) -> str:
    return char_data.user_asset_url(username, rel_path)


def image_file_path(username: str, rel_path: str) -> Path:
    if not isinstance(rel_path, str) or not rel_path.strip():
        raise FileNotFoundError("image not found")
    normalized = rel_path.replace("\\", "/").strip().lstrip("/")
    if not normalized.startswith("thing_images/"):
        raise ValueError("invalid image path")
    path = char_data.user_root(username) / normalized
    if not path.exists() or not path.is_file():
        raise FileNotFoundError("image not found")
    return path


class ObjectEditorService:
    def __init__(self, config_path: Path, make_image_script: Path, temp_root: Path):
        self._config_path = Path(config_path)
        self._make_image_script = Path(make_image_script)
        self._temp_root = Path(temp_root)
        self._config = self._load_config()

    def stop(self):
        return None

    def _load_config(self) -> dict[str, Any]:
        with open(self._config_path, "r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
        if not isinstance(loaded, dict):
            raise ValueError("object-editor config must be a mapping")
        return loaded

    def profile(self, sprite_repo: sprites.SpriteRepository) -> dict[str, Any]:
        return {
            "available_sprites": char_editor.list_available_sprite_options(sprite_repo),
        }

    def generate_image(self, username: str, description: str, previous_image: Any = None) -> dict[str, str]:
        normalized_description = self.validate_description(description)
        rel_path = self._generate_and_persist_image(username, normalized_description, previous_image=previous_image)
        return {
            "image_path": rel_path,
            "image_url": image_url(username, rel_path),
        }

    def validate_description(self, description: Any) -> str:
        if not isinstance(description, str):
            raise ValueError("description must be a string")
        normalized = description.strip()
        if not normalized:
            raise ValueError("description is required")
        if len(normalized) > 280:
            raise ValueError("description is too long")
        return normalized

    def validate_current_sprite(
        self,
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
        if sprite_ref is None:
            raise ValueError("invalid current_sprite")
        sprites.resolve_sprite_reference(sprite_ref, sprite_repo)
        return normalized

    def validate_image_path(self, username: str, rel_path: Any) -> str | None:
        if rel_path is None:
            return None
        if not isinstance(rel_path, str):
            raise ValueError("image_path must be a string or null")
        normalized = rel_path.replace("\\", "/").strip().lstrip("/")
        if not normalized:
            return None
        image_file_path(username, normalized)
        return normalized

    def build_object_info(
        self,
        *,
        username: str,
        description: str,
        current_sprite: str | None,
        image_asset_url: str | None,
    ) -> dict[str, Any]:
        normalized_description = self.validate_description(description)
        label = normalized_description[:48].strip()
        if len(normalized_description) > 48:
            label = f"{label}..."
        if not label:
            label = "Created Thing"
        if not (current_sprite or image_asset_url):
            raise ValueError("a sprite or image is required")
        sprite_asset = current_sprite or image_asset_url
        image_asset = image_asset_url or current_sprite
        metadata: dict[str, Any] = {
            "created_by": username,
            "generated_at": char_data._now_iso(),
        }
        if current_sprite:
            metadata["selected_sprite_ref"] = current_sprite
        if image_asset_url:
            metadata["generated_image"] = True
        return {
            "type": "object",
            "label": label,
            "description": normalized_description,
            "img": image_asset,
            "sprite": sprite_asset,
            "icon": image_asset,
            "tags": ["item", "generated"],
            "metadata": metadata,
        }

    def _generate_and_persist_image(self, username: str, description: str, previous_image: Any = None) -> str:
        output_name = f"thing_image_{uuid.uuid4().hex[:12]}.png"
        temp_output = self._temp_root / output_name
        temp_output.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            sys.executable,
            str(self._make_image_script),
            str(temp_output),
            "--size",
            "256x256",
            "--description",
            description,
        ]
        style = str(self._config.get("style", "")).strip()
        if style:
            cmd.extend(["--style", style])
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except OSError as err:
            raise ValueError(str(err)) from err
        captured_lines: list[str] = []
        if proc.stdout is not None:
            for raw_line in proc.stdout:
                line = raw_line.rstrip("\n")
                captured_lines.append(line)
                print(f"[make-image:thing-image:{username}] {line}", flush=True)
        return_code = proc.wait()
        if return_code != 0:
            err = "\n".join(captured_lines).strip() or "object image generation failed"
            raise ValueError(err)
        if not temp_output.exists():
            raise ValueError("object image output missing")
        if temp_output.suffix.lower() != ".png":
            raise ValueError("object image output must be png")

        images_dir = _ensure_images_dir(username)
        final_name = f"thing_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.png"
        final_path = images_dir / final_name
        try:
            shutil.move(str(temp_output), str(final_path))
        except OSError as err:
            raise ValueError(f"failed to persist object image: {err}") from err

        previous_normalized = self.validate_image_path(username, previous_image) if previous_image else None
        if previous_normalized:
            previous_path = char_data.user_root(username) / previous_normalized
            if previous_path.exists() and previous_path.is_file():
                previous_path.unlink(missing_ok=True)

        return image_rel_path(final_name)

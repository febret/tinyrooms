from __future__ import annotations

import json
import multiprocessing
import queue
import shutil
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from . import char_data


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _worker_main(task_queue, result_queue, stop_event, make_sprite_script: str):
    while not stop_event.is_set():
        try:
            task = task_queue.get(timeout=0.25)
        except queue.Empty:
            continue
        if task is None:
            break
        request_id = task["request_id"]
        output_path = task["temp_output"]
        cmd = [
            sys.executable,
            make_sprite_script,
            output_path,
            "--descriptors-json",
            json.dumps(task["descriptors"]),
            "--border-color",
            task["border_color"],
            "--glow-color",
            task["glow_color"],
        ]
        captured_lines: list[str] = []
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except OSError as err:
            result_queue.put({"request_id": request_id, "ok": False, "error": str(err)})
            continue
        if proc.stdout is not None:
            for raw_line in proc.stdout:
                line = raw_line.rstrip("\n")
                captured_lines.append(line)
                print(f"[make-sprite:{request_id}] {line}", flush=True)
        return_code = proc.wait()
        if return_code != 0:
            err = "\n".join(captured_lines).strip() or "make-sprite failed"
            result_queue.put({"request_id": request_id, "ok": False, "error": err})
            continue
        result_queue.put({"request_id": request_id, "ok": True, "temp_output": output_path})


class CharacterEditorService:
    def __init__(self, config_path: Path, make_sprite_script: Path, temp_root: Path):
        self._config_path = Path(config_path)
        self._make_sprite_script = Path(make_sprite_script)
        self._temp_root = Path(temp_root)
        self._config = self._load_config()
        self._appearance_defaults = self._build_appearance_defaults()

        self._lock = threading.RLock()
        self._requests: dict[str, dict[str, Any]] = {}
        self._queue: deque[str] = deque()
        self._running_request_id: str | None = None
        self._active_by_user: dict[str, str] = {}

        self._task_queue = multiprocessing.Queue()
        self._result_queue = multiprocessing.Queue()
        self._stop_event = multiprocessing.Event()
        self._worker = multiprocessing.Process(
            target=_worker_main,
            args=(self._task_queue, self._result_queue, self._stop_event, str(self._make_sprite_script)),
            daemon=True,
            name="tinyrooms-char-editor-worker",
        )
        self._worker.start()

        self._monitor_stop = threading.Event()
        self._monitor = threading.Thread(target=self._monitor_loop, daemon=True, name="char-editor-monitor")
        self._monitor.start()

    def stop(self):
        self._monitor_stop.set()
        self._stop_event.set()
        try:
            self._task_queue.put_nowait(None)
        except Exception:
            pass
        if self._monitor.is_alive():
            self._monitor.join(timeout=2)
        if self._worker.is_alive():
            self._worker.join(timeout=2)
        if self._worker.is_alive():
            self._worker.kill()

    def _load_config(self) -> dict[str, Any]:
        with open(self._config_path, "r", encoding="utf-8") as handle:
            config = yaml.safe_load(handle) or {}
        descriptor_classes = config.get("descriptor_classes", {})
        if not isinstance(descriptor_classes, dict) or not descriptor_classes:
            raise ValueError("char-editor descriptor_classes config missing")
        return config

    def _build_appearance_defaults(self) -> dict[str, str]:
        defaults: dict[str, str] = {}
        for descriptor_key, descriptor_meta in self._config["descriptor_classes"].items():
            options = descriptor_meta.get("options", [])
            if not options:
                continue
            first = options[0]
            if isinstance(first, dict):
                defaults[descriptor_key] = str(first.get("id", ""))
            else:
                defaults[descriptor_key] = str(first)
        return defaults

    def profile(self, username: str) -> dict[str, Any]:
        char = char_data.read_char(username, appearance_defaults=self._appearance_defaults)
        sprites = char_data.list_user_sprites(username)
        return {
            "descriptor_classes": self._config["descriptor_classes"],
            "char": self._char_for_client(username, char),
            "sprites": sprites,
            "queue": self.queue_summary(username),
        }

    def _char_for_client(self, username: str, char: dict[str, Any]) -> dict[str, Any]:
        out = dict(char)
        current_sprite = out.get("current_sprite")
        if isinstance(current_sprite, str) and current_sprite:
            out["current_sprite_url"] = char_data.sprite_url(username, current_sprite)
            out["current_sprite_id"] = Path(current_sprite).name
        else:
            out["current_sprite_url"] = None
            out["current_sprite_id"] = None
        return out

    def queue_summary(self, username: str | None = None) -> dict[str, Any]:
        with self._lock:
            queued_ids = [rid for rid in self._queue if self._requests.get(rid, {}).get("status") == "queued"]
            running = 1 if self._running_request_id is not None else 0
            out = {"queued": len(queued_ids), "running": running}
            if username:
                req_id = self._active_by_user.get(username)
                if req_id:
                    req = self._requests.get(req_id)
                    out["active_request_id"] = req_id
                    out["active_status"] = req.get("status") if req else None
                    out["items_ahead"] = self._items_ahead_locked(req_id)
                else:
                    out["active_request_id"] = None
                    out["active_status"] = None
                    out["items_ahead"] = 0
            return out

    def submit_request(self, username: str, descriptors: dict[str, str]) -> dict[str, Any]:
        validated = self.validate_descriptors(descriptors)
        with self._lock:
            existing_id = self._active_by_user.get(username)
            if existing_id:
                existing_req = self._requests.get(existing_id)
                if existing_req and existing_req["status"] in {"queued", "running"}:
                    raise ValueError("user already has an active request")

            req_id = f"req_{uuid.uuid4().hex[:12]}"
            req = {
                "request_id": req_id,
                "username": username,
                "descriptors": validated,
                "status": "queued",
                "created_at": _utc_now(),
                "updated_at": _utc_now(),
                "started_at": None,
                "finished_at": None,
                "error": None,
                "sprite_id": None,
                "sprite_path": None,
                "sprite_url": None,
                "temp_output": None,
            }
            self._requests[req_id] = req
            self._queue.append(req_id)
            self._active_by_user[username] = req_id
            # Appearance changes are persisted immediately even before selection.
            current_char = char_data.read_char(username, appearance_defaults=self._appearance_defaults)
            char_data.write_char(
                username,
                appearance=validated,
                current_sprite=current_char.get("current_sprite"),
                appearance_defaults=self._appearance_defaults,
            )
            self._dispatch_next_locked()
            return self._request_for_client_locked(req_id, username)

    def get_request(self, username: str, request_id: str) -> dict[str, Any]:
        with self._lock:
            req = self._requests.get(request_id)
            if not req or req["username"] != username:
                raise KeyError("request not found")
            return self._request_for_client_locked(request_id, username)

    def cancel_request(self, username: str, request_id: str) -> dict[str, Any]:
        with self._lock:
            req = self._requests.get(request_id)
            if not req or req["username"] != username:
                raise KeyError("request not found")
            status = req["status"]
            if status == "queued":
                req["status"] = "cancelled"
                req["updated_at"] = _utc_now()
                req["finished_at"] = _utc_now()
                self._remove_from_queue_locked(request_id)
                self._active_by_user.pop(username, None)
                return self._request_for_client_locked(request_id, username)
            if status == "running":
                req["status"] = "cancelled"
                req["updated_at"] = _utc_now()
                req["finished_at"] = _utc_now()
                self._active_by_user.pop(username, None)
                return self._request_for_client_locked(request_id, username)
            return self._request_for_client_locked(request_id, username)

    def select_sprite(
        self,
        username: str,
        sprite_id: str,
        descriptors: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        rel = char_data.sprite_rel_path(sprite_id)
        sprite_path = char_data.user_root(username) / rel
        if not sprite_path.exists():
            raise FileNotFoundError("sprite not found")
        current = char_data.read_char(username, appearance_defaults=self._appearance_defaults)
        appearance = current.get("appearance", {})
        if descriptors is not None:
            appearance = self.validate_descriptors(descriptors)
        updated = char_data.write_char(
            username,
            appearance=appearance,
            current_sprite=rel,
            appearance_defaults=self._appearance_defaults,
        )
        return self._char_for_client(username, updated)

    def discard_sprite(self, username: str, sprite_id: str) -> bool:
        rel = char_data.sprite_rel_path(sprite_id)
        sprite_path = char_data.user_root(username) / rel
        if not sprite_path.exists():
            raise FileNotFoundError("sprite not found")
        sprite_path.unlink()
        current = char_data.read_char(username, appearance_defaults=self._appearance_defaults)
        current_sprite = current.get("current_sprite")
        if current_sprite == rel:
            char_data.write_char(
                username,
                appearance=current.get("appearance", {}),
                current_sprite=None,
                appearance_defaults=self._appearance_defaults,
            )
            return True
        return False

    def validate_descriptors(self, descriptors: dict[str, str]) -> dict[str, str]:
        if not isinstance(descriptors, dict):
            raise ValueError("descriptors must be an object")
        normalized = dict(self._appearance_defaults)
        for descriptor_key, descriptor_meta in self._config["descriptor_classes"].items():
            options = descriptor_meta.get("options", [])
            allowed: set[str] = set()
            for opt in options:
                if isinstance(opt, dict):
                    allowed.add(str(opt.get("id", "")))
                else:
                    allowed.add(str(opt))
            provided = descriptors.get(descriptor_key, normalized.get(descriptor_key))
            if provided not in allowed:
                raise ValueError(f"invalid value for {descriptor_key}")
            normalized[descriptor_key] = str(provided)
        return normalized

    def _request_for_client_locked(self, request_id: str, username: str) -> dict[str, Any]:
        req = dict(self._requests[request_id])
        req["items_ahead"] = self._items_ahead_locked(request_id)
        req["queue"] = self.queue_summary(username)
        return req

    def _items_ahead_locked(self, request_id: str) -> int:
        req = self._requests.get(request_id)
        if req is None:
            return 0
        if req["status"] == "running":
            return 0
        if req["status"] != "queued":
            return 0

        ahead = 1 if self._running_request_id else 0
        for rid in self._queue:
            if rid == request_id:
                break
            queued_req = self._requests.get(rid)
            if queued_req and queued_req["status"] == "queued":
                ahead += 1
        return ahead

    def _monitor_loop(self):
        while not self._monitor_stop.is_set():
            self._drain_results()
            with self._lock:
                self._dispatch_next_locked()
            time.sleep(0.1)

    def _drain_results(self):
        while True:
            try:
                result = self._result_queue.get_nowait()
            except queue.Empty:
                return
            self._on_worker_result(result)

    def _remove_from_queue_locked(self, request_id: str):
        try:
            self._queue.remove(request_id)
        except ValueError:
            pass

    def _dispatch_next_locked(self):
        if self._running_request_id is not None:
            return
        while self._queue:
            req_id = self._queue.popleft()
            req = self._requests.get(req_id)
            if not req or req["status"] != "queued":
                continue
            req["status"] = "running"
            req["updated_at"] = _utc_now()
            req["started_at"] = _utc_now()
            temp_path = self._temp_root / f"{req_id}.png"
            temp_path.parent.mkdir(parents=True, exist_ok=True)
            req["temp_output"] = str(temp_path)
            style = self._config.get("server_style_presets", {})
            self._task_queue.put(
                {
                    "request_id": req_id,
                    "descriptors": req["descriptors"],
                    "temp_output": str(temp_path),
                    "border_color": str(style.get("border_color", "#6aa5ff")),
                    "glow_color": str(style.get("glow_color", "#5a94ff")),
                }
            )
            self._running_request_id = req_id
            print(f"char-editor: request {req_id} running for user {req['username']}")
            return

    def _on_worker_result(self, result: dict[str, Any]):
        request_id = result["request_id"]
        with self._lock:
            req = self._requests.get(request_id)
            if req is None:
                return
            self._running_request_id = None
            username = req["username"]
            cancelled = req["status"] == "cancelled"
            if cancelled:
                temp_output = req.get("temp_output")
                if temp_output:
                    tmp = Path(temp_output)
                    if tmp.exists():
                        tmp.unlink()
                self._dispatch_next_locked()
                return

            if not result.get("ok"):
                req["status"] = "failed"
                req["updated_at"] = _utc_now()
                req["finished_at"] = _utc_now()
                req["error"] = result.get("error", "generation failed")
                self._active_by_user.pop(username, None)
                print(f"char-editor: request {request_id} failed: {req['error']}")
                self._dispatch_next_locked()
                return

            temp_output = Path(result["temp_output"])
            if not temp_output.exists():
                req["status"] = "failed"
                req["updated_at"] = _utc_now()
                req["finished_at"] = _utc_now()
                req["error"] = "sprite output missing"
                self._active_by_user.pop(username, None)
                self._dispatch_next_locked()
                return

            _, sprites_dir, _ = char_data.ensure_user_paths(username)
            sprite_id = f"sprite_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{request_id[-6:]}.png"
            final_path = sprites_dir / sprite_id
            try:
                shutil.move(str(temp_output), str(final_path))
            except OSError as err:
                req["status"] = "failed"
                req["updated_at"] = _utc_now()
                req["finished_at"] = _utc_now()
                req["error"] = f"failed to persist sprite: {err}"
                self._active_by_user.pop(username, None)
                self._dispatch_next_locked()
                return

            req["status"] = "done"
            req["updated_at"] = _utc_now()
            req["finished_at"] = _utc_now()
            rel = char_data.sprite_rel_path(sprite_id)
            req["sprite_id"] = sprite_id
            req["sprite_path"] = rel
            req["sprite_url"] = char_data.sprite_url(username, rel)
            self._active_by_user.pop(username, None)
            print(f"char-editor: request {request_id} done -> {sprite_id}")
            self._dispatch_next_locked()

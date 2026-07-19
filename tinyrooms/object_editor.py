from __future__ import annotations

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


def _icons_dir(username: str) -> Path:
    return char_data.user_root(username) / "thing_icons"


def _ensure_icons_dir(username: str) -> Path:
    char_data.ensure_user_paths(username)
    icons_dir = _icons_dir(username)
    icons_dir.mkdir(parents=True, exist_ok=True)
    return icons_dir


def icon_rel_path(icon_id: str) -> str:
    if not icon_id or "/" in icon_id or "\\" in icon_id:
        raise ValueError("invalid icon id")
    return f"thing_icons/{icon_id}"


def icon_url(username: str, rel_path: str) -> str:
    return char_data.sprite_url(username, rel_path)


def icon_file_path(username: str, icon_id: str) -> Path:
    rel = icon_rel_path(icon_id)
    path = char_data.user_root(username) / rel
    if not path.exists():
        raise FileNotFoundError("icon not found")
    return path


def list_user_icons(username: str) -> list[dict[str, str]]:
    icons_dir = _icons_dir(username)
    if not icons_dir.exists():
        return []
    out: list[dict[str, str]] = []
    icon_paths = sorted(
        (p for p in icons_dir.iterdir() if p.is_file() and p.suffix.lower() == ".png"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for icon_path in icon_paths:
        icon_id = icon_path.name
        rel = icon_rel_path(icon_id)
        out.append(
            {
                "icon_id": icon_id,
                "icon_path": rel,
                "icon_url": icon_url(username, rel),
            }
        )
    return out


def _worker_main(task_queue, result_queue, stop_event, make_icon_script: str):
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
            make_icon_script,
            output_path,
            task["description"],
        ]
        style = str(task.get("style", "")).strip()
        if style:
            cmd.extend(["--style", style])
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
                print(f"[make-icon:{request_id}] {line}", flush=True)
        return_code = proc.wait()
        if return_code != 0:
            err = "\n".join(captured_lines).strip() or "make-icon failed"
            result_queue.put({"request_id": request_id, "ok": False, "error": err})
            continue
        result_queue.put({"request_id": request_id, "ok": True, "temp_output": output_path})


class ObjectEditorService:
    def __init__(self, config_path: Path, make_icon_script: Path, temp_root: Path):
        self._config_path = Path(config_path)
        self._make_icon_script = Path(make_icon_script)
        self._temp_root = Path(temp_root)
        self._config = self._load_config()

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
            args=(self._task_queue, self._result_queue, self._stop_event, str(self._make_icon_script)),
            daemon=True,
            name="tinyrooms-object-editor-worker",
        )
        self._worker.start()

        self._monitor_stop = threading.Event()
        self._monitor = threading.Thread(target=self._monitor_loop, daemon=True, name="object-editor-monitor")
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
            loaded = yaml.safe_load(handle) or {}
        if not isinstance(loaded, dict):
            raise ValueError("object-editor config must be a mapping")
        return loaded

    def profile(self, username: str) -> dict[str, Any]:
        return {
            "icons": list_user_icons(username),
            "queue": self.queue_summary(username),
        }

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

    def submit_request(self, username: str, description: str) -> dict[str, Any]:
        normalized_description = self.validate_description(description)
        with self._lock:
            existing_id = self._active_by_user.get(username)
            if existing_id:
                existing_req = self._requests.get(existing_id)
                if existing_req and existing_req["status"] in {"queued", "running"}:
                    raise ValueError("user already has an active request")
            req_id = f"obj_req_{uuid.uuid4().hex[:12]}"
            req = {
                "request_id": req_id,
                "username": username,
                "description": normalized_description,
                "status": "queued",
                "created_at": _utc_now(),
                "updated_at": _utc_now(),
                "started_at": None,
                "finished_at": None,
                "error": None,
                "icon_id": None,
                "icon_path": None,
                "icon_url": None,
                "temp_output": None,
            }
            self._requests[req_id] = req
            self._queue.append(req_id)
            self._active_by_user[username] = req_id
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

    def discard_icon(self, username: str, icon_id: str) -> None:
        icon_path = icon_file_path(username, icon_id)
        icon_path.unlink()

    def validate_description(self, description: str) -> str:
        if not isinstance(description, str):
            raise ValueError("description must be a string")
        normalized = description.strip()
        if not normalized:
            raise ValueError("description is required")
        if len(normalized) > 280:
            raise ValueError("description is too long")
        return normalized

    def build_object_info(
        self,
        *,
        username: str,
        icon_id: str,
        description: str,
        icon_asset_url: str,
    ) -> dict[str, Any]:
        normalized_description = self.validate_description(description)
        if not isinstance(icon_asset_url, str) or not icon_asset_url.strip():
            raise ValueError("icon asset url is required")
        icon_file_path(username, icon_id)
        label = normalized_description[:48].strip()
        if len(normalized_description) > 48:
            label = f"{label}..."
        if not label:
            label = "Created Thing"
        return {
            "type": "object",
            "label": label,
            "description": normalized_description,
            "img": icon_asset_url,
            "sprite": icon_asset_url,
            "icon": icon_asset_url,
            "tags": ["item", "generated"],
            "metadata": {
                "created_by": username,
                "generated_icon_id": icon_id,
                "generated_at": _utc_now(),
            },
        }

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
            style = str(self._config.get("style", "")).strip()
            self._task_queue.put(
                {
                    "request_id": req_id,
                    "description": req["description"],
                    "temp_output": str(temp_path),
                    "style": style,
                }
            )
            self._running_request_id = req_id
            print(f"object-editor: request {req_id} running for user {req['username']}")
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
                print(f"object-editor: request {request_id} failed: {req['error']}")
                self._dispatch_next_locked()
                return

            temp_output = Path(result["temp_output"])
            if not temp_output.exists():
                req["status"] = "failed"
                req["updated_at"] = _utc_now()
                req["finished_at"] = _utc_now()
                req["error"] = "icon output missing"
                self._active_by_user.pop(username, None)
                self._dispatch_next_locked()
                return
            if temp_output.suffix.lower() != ".png":
                req["status"] = "failed"
                req["updated_at"] = _utc_now()
                req["finished_at"] = _utc_now()
                req["error"] = "icon output must be png"
                self._active_by_user.pop(username, None)
                self._dispatch_next_locked()
                return
            icons_dir = _ensure_icons_dir(username)
            icon_id = f"thing_icon_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{request_id[-6:]}.png"
            final_path = icons_dir / icon_id
            try:
                shutil.move(str(temp_output), str(final_path))
            except OSError as err:
                req["status"] = "failed"
                req["updated_at"] = _utc_now()
                req["finished_at"] = _utc_now()
                req["error"] = f"failed to persist icon: {err}"
                self._active_by_user.pop(username, None)
                self._dispatch_next_locked()
                return

            req["status"] = "done"
            req["updated_at"] = _utc_now()
            req["finished_at"] = _utc_now()
            rel = icon_rel_path(icon_id)
            req["icon_id"] = icon_id
            req["icon_path"] = rel
            req["icon_url"] = icon_url(username, rel)
            self._active_by_user.pop(username, None)
            print(f"object-editor: request {request_id} done -> {icon_id}")
            self._dispatch_next_locked()

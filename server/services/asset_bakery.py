"""Admin Asset Bakery service: discover, edit, bake, and postprocess bake.json assets.

Bake task files live under ``data/``, ``worlds/``, ``client/``, and ``mods/``.
Each file is either a JSON object with a ``tasks`` list (plus an optional
top-level ``simplify`` block for 3D assets) or a bare JSON task list. Every
task carries a ``label``, ``tool``, ``prompt``, ``output``, and ``args`` map.
Image tasks accept ``width``/``height``/``seed``/``steps``/``negative`` (plus
an optional ``template`` reference); 3D asset tasks accept ``seed``/``faces``
(plus ``template``/``aces``); sound tasks accept ``duration``/``seed``.
"""

from __future__ import annotations

import json
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from server.config import AppConfig, ConfigError, ensure_contained
from server.security import utc_now
from server.services.audit import AuditService

FEATURE_NAME = "asset-bakery"
BACKUP_ROOT = "asset-bakery"
SEED_MAX = 2**31 - 1
SEED_RE = re.compile(r'("seed"\s*:\s*)(-?\d+)')
LOG_LIMIT = 200_000

ALLOWED_TOOLS = frozenset({"image", "asset", "sound", "TEMPLATE"})
SIMPLIFY_STRATEGIES = frozenset({"auto", "decimate", "retopo"})
EXCLUDED_PARTS = frozenset(
    {".local", "attic", "releases", "node_modules", ".venv", "__pycache__", ".git"}
)
SEARCH_ROOTS = ("data", "worlds", "client", "mods")
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp"})
MODEL_SUFFIXES = frozenset({".glb", ".gltf"})
AUDIO_SUFFIXES = frozenset({".wav", ".mp3", ".ogg"})


class AssetBakeryError(ValueError):
    """Base class for Asset Bakery failures."""


class AssetBakeryNotFound(AssetBakeryError):
    """Raised when a bake file, task, or job cannot be found."""


class AssetBakeryValidationError(AssetBakeryError):
    """Raised when a candidate bake file fails validation."""


def _utc_stamp() -> str:
    return utc_now().strftime("%Y%m%dT%H%M%S%f")


def discover_bake_files(repo_root: Path) -> list[Path]:
    """Return every bake.json under the searchable roots, sorted by relpath."""

    found: list[Path] = []
    for root_name in SEARCH_ROOTS:
        root = repo_root / root_name
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("bake.json")):
            if EXCLUDED_PARTS.isdisjoint(path.parts):
                found.append(path)
    found.sort(key=lambda item: item.relative_to(repo_root).as_posix())
    return found


def resolve_bake_file(config: AppConfig, file_id: str) -> Path:
    """Resolve a repo-relative bake.json id to an absolute path."""

    normalized = str(file_id or "").strip().replace("\\", "/")
    if not normalized or normalized.startswith("/") or ".." in normalized.split("/"):
        raise AssetBakeryNotFound(f"Unknown bake file '{file_id}'.")
    try:
        candidate = ensure_contained(config.repo_root / normalized, config.repo_root, "bake")
    except ConfigError as exc:
        raise AssetBakeryNotFound(f"Unknown bake file '{file_id}'.") from exc
    if candidate.name != "bake.json" or not candidate.is_file():
        raise AssetBakeryNotFound(f"Unknown bake file '{file_id}'.")
    return candidate


def file_id_for(config: AppConfig, path: Path) -> str:
    """Return the repo-relative id for a bake.json path."""

    return path.relative_to(config.repo_root).as_posix()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_bytes().decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise AssetBakeryValidationError(f"{path.name}: invalid JSON: {exc}") from exc
    except OSError as exc:
        raise AssetBakeryNotFound(f"Cannot read {path.name}: {exc}") from exc


def split_document(data: Any) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    """Split raw JSON into (tasks, simplify, shape) with shape in {"object", "list"}."""

    if isinstance(data, list):
        if not all(isinstance(entry, dict) for entry in data):
            raise AssetBakeryValidationError("bake.json task list must contain objects.")
        return [dict(entry) for entry in data], {}, "list"
    if not isinstance(data, dict):
        raise AssetBakeryValidationError("bake.json must be an object with 'tasks' or a task list.")
    raw_tasks = data.get("tasks")
    if not isinstance(raw_tasks, list):
        raise AssetBakeryValidationError("bake.json must contain a 'tasks' list.")
    if not all(isinstance(entry, dict) for entry in raw_tasks):
        raise AssetBakeryValidationError("bake.json 'tasks' must contain objects.")
    simplify = data.get("simplify", {})
    if simplify is None:
        simplify = {}
    if not isinstance(simplify, dict):
        raise AssetBakeryValidationError("bake.json 'simplify' must be a mapping.")
    return [dict(entry) for entry in raw_tasks], dict(simplify), "object"


def _require_int(value: Any, label: str, *, minimum: int = 1, maximum: int = SEED_MAX) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AssetBakeryValidationError(f"{label} must be an integer.")
    if not minimum <= value <= maximum:
        raise AssetBakeryValidationError(f"{label} must be between {minimum} and {maximum}.")
    return value


def validate_simplify(simplify: Any, *, where: str) -> dict[str, Any]:
    """Validate a simplify block and return a normalized copy."""

    if simplify is None:
        return {}
    if not isinstance(simplify, dict):
        raise AssetBakeryValidationError(f"{where} 'simplify' must be a mapping.")
    cleaned = dict(simplify)
    strategy = cleaned.get("strategy", "auto")
    if strategy not in SIMPLIFY_STRATEGIES:
        raise AssetBakeryValidationError(
            f"{where} simplify.strategy must be one of {sorted(SIMPLIFY_STRATEGIES)}."
        )
    for key in ("target", "flat_target", "wall_target", "bake_resolution", "remesh_resolution"):
        if key in cleaned and cleaned[key] is not None:
            _require_int(cleaned[key], f"{where} simplify.{key}", minimum=1, maximum=4096)
    if "max_deviation" in cleaned and cleaned["max_deviation"] is not None:
        deviation = cleaned["max_deviation"]
        if isinstance(deviation, bool) or not isinstance(deviation, (int, float)):
            raise AssetBakeryValidationError(f"{where} simplify.max_deviation must be a number.")
        if not 0 < float(deviation) <= 1:
            raise AssetBakeryValidationError(f"{where} simplify.max_deviation must be in (0, 1].")
    return cleaned


def validate_task(entry: Any, *, index: int) -> dict[str, Any]:
    """Validate one bake task and return a normalized copy."""

    where = f"task #{index}"
    if not isinstance(entry, dict):
        raise AssetBakeryValidationError(f"{where} must be an object.")
    task = dict(entry)
    label = task.get("label")
    if not isinstance(label, str) or not label.strip():
        raise AssetBakeryValidationError(f"{where} needs a non-empty 'label'.")
    tool = task.get("tool")
    if tool not in ALLOWED_TOOLS:
        raise AssetBakeryValidationError(
            f"task '{label}' has unknown tool '{tool}'; expected one of {sorted(ALLOWED_TOOLS)}."
        )
    prompt = task.get("prompt", "")
    if tool != "TEMPLATE" and (not isinstance(prompt, str) or not prompt.strip()):
        raise AssetBakeryValidationError(f"task '{label}' needs a non-empty 'prompt'.")
    output = task.get("output", "")
    if tool == "TEMPLATE":
        if output and not isinstance(output, str):
            raise AssetBakeryValidationError(f"task '{label}' has an invalid 'output'.")
    elif not isinstance(output, str) or not output.strip():
        raise AssetBakeryValidationError(f"task '{label}' needs a non-empty 'output'.")
    else:
        task["output"] = normalize_output(output)
    args = task.get("args", {})
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise AssetBakeryValidationError(f"task '{label}' 'args' must be a mapping.")
    cleaned_args = dict(args)
    if "seed" in cleaned_args and cleaned_args["seed"] is not None:
        _require_int(cleaned_args["seed"], f"task '{label}' args.seed")
    for key in ("width", "height"):
        if key in cleaned_args and cleaned_args[key] is not None:
            _require_int(cleaned_args[key], f"task '{label}' args.{key}", minimum=16, maximum=4096)
    if "steps" in cleaned_args and cleaned_args["steps"] is not None:
        _require_int(cleaned_args["steps"], f"task '{label}' args.steps", minimum=1, maximum=150)
    if "faces" in cleaned_args and cleaned_args["faces"] is not None:
        _require_int(cleaned_args["faces"], f"task '{label}' args.faces", minimum=50, maximum=20000)
    if "duration" in cleaned_args and cleaned_args["duration"] is not None:
        duration = cleaned_args["duration"]
        if isinstance(duration, bool) or not isinstance(duration, (int, float)):
            raise AssetBakeryValidationError(f"task '{label}' args.duration must be a number.")
        if not 0 < float(duration) <= 600:
            raise AssetBakeryValidationError(f"task '{label}' args.duration must be in (0, 600].")
    for key in ("negative", "template"):
        if key in cleaned_args and cleaned_args[key] is not None and not isinstance(
            cleaned_args[key], str
        ):
            raise AssetBakeryValidationError(f"task '{label}' args.{key} must be a string.")
    if "aces" in cleaned_args and not isinstance(cleaned_args["aces"], bool):
        raise AssetBakeryValidationError(f"task '{label}' args.aces must be a boolean.")
    task["args"] = cleaned_args
    if "simplify" in task and task["simplify"] is not None:
        task["simplify"] = validate_simplify(task["simplify"], where=f"task '{label}'")
    return task


def validate_document(tasks: Any, simplify: Any = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Validate tasks plus an optional file-level simplify block."""

    if not isinstance(tasks, list):
        raise AssetBakeryValidationError("'tasks' must be a list.")
    cleaned = [validate_task(entry, index=index) for index, entry in enumerate(tasks)]
    labels = [str(task["label"]) for task in cleaned]
    duplicates = sorted({label for label in labels if labels.count(label) > 1})
    if duplicates:
        raise AssetBakeryValidationError(f"Duplicate task labels: {', '.join(duplicates)}.")
    return cleaned, validate_simplify(simplify or {}, where="file")


def _output_suffix_hint(output: str) -> str:
    for marker in ("data/", "worlds/", "client/", "mods/"):
        index = output.replace("\\", "/").find(marker)
        if index >= 0:
            return output.replace("\\", "/")[index:]
    return ""


def normalize_output(output: object) -> str:
    """Return a repo-relative posix path for a task output value.

    Bake files historically stored absolute developer-machine paths
    (``C:/workspace/tinyrooms-noon/data/...``). Relative outputs resolve
    against the repo root when baking, so normalize any absolute or
    machine-specific value down to its repo-relative suffix. Values that
    do not map inside the repo are returned stripped but unchanged.
    """

    if not isinstance(output, str):
        return output if output == "" else str(output)
    text = output.strip().replace("\\", "/")
    hint = _output_suffix_hint(text)
    if hint:
        return hint
    return output.strip()


def resolve_output_local(config: AppConfig, output: str) -> Path | None:
    """Map a task output string to a local path under the repo, if possible."""

    if not isinstance(output, str) or not output.strip():
        return None
    text = output.strip().replace("\\", "/")
    hint = _output_suffix_hint(text)
    if hint:
        try:
            return ensure_contained(config.repo_root / hint, config.repo_root, "output")
        except (ConfigError, OSError):
            return None
    candidate = Path(output.strip())
    if not candidate.is_absolute():
        candidate = config.repo_root / candidate
    try:
        return ensure_contained(candidate.resolve(), config.repo_root.resolve(), "output")
    except (ConfigError, OSError):
        return None


def preview_url_for(config: AppConfig, output: str) -> str:
    """Map a task output to a servable browser URL, or empty when unmappable."""

    local = resolve_output_local(config, output)
    if local is None:
        return ""
    try:
        rel = local.relative_to(config.repo_root.resolve()).as_posix()
    except ValueError:
        return ""
    parts = rel.split("/")
    if rel.startswith("client/app/"):
        return "/app/" + "/".join(parts[2:])
    if parts[0] == "data" and len(parts) >= 3 and parts[1] == "propsets":
        return "/assets/propsets/" + "/".join(parts[2:])
    if parts[0] == "data" and len(parts) >= 3 and parts[1] == "cardsets":
        return "/assets/" + "/".join(parts[2:])
    if parts[0] == "data" and len(parts) >= 3 and parts[1] == "sounds":
        return "/assets/sounds/" + "/".join(parts[2:])
    if parts[0] == "data" and len(parts) >= 3 and parts[1] == "fx":
        return "/assets/fx/" + "/".join(parts[2:])
    if parts[0] == "worlds" and len(parts) >= 4 and parts[2] in {
        "cards",
        "rooms",
        "props",
        "peeps",
    }:
        return "/assets/world/" + "/".join(parts[1:])
    return ""


def task_preview(config: AppConfig, task: dict[str, Any]) -> dict[str, Any]:
    """Describe a task output file for the UI preview pane."""

    output = str(task.get("output") or "")
    local = resolve_output_local(config, output)
    url = preview_url_for(config, output)
    suffix = Path(output).suffix.lower() if output else ""
    kind = "model" if suffix in MODEL_SUFFIXES else "audio" if suffix in AUDIO_SUFFIXES else "image"
    info: dict[str, Any] = {"url": url, "kind": kind, "suffix": suffix, "exists": False}
    if local is not None and local.is_file():
        stat = local.stat()
        info.update(
            {
                "exists": True,
                "size": stat.st_size,
                "mtime": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            }
        )
        if kind == "image":
            try:
                from PIL import Image

                with Image.open(local) as image:
                    info["width"] = image.width
                    info["height"] = image.height
                    info["mode"] = image.mode
            except Exception:  # noqa: BLE001 - preview metadata is best-effort
                pass
    return info


@dataclass(slots=True)
class BakeJob:
    """One background bake process invocation."""

    id: str
    file_id: str
    filters: tuple[str, ...] = ()
    force: bool = False
    dry_run: bool = False
    reseeded: int = 0
    status: str = "queued"
    exit_code: int | None = None
    log: str = ""
    created_at: str = field(default_factory=lambda: utc_now().isoformat())
    finished_at: str | None = None


_JOB_LOCK = threading.Lock()
_JOBS: dict[str, BakeJob] = {}


def list_jobs() -> list[BakeJob]:
    """Return background bake jobs, newest first."""

    with _JOB_LOCK:
        return sorted(_JOBS.values(), key=lambda job: job.created_at, reverse=True)[:50]


def get_job(job_id: str) -> BakeJob:
    """Return one background bake job or raise when unknown."""

    with _JOB_LOCK:
        job = _JOBS.get(str(job_id))
    if job is None:
        raise AssetBakeryNotFound(f"Unknown bake job '{job_id}'.")
    return job


def _append_log(job: BakeJob, text: str) -> None:
    with _JOB_LOCK:
        job.log = (job.log + text)[-LOG_LIMIT:]


def _finish_job(job: BakeJob, *, status: str, exit_code: int | None) -> None:
    with _JOB_LOCK:
        job.status = status
        job.exit_code = exit_code
        job.finished_at = utc_now().isoformat()


class AssetBakeryService:
    """Discover, validate, bake, and postprocess bake.json asset tasks."""

    def __init__(
        self,
        config: AppConfig,
        audit: AuditService,
        *,
        bake_runner: Any | None = None,
    ) -> None:
        self._config = config
        self._audit = audit
        self._bake_runner = bake_runner

    # -- discovery ------------------------------------------------------

    def catalog(self) -> dict[str, Any]:
        """List every bake.json file with task counts and tool mix."""

        entries = []
        for path in discover_bake_files(self._config.repo_root):
            try:
                tasks, simplify, _shape = split_document(_read_json(path))
            except AssetBakeryError:
                tasks, simplify = [], {}
            tools: dict[str, int] = {}
            for task in tasks:
                tools[str(task.get("tool"))] = tools.get(str(task.get("tool")), 0) + 1
            entries.append(
                {
                    "id": file_id_for(self._config, path),
                    "tasks": len(tasks),
                    "tools": tools,
                    "has_simplify": bool(simplify),
                }
            )
        return {"files": entries, "count": len(entries)}

    def load_file(self, file_id: str) -> dict[str, Any]:
        """Load one bake.json with per-task output stats for editing."""

        path = resolve_bake_file(self._config, file_id)
        tasks, simplify, _shape = split_document(_read_json(path))
        enriched = []
        for index, task in enumerate(tasks):
            try:
                cleaned = validate_task(task, index=index)
            except AssetBakeryValidationError:
                cleaned = dict(task)
            enriched.append({**cleaned, "_preview": task_preview(self._config, cleaned)})
        try:
            cleaned_simplify = validate_simplify(simplify, where="file")
        except AssetBakeryValidationError:
            cleaned_simplify = dict(simplify) if isinstance(simplify, dict) else {}
        return {
            "id": file_id_for(self._config, path),
            "tasks": enriched,
            "simplify": cleaned_simplify,
            "count": len(enriched),
        }

    # -- editing --------------------------------------------------------

    def save_file(
        self,
        file_id: str,
        tasks: Any,
        simplify: Any = None,
        *,
        actor_id: str,
    ) -> dict[str, Any]:
        """Validate and atomically rewrite one bake.json file."""

        path = resolve_bake_file(self._config, file_id)
        original = _read_json(path)
        _tasks, _simplify, shape = split_document(original)
        cleaned_tasks, cleaned_simplify = validate_document(tasks, simplify)
        for task in cleaned_tasks:
            output = str(task.get("output") or "")
            if output and resolve_output_local(self._config, output) is None:
                raise AssetBakeryValidationError(
                    f"task '{task.get('label')}' output escapes the repository."
                )
        if shape == "list" and not cleaned_simplify:
            payload: Any = cleaned_tasks
        elif isinstance(original, dict):
            payload = dict(original)
            payload["tasks"] = cleaned_tasks
            if cleaned_simplify:
                payload["simplify"] = cleaned_simplify
            else:
                payload.pop("simplify", None)
        else:
            payload = {"tasks": cleaned_tasks}
            if cleaned_simplify:
                payload = {"simplify": cleaned_simplify, "tasks": cleaned_tasks}
        backup = self._backup(path, file_id_for(self._config, path))
        self._atomic_write(path, payload)
        self._audit.safe_record(
            actor_id,
            "asset_bakery.save",
            file_id_for(self._config, path),
            "ok",
            {"tasks": len(cleaned_tasks), "backup": backup.name if backup else ""},
        )
        return self.load_file(file_id)

    def reseed_file(self, file_id: str, *, actor_id: str, dry_run: bool = False) -> dict[str, Any]:
        """Assign fresh random seeds to every pinned integer seed in a file."""

        path = resolve_bake_file(self._config, file_id)
        text = path.read_bytes().decode("utf-8")
        data = json.loads(text)
        tasks, _simplify, _shape = split_document(data)
        pinned = sum(
            1
            for task in tasks
            if isinstance(task.get("args"), dict)
            and isinstance(task["args"].get("seed"), int)
            and not isinstance(task["args"].get("seed"), bool)
        )
        if not pinned:
            return {"id": file_id_for(self._config, path), "reseeded": 0, "changes": []}
        matches = list(SEED_RE.finditer(text))
        if len(matches) != pinned:
            raise AssetBakeryValidationError(
                f"Found {len(matches)} seed entries but {pinned} integer seeds; refusing to rewrite."
            )
        changes: list[list[int]] = []
        parts: list[str] = []
        last = 0
        for match in matches:
            old = int(match.group(2))
            new = random.randint(1, SEED_MAX)
            while new == old:
                new = random.randint(1, SEED_MAX)
            changes.append([old, new])
            parts.append(text[last:match.start()])
            parts.append(match.group(1) + str(new))
            last = match.end()
        parts.append(text[last:])
        if not dry_run:
            backup = self._backup(path, file_id_for(self._config, path))
            path.write_bytes("".join(parts).encode("utf-8"))
            self._audit.safe_record(
                actor_id,
                "asset_bakery.reseed",
                file_id_for(self._config, path),
                "ok",
                {"reseeded": len(changes), "backup": backup.name if backup else ""},
            )
        return {"id": file_id_for(self._config, path), "reseeded": len(changes), "changes": changes}

    # -- baking ----------------------------------------------------------

    def start_bake(
        self,
        file_id: str,
        *,
        actor_id: str,
        filters: list[str] | tuple[str, ...] = (),
        force: bool = False,
        dry_run: bool = False,
        reseed: bool = False,
    ) -> BakeJob:
        """Queue a background bake of one file, optionally reseeding first."""

        path = resolve_bake_file(self._config, file_id)
        normalized_filters = [str(item).strip() for item in (filters or []) if str(item).strip()]
        reseeded = 0
        if reseed and not dry_run:
            reseeded = int(self.reseed_file(file_id, actor_id=actor_id).get("reseeded", 0))
        job = BakeJob(
            id=uuid.uuid4().hex[:12],
            file_id=file_id_for(self._config, path),
            filters=tuple(normalized_filters),
            force=bool(force),
            dry_run=bool(dry_run),
            reseeded=reseeded,
        )
        with _JOB_LOCK:
            _JOBS[job.id] = job
        self._audit.safe_record(
            actor_id,
            "asset_bakery.bake",
            job.file_id,
            "queued",
            {"job": job.id, "filters": list(normalized_filters), "force": job.force},
        )
        thread = threading.Thread(
            target=self._run_bake_job,
            args=(job, actor_id),
            daemon=True,
        )
        thread.start()
        return job

    def _bake_command(self, job: BakeJob) -> list[str]:
        script = self._config.repo_root / "tools" / "bake_assets.py"
        command = [sys.executable, "-u", str(script), job.file_id]
        for pattern in job.filters:
            command += ["--filter", pattern]
        if job.force:
            command.append("--force")
        if job.dry_run:
            command.append("--dryrun")
        return command

    def _run_bake_job(self, job: BakeJob, actor_id: str) -> None:
        with _JOB_LOCK:
            job.status = "running"
        try:
            if self._bake_runner is not None:
                returncode, output = self._bake_runner(self._bake_command(job))
            else:
                completed = subprocess.run(
                    self._bake_command(job),
                    cwd=str(self._config.repo_root),
                    capture_output=True,
                    text=True,
                    timeout=3600,
                )
                returncode, output = completed.returncode, (completed.stdout or "") + (
                    completed.stderr or ""
                )
        except Exception as exc:  # noqa: BLE001 - surface runner failures on the job
            _append_log(job, f"\n[asset-bakery] bake runner failed: {exc}\n")
            _finish_job(job, status="error", exit_code=None)
            self._audit.safe_record(actor_id, "asset_bakery.bake", job.file_id, "error", {"job": job.id})
            return
        _append_log(job, output[-LOG_LIMIT:])
        _finish_job(job, status="done" if returncode == 0 else "error", exit_code=returncode)
        self._audit.safe_record(
            actor_id,
            "asset_bakery.bake",
            job.file_id,
            "done" if returncode == 0 else "error",
            {"job": job.id, "exit_code": returncode},
        )

    # -- postprocess ------------------------------------------------------

    def postprocess(
        self,
        file_id: str,
        label: str,
        operation: str,
        params: dict[str, Any] | None,
        *,
        actor_id: str,
    ) -> dict[str, Any]:
        """Apply a basic image edit to a baked task output."""

        from server.services.asset_postprocess import apply_operation

        path = resolve_bake_file(self._config, file_id)
        tasks, _simplify, _shape = split_document(_read_json(path))
        task = next((entry for entry in tasks if str(entry.get("label")) == str(label)), None)
        if task is None:
            raise AssetBakeryNotFound(f"Unknown task '{label}'.")
        output = str(task.get("output") or "")
        local = resolve_output_local(self._config, output)
        if local is None or not local.is_file():
            raise AssetBakeryNotFound(f"No baked output found for '{label}'.")
        suffix = local.suffix.lower()
        if suffix not in IMAGE_SUFFIXES:
            raise AssetBakeryValidationError(
                f"Postprocess editing supports image outputs; '{label}' is '{suffix or 'unknown'}'."
            )
        backup = self._backup(local, f"{file_id_for(self._config, path)}/{label}")
        result = apply_operation(local, operation, dict(params or {}))
        self._audit.safe_record(
            actor_id,
            f"asset_bakery.postprocess.{operation}",
            f"{file_id_for(self._config, path)}/{label}",
            "ok",
            {"backup": backup.name if backup else "", **{k: v for k, v in result.items() if k != 'preview'}},
        )
        return {"id": file_id_for(self._config, path), "label": label, **result}

    # -- filesystem -------------------------------------------------------

    def _backup(self, path: Path, label: str) -> Path | None:
        if not path.is_file():
            return None
        safe = re.sub(r"[^A-Za-z0-9._-]+", "-", label).strip("-") or "bake"
        target_dir = self._config.revisions_path / BACKUP_ROOT / safe / _utc_stamp()
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / path.name
        shutil.copy2(path, target)
        return target

    @staticmethod
    def _atomic_write(path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)


def job_payload(job: BakeJob) -> dict[str, Any]:
    """Serialize a bake job for the API."""

    return {
        "id": job.id,
        "file_id": job.file_id,
        "filters": list(job.filters),
        "force": job.force,
        "dry_run": job.dry_run,
        "reseeded": job.reseeded,
        "status": job.status,
        "exit_code": job.exit_code,
        "log": job.log[-8000:],
        "created_at": job.created_at,
        "finished_at": job.finished_at,
    }

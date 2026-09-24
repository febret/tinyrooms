"""Server-side world draft, validation, and publish service."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import os
import shutil
import tempfile

from server.config import AppConfig
from server.content.bundle import WorldBundle, load_world_bundle
from server.content.cards import load_card_catalog
from server.content.common import ContentError
from server.content.draft import (
    DRAFT_FORMAT_VERSION,
    DraftInfo,
    DraftIssue,
    DraftReferences,
    build_draft,
    draft_yaml_files,
    validate_structure,
    yaml_file_names,
)
from server.content.recipes import load_recipes
from server.content.tasks import load_task_definitions
from server.content.activities import load_activity_definitions
from server.content.staging import stage_world
from server.security import utc_now
from server.services.audit import AuditService
from server.services.world_reconcile import (
    DestructiveChange,
    affected_rooms,
    destructive_changes,
    reconcile,
)
from server.state.migrations import DatabaseHub
from server.state.world_state import WorldStateRepository


PUBLISHED_REVISION_KEY = "published_revision"
PUBLISHED_AT_KEY = "published_at"
PUBLISHED_BY_KEY = "published_by"

DRAFT_FILE_SUFFIX = ".json"


class WorldEditorError(ValueError):
    """Base class for World Editor failures."""


class DraftValidationError(WorldEditorError):
    """Raised when a draft fails structural validation."""

    def __init__(self, issues: list[DraftIssue]) -> None:
        super().__init__("The draft is not valid.")
        self.issues = issues


class PublishValidationError(WorldEditorError):
    """Raised when a publish fails full loader validation."""

    def __init__(self, errors: list[DraftIssue]) -> None:
        super().__init__("The world did not validate; nothing was written.")
        self.errors = errors


class PublishConfirmationRequired(WorldEditorError):
    """Raised when a publish has destructive changes that need confirmation."""

    def __init__(self, changes: list[DestructiveChange]) -> None:
        rooms = affected_rooms(changes)
        listed = ", ".join(rooms) if rooms else "no rooms"
        super().__init__(
            f"Saving will apply destructive changes to {len(rooms)} room(s): {listed}."
        )
        self.changes = changes
        self.rooms = rooms


@dataclass(slots=True)
class ValidationReport:
    """Result of validating a draft against the real loaders."""

    valid: bool
    errors: list[DraftIssue]

    def to_payload(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""

        return {"valid": self.valid, "errors": [issue.to_payload() for issue in self.errors]}


@dataclass(slots=True)
class PublishResult:
    """Summary of a successful publish."""

    revision: int
    changed_files: tuple[str, ...]
    backup_path: Path
    destructive_changes: tuple[DestructiveChange, ...]
    reconciled: object | None = None

    def to_payload(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""

        payload: dict[str, object] = {
            "revision": self.revision,
            "changed_files": list(self.changed_files),
            "backup_path": self.backup_path.name,
            "destructive_changes": [change.to_payload() for change in self.destructive_changes],
            "affected_rooms": affected_rooms(list(self.destructive_changes)),
        }
        if self.reconciled is not None:
            payload["reconciled"] = self.reconciled.to_payload()
        return payload


class WorldEditorService:
    """Draft lifecycle, validation, and atomic publish for one world."""

    def __init__(
        self,
        config: AppConfig,
        hub: DatabaseHub,
        world_state: WorldStateRepository,
        audit: AuditService,
        loaded_mods: object | None = None,
    ) -> None:
        self._config = config
        self._hub = hub
        self._world_state = world_state
        self._audit = audit
        self._loaded_mods = loaded_mods
        self._world_key = config.world_path.name

    @property
    def world_key(self) -> str:
        """Return the stable draft/revision key for the world."""

        return self._world_key

    def draft_path(self) -> Path:
        """Return the JSON draft file path."""

        return self._config.drafts_path / f"{self._world_key}{DRAFT_FILE_SUFFIX}"

    def load_draft(self) -> dict[str, object]:
        """Return the saved draft, or a fresh one built from published files."""

        path = self.draft_path()
        if path.is_file():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                payload = None
            if isinstance(payload, dict):
                return payload
        draft = build_draft(self._config.world_path, world_id=self._world_key)
        draft["base_published_revision"] = self._world_state.read_world_meta(PUBLISHED_REVISION_KEY)
        return draft

    def save_draft(self, draft: dict[str, object]) -> DraftInfo:
        """Persist a draft after structural validation; never touch the world."""

        references = self._references(draft)
        issues = validate_structure(draft, references)
        if issues:
            raise DraftValidationError(issues)
        previous_revision = 0
        path = self.draft_path()
        if path.is_file():
            try:
                previous = json.loads(path.read_text(encoding="utf-8"))
                previous_revision = int(previous.get("draft_revision", 0))
            except (ValueError, OSError, TypeError):
                previous_revision = 0
        draft = dict(draft)
        draft["format_version"] = DRAFT_FORMAT_VERSION
        draft["world_id"] = self._world_key
        draft["draft_revision"] = previous_revision + 1
        draft["base_published_revision"] = self._world_state.read_world_meta(PUBLISHED_REVISION_KEY)
        draft["updated_at"] = utc_now().isoformat()
        self._atomic_write_json(path, draft)
        return self._draft_info(draft)

    def discard_draft(self) -> bool:
        """Delete the saved draft, returning whether one existed."""

        path = self.draft_path()
        if path.is_file():
            path.unlink()
            return True
        return False

    def validate(self, draft: dict[str, object]) -> ValidationReport:
        """Validate a draft structurally and against the real content loaders."""

        errors = list(validate_structure(draft, self._references(draft)))
        errors.extend(self._loader_errors(draft))
        return ValidationReport(valid=not errors, errors=errors)

    def publish(
        self,
        draft: dict[str, object],
        *,
        actor_account_id: str,
        confirm: bool = False,
    ) -> PublishResult:
        """Validate, confirm, back up, and atomically write a draft to the world."""

        report = self.validate(draft)
        if not report.valid:
            self._audit.safe_record(
                actor_account_id,
                "world.publish",
                self._world_key,
                "rejected",
                {"reason": "validation", "errors": [issue.to_payload() for issue in report.errors]},
            )
            raise PublishValidationError(report.errors)

        staged = self._stage(draft)
        try:
            old_bundle = load_world_bundle(self._config, self._loaded_mods, self._config.world_path)
            new_bundle = load_world_bundle(self._config, self._loaded_mods, staged)
            changes = destructive_changes(old_bundle.world, new_bundle.world)
            if changes and not confirm:
                self._audit.safe_record(
                    actor_account_id,
                    "world.publish",
                    self._world_key,
                    "rejected",
                    {"reason": "confirmation", "rooms": affected_rooms(changes)},
                )
                raise PublishConfirmationRequired(changes)
            revision = self._next_revision()
            backup_path = self._backup(revision, actor_account_id, staged)
            changed_files = self._commit(staged, backup_path)
            reconciled = reconcile(
                self._hub,
                self._world_state,
                old_bundle.world,
                new_bundle.world,
            )
            self._record_publish(revision, actor_account_id, changed_files)
        finally:
            shutil.rmtree(staged, ignore_errors=True)

        self._audit.safe_record(
            actor_account_id,
            "world.publish",
            self._world_key,
            "ok",
            {
                "revision": revision,
                "changed_files": list(changed_files),
                "removed_card_stacks": reconciled.removed_card_stacks,
            },
        )
        return PublishResult(
            revision=revision,
            changed_files=tuple(changed_files),
            backup_path=backup_path,
            destructive_changes=tuple(changes),
            reconciled=reconciled,
        )

    def _draft_info(self, draft: dict[str, object]) -> DraftInfo:
        return DraftInfo(
            world_id=str(draft.get("world_id", self._world_key)),
            draft_revision=int(draft.get("draft_revision", 0)),
            base_published_revision=draft.get("base_published_revision"),
            updated_at=draft.get("updated_at"),
            sections=tuple(
                name for name, payload in draft.items() if isinstance(payload, dict) and name != "world"
            ),
        )

    def _references(self, draft: dict[str, object]) -> DraftReferences:
        bundle = load_world_bundle(self._config, self._loaded_mods, self._config.world_path)
        draft_props = draft.get("props") if isinstance(draft.get("props"), dict) else {}
        draft_recipes = draft.get("recipes") if isinstance(draft.get("recipes"), dict) else {}
        draft_activities = draft.get("activities") if isinstance(draft.get("activities"), dict) else {}
        return DraftReferences(
            card_ids=frozenset(bundle.catalog.cards),
            prop_ids=frozenset(bundle.world.props) | frozenset(draft_props),
            activity_ids=frozenset(bundle.world.activities) | frozenset(draft_activities),
            recipe_ids=frozenset(bundle.world.recipes) | frozenset(draft_recipes),
        )

    def _loader_errors(self, draft: dict[str, object]) -> list[DraftIssue]:
        staged = self._stage(draft)
        errors: list[DraftIssue] = []
        try:
            try:
                catalog = load_card_catalog(self._config.cardsets_path, staged)
            except (ContentError, OSError) as exc:
                return [DraftIssue(path="cards", message=str(exc))]
            try:
                load_recipes(staged, set(catalog.cards))
            except (ContentError, OSError) as exc:
                errors.append(DraftIssue(path="recipes", message=str(exc)))
            try:
                load_task_definitions(staged, set(catalog.cards))
            except (ContentError, OSError) as exc:
                errors.append(DraftIssue(path="tasks", message=str(exc)))
            try:
                load_activity_definitions(
                    staged / "activities.yaml",
                    source=self._world_key,
                )
            except (ContentError, OSError) as exc:
                errors.append(DraftIssue(path="activities", message=str(exc)))
            try:
                load_world_bundle(self._config, self._loaded_mods, staged)
            except (ContentError, OSError) as exc:
                errors.append(DraftIssue(path="world", message=str(exc)))
        finally:
            shutil.rmtree(staged, ignore_errors=True)
        return errors

    def _stage(self, draft: dict[str, object]) -> Path:
        self._config.drafts_path.mkdir(parents=True, exist_ok=True)
        staged = Path(tempfile.mkdtemp(prefix="draft-", dir=self._config.drafts_path))
        stage_world(self._config.world_path, staged, draft_yaml_files(draft))
        return staged

    def _next_revision(self) -> int:
        stored = self._world_state.read_world_meta(PUBLISHED_REVISION_KEY)
        try:
            return int(stored) + 1 if stored else 1
        except ValueError:
            return 1

    def _backup(self, revision: int, actor_account_id: str, staged: Path) -> Path:
        backup_path = self._config.revisions_path / self._world_key / str(revision)
        if backup_path.exists():
            shutil.rmtree(backup_path)
        backup_path.mkdir(parents=True, exist_ok=True)
        previous = self._world_state.read_world_meta(PUBLISHED_REVISION_KEY)
        for relative_name in yaml_file_names():
            source = self._config.world_path / relative_name
            if source.is_file():
                target = backup_path / relative_name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        manifest = {
            "world_id": self._world_key,
            "revision": revision,
            "previous_revision": previous,
            "published_by": actor_account_id,
            "published_at": utc_now().isoformat(),
            "files": list(yaml_file_names()),
        }
        (backup_path / "manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        return backup_path

    def _commit(self, staged: Path, backup_path: Path) -> list[str]:
        replaced: list[str] = []
        try:
            for relative_name in yaml_file_names():
                source = staged / relative_name
                if not source.is_file():
                    continue
                target = self._config.world_path / relative_name
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(source, target)
                replaced.append(relative_name)
        except OSError:
            self._restore(backup_path, replaced)
            raise
        return replaced

    def _restore(self, backup_path: Path, replaced: list[str]) -> None:
        for relative_name in replaced:
            source = backup_path / relative_name
            if not source.is_file():
                continue
            target = self._config.world_path / relative_name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    def _record_publish(self, revision: int, actor_account_id: str, changed_files: list[str]) -> None:
        with self._hub.transaction() as connection:
            self._world_state.write_world_meta(connection, PUBLISHED_REVISION_KEY, str(revision))
            self._world_state.write_world_meta(connection, PUBLISHED_AT_KEY, utc_now().isoformat())
            self._world_state.write_world_meta(connection, PUBLISHED_BY_KEY, actor_account_id)

    @staticmethod
    def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=False), encoding="utf-8")
        os.replace(temporary, path)

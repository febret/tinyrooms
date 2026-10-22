"""Curated decorative prop showcase for the public player-entry page.

The entry page is served before a destination world exists, so Mission Control
serves a small, hand-picked cross-section of bundled/shared props directly. The
manifest is public and read-only: it exposes only labels, sizes, and media URLs,
never filesystem paths or world state.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse

from server.config import ConfigError, ensure_contained
from server.content.common import ContentError
from server.content.worlds import PropDefinition, load_propset
from server.mission_control.config import MCConfig


LOGGER = logging.getLogger("tinyrooms.mc")

SHOWCASE_PREFIX = "/mission-control/showcase"
MODEL_CACHE_CONTROL = "public, max-age=604800"
MANIFEST_CACHE_CONTROL = "public, max-age=300"


@dataclass(frozen=True, slots=True)
class ShowcasePick:
    """One hand-placed prop in the entry-page diorama."""

    propset: str
    prop_id: str
    col: int
    row: int
    priority: int = 0


# A deliberately varied, cheerful slice of the catalog: nature, home, arcade,
# whimsy, and rococo. Slots compose a 5x5 isometric grid (row 0 is the back).
CURATED_PROPS = (
    ShowcasePick("arbor-base", "cherry-blossom-tree", 2, 0),
    ShowcasePick("rococo-base", "gilded-birdcage", 0, 0, priority=1),
    ShowcasePick("arbor-base", "sunflower-stalk", 4, 0, priority=1),
    ShowcasePick("arbor-base", "crystal-cluster", 1, 1),
    ShowcasePick("leet-base", "arcade-cabinet", 3, 1),
    ShowcasePick("base", "mushroom-table-lamp", 2, 2),
    ShowcasePick("base", "teal-egg-chair", 0, 2, priority=1),
    ShowcasePick("potty-base", "rocket-toilet", 4, 2, priority=1),
    ShowcasePick("yokkmok", "aalto-stool", 1, 3, priority=2),
    ShowcasePick("yokkmok", "koivu-dining-chair", 3, 3, priority=2),
)


class EntryShowcase:
    """Resolve and cache the curated showcase manifest for one MC process."""

    def __init__(self, config: MCConfig) -> None:
        self._config = config
        self._manifest: dict[str, object] | None = None
        self._allowed_models: set[tuple[str, str]] = set()

    @property
    def propset_roots(self) -> tuple[Path, ...]:
        """Return shared then bundled propset roots, when they exist."""

        roots: list[Path] = []
        for root in (self._config.shared_propsets_root, self._config.repo_root / "data" / "propsets"):
            if root.is_dir():
                roots.append(root)
        return tuple(roots)

    def _propset_path(self, propset: str) -> Path | None:
        for root in self.propset_roots:
            candidate = root / propset
            if (candidate / "props.yaml").is_file():
                return candidate
        return None

    def manifest(self) -> dict[str, object]:
        """Return the cached manifest payload, building it on first use."""

        if self._manifest is None:
            self._manifest = self._build()
        return self._manifest

    @property
    def allowed_models(self) -> set[tuple[str, str]]:
        """Return the manifest's allowlisted ``(propset, filename)`` models."""

        self.manifest()
        return self._allowed_models

    def _build(self) -> dict[str, object]:
        loaded: dict[str, dict[str, PropDefinition]] = {}
        props: list[dict[str, object]] = []
        for pick in CURATED_PROPS:
            try:
                definitions = loaded.get(pick.propset)
                if definitions is None:
                    propset_path = self._propset_path(pick.propset)
                    if propset_path is None:
                        continue
                    definitions = load_propset(propset_path)
                    loaded[pick.propset] = definitions
                definition = definitions.get(pick.prop_id)
                if definition is None or definition.render_kind != "model" or not definition.model_name:
                    continue
                model_name = quote(definition.model_name, safe="")
                # The entry collage deliberately previews locked marketplace props.
                self._allowed_models.add((definition.source, definition.model_name))
                props.append(
                    {
                        "id": definition.id,
                        "label": definition.label,
                        "propset": definition.source,
                        "model_url": f"{SHOWCASE_PREFIX}/{definition.source}/{model_name}",
                        "scale": round(float(definition.scale), 3),
                        "slot": [pick.col, pick.row],
                        "priority": pick.priority,
                    }
                )
            except (ContentError, OSError) as exc:
                LOGGER.warning("entry.showcase_propset_skipped propset=%s error=%s", pick.propset, exc)
                continue
        props.sort(key=lambda item: (int(item["priority"]), str(item["id"])))
        return {"ok": True, "props": props}


router = APIRouter()


def showcase_for(request: Request) -> EntryShowcase:
    """Return the entry showcase service from the app runtime."""

    return request.app.state.mc.entry_showcase


@router.get("/api/entry/showcase")
async def showcase_manifest(request: Request) -> Response:
    """Return the public decorative prop manifest for the entry page."""

    try:
        payload = showcase_for(request).manifest()
    except Exception:  # noqa: BLE001 - decorative content must never break login
        LOGGER.exception("entry.showcase_manifest_failed")
        payload = {"ok": True, "props": []}
    return JSONResponse(payload, headers={"Cache-Control": MANIFEST_CACHE_CONTROL})


@router.get(f"{SHOWCASE_PREFIX}/{{propset}}/{{filename}}")
async def showcase_model(request: Request, propset: str, filename: str) -> Response:
    """Serve one curated GLB, restricted to contained propset directories."""

    if not filename.lower().endswith(".glb"):
        raise HTTPException(status_code=404, detail="Not found.")
    showcase = showcase_for(request)
    if (propset, filename) not in showcase.allowed_models:
        raise HTTPException(status_code=404, detail="Showcase model not found.")
    for root in showcase.propset_roots:
        try:
            candidate = ensure_contained(root / propset / filename, root, "showcase")
        except ConfigError as exc:
            raise HTTPException(status_code=404, detail="Not found.") from exc
        if candidate.is_file():
            return FileResponse(
                candidate,
                media_type="model/gltf-binary",
                headers={"Cache-Control": MODEL_CACHE_CONTROL},
            )
    raise HTTPException(status_code=404, detail="Showcase model not found.")

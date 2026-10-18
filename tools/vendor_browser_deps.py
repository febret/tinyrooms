from __future__ import annotations

import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NODE_MODULES = ROOT / "node_modules"
TARGET = ROOT / "app" / "vendor"
THREE = NODE_MODULES / "three"
DRAWFLOW = NODE_MODULES / "drawflow"

FILES = {
    THREE / "build" / "three.module.js": TARGET / "three" / "three.module.js",
    THREE / "build" / "three.core.js": TARGET / "three" / "three.core.js",
    THREE / "examples" / "jsm" / "controls" / "OrbitControls.js": TARGET / "three" / "examples" / "jsm" / "controls" / "OrbitControls.js",
    THREE / "examples" / "jsm" / "loaders" / "GLTFLoader.js": TARGET / "three" / "examples" / "jsm" / "loaders" / "GLTFLoader.js",
    THREE / "examples" / "jsm" / "loaders" / "FontLoader.js": TARGET / "three" / "examples" / "jsm" / "loaders" / "FontLoader.js",
    THREE / "examples" / "jsm" / "geometries" / "TextGeometry.js": TARGET / "three" / "examples" / "jsm" / "geometries" / "TextGeometry.js",
    THREE / "examples" / "fonts" / "LICENSE": TARGET / "three" / "examples" / "fonts" / "LICENSE",
    THREE / "examples" / "jsm" / "utils" / "BufferGeometryUtils.js": TARGET / "three" / "examples" / "jsm" / "utils" / "BufferGeometryUtils.js",
    DRAWFLOW / "dist" / "drawflow.min.js": TARGET / "drawflow" / "drawflow.min.js",
    DRAWFLOW / "dist" / "drawflow.min.css": TARGET / "drawflow" / "drawflow.min.css",
    DRAWFLOW / "LICENSE": TARGET / "drawflow" / "LICENSE",
}

for font in ("helvetiker_regular", "optimer_regular", "gentilis_regular"):
    filename = f"{font}.typeface.json"
    FILES[THREE / "examples" / "fonts" / filename] = TARGET / "three" / "examples" / "fonts" / filename


def main() -> None:
    for package in (THREE, DRAWFLOW):
        if not package.exists():
            raise SystemExit(
                f"Missing node_modules\\{package.name}. Run `npm install` before vendoring browser dependencies."
            )
    for source, destination in FILES.items():
        if not source.exists():
            raise SystemExit(f"Missing expected dependency file: {source}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        print(f"Vendored {source.relative_to(ROOT)} -> {destination.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

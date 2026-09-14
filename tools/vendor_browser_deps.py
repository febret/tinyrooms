from __future__ import annotations

import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NODE_MODULES = ROOT / "node_modules" / "three"
TARGET = ROOT / "app" / "vendor" / "three"

FILES = {
    NODE_MODULES / "build" / "three.module.js": TARGET / "three.module.js",
    NODE_MODULES / "build" / "three.core.js": TARGET / "three.core.js",
    NODE_MODULES / "examples" / "jsm" / "controls" / "OrbitControls.js": TARGET / "examples" / "jsm" / "controls" / "OrbitControls.js",
    NODE_MODULES / "examples" / "jsm" / "loaders" / "GLTFLoader.js": TARGET / "examples" / "jsm" / "loaders" / "GLTFLoader.js",
    NODE_MODULES / "examples" / "jsm" / "utils" / "BufferGeometryUtils.js": TARGET / "examples" / "jsm" / "utils" / "BufferGeometryUtils.js",
}


def main() -> None:
    if not NODE_MODULES.exists():
        raise SystemExit(
            "Missing node_modules\\three. Run `npm install` before vendoring browser dependencies."
        )
    for source, destination in FILES.items():
        if not source.exists():
            raise SystemExit(f"Missing expected dependency file: {source}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        print(f"Vendored {source.relative_to(ROOT)} -> {destination.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

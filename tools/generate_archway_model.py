"""Generate the infinite-bedrooms archway model as a deterministic GLB.

Run from the repository root:

    python -m tools.generate_archway_model

The output is written to ``mods/infinite-bedrooms/props/archway.glb`` and uses
only the Python standard library so the asset can be rebuilt reproducibly.
"""

from __future__ import annotations

import json
import math
import struct
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = REPO_ROOT / "mods" / "infinite-bedrooms" / "props" / "archway.glb"

PILLAR_WIDTH = 0.25
PILLAR_DEPTH = 0.3
PILLAR_HEIGHT = 1.2
SPAN = 1.0
ARCH_SEGMENTS = 14

INNER_RADIUS = SPAN / 2.0
OUTER_RADIUS = INNER_RADIUS + PILLAR_WIDTH
HALF_DEPTH = PILLAR_DEPTH / 2.0


class MeshBuilder:
    """Accumulate flat-shaded triangles with per-face normals."""

    def __init__(self) -> None:
        self.positions: list[tuple[float, float, float]] = []
        self.normals: list[tuple[float, float, float]] = []
        self.indices: list[int] = []

    def add_quad(
        self,
        a: tuple[float, float, float],
        b: tuple[float, float, float],
        c: tuple[float, float, float],
        d: tuple[float, float, float],
    ) -> None:
        self.add_triangle(a, b, c)
        self.add_triangle(a, c, d)

    def add_triangle(
        self,
        a: tuple[float, float, float],
        b: tuple[float, float, float],
        c: tuple[float, float, float],
    ) -> None:
        normal = _face_normal(a, b, c)
        base = len(self.positions)
        for point in (a, b, c):
            self.positions.append(point)
            self.normals.append(normal)
        self.indices.extend((base, base + 1, base + 2))

    def add_box(
        self,
        x0: float,
        x1: float,
        y0: float,
        y1: float,
        z0: float,
        z1: float,
    ) -> None:
        self.add_quad((x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1))
        self.add_quad((x1, y0, z0), (x0, y0, z0), (x0, y1, z0), (x1, y1, z0))
        self.add_quad((x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0))
        self.add_quad((x1, y0, z1), (x1, y0, z0), (x1, y1, z0), (x1, y1, z1))
        self.add_quad((x0, y1, z1), (x1, y1, z1), (x1, y1, z0), (x0, y1, z0))
        self.add_quad((x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1))


def _face_normal(
    a: tuple[float, float, float],
    b: tuple[float, float, float],
    c: tuple[float, float, float],
) -> tuple[float, float, float]:
    ux, uy, uz = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    vx, vy, vz = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    nx, ny, nz = (uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx)
    length = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
    return (nx / length, ny / length, nz / length)


def _arch_point(radius: float, angle: float, z: float) -> tuple[float, float, float]:
    return (radius * math.cos(angle), PILLAR_HEIGHT + radius * math.sin(angle), z)


def build_mesh() -> MeshBuilder:
    """Build the archway geometry."""

    builder = MeshBuilder()
    right_inner = INNER_RADIUS
    right_outer = OUTER_RADIUS
    left_inner = -INNER_RADIUS
    left_outer = -OUTER_RADIUS

    builder.add_box(right_inner, right_outer, 0.0, PILLAR_HEIGHT, -HALF_DEPTH, HALF_DEPTH)
    builder.add_box(left_outer, left_inner, 0.0, PILLAR_HEIGHT, -HALF_DEPTH, HALF_DEPTH)

    for segment in range(ARCH_SEGMENTS):
        angle0 = math.pi * segment / ARCH_SEGMENTS
        angle1 = math.pi * (segment + 1) / ARCH_SEGMENTS
        inner_front0 = _arch_point(INNER_RADIUS, angle0, -HALF_DEPTH)
        inner_front1 = _arch_point(INNER_RADIUS, angle1, -HALF_DEPTH)
        inner_back0 = _arch_point(INNER_RADIUS, angle0, HALF_DEPTH)
        inner_back1 = _arch_point(INNER_RADIUS, angle1, HALF_DEPTH)
        outer_front0 = _arch_point(OUTER_RADIUS, angle0, -HALF_DEPTH)
        outer_front1 = _arch_point(OUTER_RADIUS, angle1, -HALF_DEPTH)
        outer_back0 = _arch_point(OUTER_RADIUS, angle0, HALF_DEPTH)
        outer_back1 = _arch_point(OUTER_RADIUS, angle1, HALF_DEPTH)

        builder.add_quad(outer_front0, outer_front1, outer_back1, outer_back0)
        builder.add_quad(inner_front1, inner_front0, inner_back0, inner_back1)
        builder.add_quad(inner_front0, inner_front1, outer_front1, outer_front0)
        builder.add_quad(inner_back1, inner_back0, outer_back0, outer_back1)

    builder.add_quad(
        _arch_point(INNER_RADIUS, 0.0, -HALF_DEPTH),
        _arch_point(INNER_RADIUS, 0.0, HALF_DEPTH),
        _arch_point(OUTER_RADIUS, 0.0, HALF_DEPTH),
        _arch_point(OUTER_RADIUS, 0.0, -HALF_DEPTH),
    )
    builder.add_quad(
        _arch_point(INNER_RADIUS, math.pi, -HALF_DEPTH),
        _arch_point(OUTER_RADIUS, math.pi, -HALF_DEPTH),
        _arch_point(OUTER_RADIUS, math.pi, HALF_DEPTH),
        _arch_point(INNER_RADIUS, math.pi, HALF_DEPTH),
    )
    return builder


def _pad(data: bytes, multiple: int, fill: bytes) -> bytes:
    remainder = len(data) % multiple
    if remainder == 0:
        return data
    return data + fill * (multiple - remainder)


def build_glb(mesh: MeshBuilder) -> bytes:
    """Serialize the mesh as a binary glTF 2.0 asset."""

    positions = b"".join(struct.pack("<3f", *point) for point in mesh.positions)
    normals = b"".join(struct.pack("<3f", *normal) for normal in mesh.normals)
    indices = b"".join(struct.pack("<H", index) for index in mesh.indices)

    position_offset = 0
    normal_offset = position_offset + len(positions)
    index_offset = normal_offset + len(normals)
    binary_blob = _pad(positions + normals + indices, 4, b"\x00")

    xs = [point[0] for point in mesh.positions]
    ys = [point[1] for point in mesh.positions]
    zs = [point[2] for point in mesh.positions]

    gltf = {
        "asset": {"version": "2.0", "generator": "tinyrooms generate_archway_model"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": "Archway"}],
        "meshes": [
            {
                "name": "Archway",
                "primitives": [
                    {
                        "attributes": {"POSITION": 0, "NORMAL": 1},
                        "indices": 2,
                        "material": 0,
                    }
                ],
            }
        ],
        "materials": [
            {
                "name": "Stone",
                "doubleSided": True,
                "pbrMetallicRoughness": {
                    "baseColorFactor": [0.56, 0.57, 0.53, 1.0],
                    "metallicFactor": 0.0,
                    "roughnessFactor": 0.92,
                },
            }
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": len(mesh.positions),
                "type": "VEC3",
                "min": [min(xs), min(ys), min(zs)],
                "max": [max(xs), max(ys), max(zs)],
            },
            {
                "bufferView": 1,
                "componentType": 5126,
                "count": len(mesh.normals),
                "type": "VEC3",
            },
            {
                "bufferView": 2,
                "componentType": 5123,
                "count": len(mesh.indices),
                "type": "SCALAR",
            },
        ],
        "bufferViews": [
            {"buffer": 0, "byteOffset": position_offset, "byteLength": len(positions), "target": 34962},
            {"buffer": 0, "byteOffset": normal_offset, "byteLength": len(normals), "target": 34962},
            {"buffer": 0, "byteOffset": index_offset, "byteLength": len(indices), "target": 34963},
        ],
        "buffers": [{"byteLength": len(binary_blob)}],
    }

    json_blob = _pad(json.dumps(gltf, separators=(",", ":")).encode("utf-8"), 4, b" ")
    total_length = 12 + 8 + len(json_blob) + 8 + len(binary_blob)
    header = struct.pack("<4sII", b"glTF", 2, total_length)
    json_chunk = struct.pack("<II", len(json_blob), 0x4E4F534A) + json_blob
    bin_chunk = struct.pack("<II", len(binary_blob), 0x004E4942) + binary_blob
    return header + json_chunk + bin_chunk


def main() -> None:
    """Write the archway GLB to the mod's props directory."""

    mesh = build_mesh()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_bytes(build_glb(mesh))
    print(f"Wrote {OUTPUT_PATH.relative_to(REPO_ROOT)} ({len(mesh.indices) // 3} triangles)")


if __name__ == "__main__":
    main()

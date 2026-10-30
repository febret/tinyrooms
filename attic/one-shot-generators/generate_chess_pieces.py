"""Generate the Tiny Arcade chess piece GLBs directly with Blender.

Run from the repository root:

    blender --background --factory-startup \
        --python tools/generate_chess_pieces.py

The script builds procedural Staunton-style pieces and exports one GLB per
colour and type into ``worlds/tiny-arcade/props``. These assets are intentionally
not part of ``bake.json``; rerun this script instead of the ComfyUI bake pipeline.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import math
from pathlib import Path
import sys

import bmesh
import bpy
from mathutils import Vector


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "worlds" / "tiny-arcade" / "props"
DEFAULT_PREVIEW = REPO_ROOT / ".local" / "chess-piece-preview.png"
SEGMENTS = 48
PIECE_KINDS = ("pawn", "knight", "bishop", "rook", "queen", "king")
PIECE_SCALES = {
    "pawn": 0.62,
    "knight": 0.84,
    "bishop": 0.90,
    "rook": 0.82,
    "queen": 1.00,
    "king": 1.04,
}
COLORS = {
    "white": {
        "material": "Chess Ivory",
        "hex": "#efe5cf",
        "roughness": 0.38,
        "metallic": 0.0,
    },
    "black": {
        "material": "Chess Charcoal",
        "hex": "#1b1c21",
        "roughness": 0.24,
        "metallic": 0.06,
    },
}
FELT_HEX = "#1f4d3a"


@dataclass(frozen=True)
class PieceStyle:
    key: str
    material_name: str
    hex_color: str
    roughness: float
    metallic: float


def _srgb_channel(value: int) -> float:
    channel = value / 255.0
    if channel <= 0.04045:
        return channel / 12.92
    return ((channel + 0.055) / 1.055) ** 2.4


def _color(hex_color: str) -> tuple[float, float, float, float]:
    value = hex_color.lstrip("#")
    return (
        _srgb_channel(int(value[0:2], 16)),
        _srgb_channel(int(value[2:4], 16)),
        _srgb_channel(int(value[4:6], 16)),
        1.0,
    )


def _material(style: PieceStyle) -> bpy.types.Material:
    material = bpy.data.materials.new(style.material_name)
    material.use_nodes = True
    color = _color(style.hex_color)
    material.diffuse_color = color
    nodes = material.node_tree.nodes
    shader = nodes.get("Principled BSDF")
    if shader is not None:
        shader.inputs["Base Color"].default_value = color
        shader.inputs["Roughness"].default_value = style.roughness
        shader.inputs["Metallic"].default_value = style.metallic
    return material


def _felt_material() -> bpy.types.Material:
    material = bpy.data.materials.new("Chess Felt")
    material.use_nodes = True
    color = _color(FELT_HEX)
    material.diffuse_color = color
    shader = material.node_tree.nodes.get("Principled BSDF")
    if shader is not None:
        shader.inputs["Base Color"].default_value = color
        shader.inputs["Roughness"].default_value = 0.95
        shader.inputs["Metallic"].default_value = 0.0
    return material


def _mesh_object(
    name: str,
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, ...]],
    material: bpy.types.Material,
) -> bpy.types.Object:
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.validate(clean_customdata=False)
    mesh.update()
    editable = bmesh.new()
    editable.from_mesh(mesh)
    bmesh.ops.recalc_face_normals(editable, faces=editable.faces)
    editable.to_mesh(mesh)
    editable.free()
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.data.materials.append(material)
    return obj


def _lathe(
    name: str,
    profile: list[tuple[float, float]],
    material: bpy.types.Material,
    *,
    segments: int = SEGMENTS,
) -> bpy.types.Object:
    vertices: list[tuple[float, float, float]] = []
    for z, radius in profile:
        for step in range(segments):
            angle = 2.0 * math.pi * step / segments
            vertices.append((radius * math.cos(angle), radius * math.sin(angle), z))
    faces: list[tuple[int, ...]] = []
    for ring in range(len(profile) - 1):
        base = ring * segments
        next_base = (ring + 1) * segments
        for step in range(segments):
            following = (step + 1) % segments
            faces.append(
                (
                    base + step,
                    base + following,
                    next_base + following,
                    next_base + step,
                )
            )
    bottom_center = len(vertices)
    vertices.append((0.0, 0.0, profile[0][0]))
    top_center = len(vertices)
    vertices.append((0.0, 0.0, profile[-1][0]))
    for step in range(segments):
        following = (step + 1) % segments
        faces.append((bottom_center, following, step))
        top = (len(profile) - 1) * segments
        faces.append((top_center, top + step, top + following))
    return _mesh_object(name, vertices, faces, material)


def _cylinder(
    name: str,
    radius: float,
    depth: float,
    z: float,
    material: bpy.types.Material,
    *,
    vertices: int = SEGMENTS,
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=vertices,
        radius=radius,
        depth=depth,
        location=(0.0, 0.0, z),
    )
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(material)
    return obj


def _box(
    name: str,
    size: tuple[float, float, float],
    location: tuple[float, float, float],
    material: bpy.types.Material,
    *,
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=location, rotation=rotation)
    obj = bpy.context.object
    obj.name = name
    obj.scale = size
    obj.data.materials.append(material)
    return obj


def _sphere(
    name: str,
    radius: float,
    z: float,
    material: bpy.types.Material,
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=SEGMENTS,
        ring_count=24,
        radius=radius,
        location=(0.0, 0.0, z),
    )
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(material)
    return obj


def _cone(
    name: str,
    radius: float,
    depth: float,
    z: float,
    material: bpy.types.Material,
    *,
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
    location: tuple[float, float, float] | None = None,
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cone_add(
        vertices=24,
        radius1=radius,
        radius2=0.012,
        depth=depth,
        location=location or (0.0, 0.0, z),
        rotation=rotation,
    )
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(material)
    return obj


def _base_profile() -> list[tuple[float, float]]:
    return [
        (0.000, 0.300),
        (0.012, 0.300),
        (0.022, 0.292),
        (0.035, 0.270),
        (0.045, 0.230),
        (0.055, 0.215),
        (0.068, 0.224),
        (0.082, 0.230),
        (0.096, 0.222),
        (0.108, 0.196),
        (0.122, 0.168),
        (0.140, 0.150),
    ]


def _pawn_profile() -> list[tuple[float, float]]:
    profile = _base_profile() + [
        (0.170, 0.142),
        (0.230, 0.124),
        (0.340, 0.104),
        (0.460, 0.100),
        (0.550, 0.108),
        (0.610, 0.132),
        (0.650, 0.148),
        (0.676, 0.126),
        (0.692, 0.100),
    ]
    center = 0.846
    radius = 0.154
    for index in range(1, 20):
        angle = math.pi * index / 20.0
        profile.append(
            (center - radius * math.cos(angle), max(0.004, radius * math.sin(angle)))
        )
    return profile


def _bishop_profile() -> list[tuple[float, float]]:
    profile = _base_profile() + [
        (0.170, 0.142),
        (0.230, 0.120),
        (0.360, 0.100),
        (0.470, 0.108),
        (0.540, 0.128),
        (0.590, 0.155),
        (0.630, 0.176),
        (0.670, 0.212),
        (0.720, 0.232),
        (0.780, 0.214),
        (0.840, 0.170),
        (0.890, 0.118),
        (0.925, 0.075),
        (0.940, 0.060),
    ]
    center = 0.966
    radius = 0.052
    for index in range(1, 16):
        angle = math.pi * index / 16.0
        profile.append(
            (center - radius * math.cos(angle), max(0.004, radius * math.sin(angle)))
        )
    return profile


def _queen_profile() -> list[tuple[float, float]]:
    return _base_profile() + [
        (0.170, 0.145),
        (0.230, 0.122),
        (0.350, 0.102),
        (0.460, 0.110),
        (0.530, 0.138),
        (0.580, 0.168),
        (0.620, 0.196),
        (0.650, 0.220),
        (0.700, 0.242),
        (0.760, 0.252),
        (0.810, 0.250),
        (0.840, 0.238),
        (0.845, 0.206),
        (0.820, 0.190),
    ]


def _king_profile() -> list[tuple[float, float]]:
    return _base_profile() + [
        (0.170, 0.147),
        (0.230, 0.124),
        (0.350, 0.104),
        (0.470, 0.112),
        (0.545, 0.140),
        (0.595, 0.170),
        (0.635, 0.194),
        (0.665, 0.220),
        (0.710, 0.230),
        (0.755, 0.234),
        (0.790, 0.234),
        (0.822, 0.230),
        (0.850, 0.226),
        (0.855, 0.208),
        (0.835, 0.198),
        (0.820, 0.190),
    ]


def _knight_head(material: bpy.types.Material) -> bpy.types.Object:
    silhouette = [
        (-0.150, 0.330),
        (0.115, 0.330),
        (0.145, 0.400),
        (0.165, 0.500),
        (0.180, 0.590),
        (0.205, 0.660),
        (0.255, 0.710),
        (0.320, 0.745),
        (0.360, 0.775),
        (0.355, 0.815),
        (0.300, 0.835),
        (0.235, 0.865),
        (0.185, 0.905),
        (0.140, 0.955),
        (0.105, 1.000),
        (0.070, 0.940),
        (0.025, 0.915),
        (-0.030, 0.880),
        (-0.045, 0.840),
        (-0.095, 0.825),
        (-0.105, 0.790),
        (-0.150, 0.775),
        (-0.160, 0.735),
        (-0.195, 0.715),
        (-0.200, 0.675),
        (-0.230, 0.650),
        (-0.225, 0.610),
        (-0.205, 0.570),
        (-0.200, 0.520),
        (-0.175, 0.470),
        (-0.170, 0.410),
    ]
    half_width = 0.108
    vertices: list[tuple[float, float, float]] = []
    for x in (-half_width, half_width):
        for y, z in silhouette:
            vertices.append((x, y, z))
    count = len(silhouette)
    faces: list[tuple[int, ...]] = []
    faces.append(tuple(range(count - 1, -1, -1)))
    faces.append(tuple(range(count, count * 2)))
    for index in range(count):
        following = (index + 1) % count
        faces.append((index, following, count + following, count + index))
    return _mesh_object("KnightHead", vertices, faces, material)


def _apply_bevel(obj: bpy.types.Object, width: float = 0.008, segments: int = 2) -> None:
    modifier = obj.modifiers.new("EdgeBevel", "BEVEL")
    modifier.width = width
    modifier.segments = segments
    modifier.limit_method = "ANGLE"
    modifier.angle_limit = math.radians(35.0)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=modifier.name)


def _smooth(obj: bpy.types.Object) -> None:
    for polygon in obj.data.polygons:
        polygon.use_smooth = True


def _join(objects: list[bpy.types.Object], name: str) -> bpy.types.Object:
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.object.join()
    joined = bpy.context.object
    joined.name = name
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    return joined


def _normalize(obj: bpy.types.Object) -> None:
    bpy.context.view_layer.update()
    corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    minimum = Vector(
        (
            min(corner.x for corner in corners),
            min(corner.y for corner in corners),
            min(corner.z for corner in corners),
        )
    )
    maximum = Vector(
        (
            max(corner.x for corner in corners),
            max(corner.y for corner in corners),
            max(corner.z for corner in corners),
        )
    )
    center_x = (minimum.x + maximum.x) / 2.0
    center_y = (minimum.y + maximum.y) / 2.0
    height = maximum.z - minimum.z
    for vertex in obj.data.vertices:
        vertex.co.x = (vertex.co.x - center_x) / height
        vertex.co.y = (vertex.co.y - center_y) / height
        vertex.co.z = (vertex.co.z - minimum.z) / height
    obj.data.update()


def _bishop_slit(obj: bpy.types.Object, material: bpy.types.Material) -> None:
    cutter = _box(
        "BishopSlitCutter",
        (0.48, 0.16, 0.045),
        (0.0, 0.0, 0.822),
        material,
        rotation=(math.radians(38.0), 0.0, 0.0),
    )
    modifier = obj.modifiers.new("BishopSlit", "BOOLEAN")
    modifier.operation = "DIFFERENCE"
    modifier.solver = "EXACT"
    modifier.object = cutter
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    bpy.data.objects.remove(cutter, do_unlink=True)


def _build_piece(kind: str, style: PieceStyle) -> bpy.types.Object:
    material = _material(style)
    felt = _felt_material()
    objects: list[bpy.types.Object] = [
        _cylinder("Felt", 0.305, 0.014, 0.007, felt)
    ]
    if kind == "pawn":
        body = _lathe("Body", _pawn_profile(), material)
    elif kind == "bishop":
        body = _lathe("Body", _bishop_profile(), material)
        _bishop_slit(body, material)
    elif kind == "queen":
        body = _lathe("Body", _queen_profile(), material)
        for index in range(10):
            angle = 2.0 * math.pi * index / 10.0
            radius = 0.205
            point = _cone(
                f"CrownPoint{index}",
                0.032,
                0.110,
                0.880,
                material,
                location=(radius * math.cos(angle), radius * math.sin(angle), 0.880),
            )
            objects.append(point)
        objects.append(_sphere("Finial", 0.052, 0.962, material))
    elif kind == "rook":
        body = _lathe(
            "Body",
            _base_profile()
            + [
                (0.180, 0.166),
                (0.260, 0.158),
                (0.620, 0.158),
                (0.680, 0.176),
                (0.720, 0.200),
                (0.780, 0.222),
                (0.820, 0.228),
                (0.835, 0.214),
            ],
            material,
        )
        objects.append(_cylinder("TowerBand", 0.235, 0.060, 0.705, material))
        for index in range(8):
            angle = 2.0 * math.pi * index / 8.0
            radius = 0.176
            objects.append(
                _box(
                    f"Merlon{index}",
                    (0.090, 0.080, 0.165),
                    (radius * math.cos(angle), radius * math.sin(angle), 0.905),
                    material,
                    rotation=(0.0, 0.0, angle),
                )
            )
    elif kind == "king":
        body = _lathe("Body", _king_profile(), material)
        objects.append(_cylinder("CrownBand", 0.242, 0.070, 0.670, material))
        objects.append(_box("CrossStem", (0.062, 0.062, 0.190), (0.0, 0.0, 0.930), material))
        objects.append(_box("CrossBar", (0.180, 0.062, 0.060), (0.0, 0.0, 0.965), material))
    else:
        body = _lathe(
            "Neck",
            _base_profile()
            + [
                (0.165, 0.168),
                (0.230, 0.170),
                (0.300, 0.176),
                (0.350, 0.180),
            ],
            material,
        )
        head = _knight_head(material)
        _apply_bevel(head, width=0.028, segments=4)
        objects.append(head)
    _apply_bevel(body)
    _smooth(body)
    objects.insert(1, body)
    for obj in objects[1:]:
        _smooth(obj)
    joined = _join(objects, f"Chess{kind.title()}")
    _normalize(joined)
    _smooth(joined)
    return joined


def _export_piece(kind: str, color: str, output_dir: Path) -> Path:
    style = PieceStyle(
        key=color,
        material_name=COLORS[color]["material"],
        hex_color=COLORS[color]["hex"],
        roughness=COLORS[color]["roughness"],
        metallic=COLORS[color]["metallic"],
    )
    obj = _build_piece(kind, style)
    output = output_dir / f"chess-{kind}-{color}.glb"
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.export_scene.gltf(
        filepath=str(output),
        export_format="GLB",
        use_selection=True,
        export_apply=True,
        export_yup=True,
        export_materials="EXPORT",
        export_cameras=False,
        export_lights=False,
        export_animations=False,
    )
    bpy.data.objects.remove(obj, do_unlink=True)
    return output


def _clear_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for block in (bpy.data.meshes, bpy.data.materials, bpy.data.cameras, bpy.data.lights):
        for item in list(block):
            if item.users == 0:
                block.remove(item)


def _preview(output: Path, kinds: list[str]) -> None:
    _clear_scene()
    white = PieceStyle(
        key="white",
        material_name=COLORS["white"]["material"],
        hex_color=COLORS["white"]["hex"],
        roughness=COLORS["white"]["roughness"],
        metallic=COLORS["white"]["metallic"],
    )
    black = PieceStyle(
        key="black",
        material_name=COLORS["black"]["material"],
        hex_color=COLORS["black"]["hex"],
        roughness=COLORS["black"]["roughness"],
        metallic=COLORS["black"]["metallic"],
    )
    spacing = 1.25
    center = (len(kinds) - 1) / 2.0
    for color_index, style in enumerate((white, black)):
        for kind_index, kind in enumerate(kinds):
            obj = _build_piece(kind, style)
            scale = PIECE_SCALES[kind]
            obj.scale = (scale, scale, scale)
            obj.location = (
                (kind_index - center) * spacing,
                3.0 - color_index * 3.4,
                0.0,
            )
    bpy.ops.mesh.primitive_plane_add(size=40.0, location=(0.0, 0.0, -0.005))
    plane = bpy.context.object
    plane_material = bpy.data.materials.new("Preview Floor")
    plane_material.use_nodes = True
    floor_shader = plane_material.node_tree.nodes.get("Principled BSDF")
    if floor_shader is not None:
        floor_shader.inputs["Base Color"].default_value = (0.07, 0.055, 0.08, 1.0)
        floor_shader.inputs["Roughness"].default_value = 0.8
    plane.data.materials.append(plane_material)

    camera_data = bpy.data.cameras.new("Preview Camera")
    camera = bpy.data.objects.new("Preview Camera", camera_data)
    bpy.context.scene.collection.objects.link(camera)
    camera.location = (6.8, -11.5, 6.2)
    target = Vector((0.0, 0.2, 0.36))
    camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()
    camera_data.lens = 52
    bpy.context.scene.camera = camera

    sun_data = bpy.data.lights.new("Key", "SUN")
    sun = bpy.data.objects.new("Key", sun_data)
    bpy.context.scene.collection.objects.link(sun)
    sun.rotation_euler = (math.radians(52), 0.0, math.radians(32))
    sun_data.energy = 3.2
    fill_data = bpy.data.lights.new("Fill", "AREA")
    fill = bpy.data.objects.new("Fill", fill_data)
    bpy.context.scene.collection.objects.link(fill)
    fill.location = (-5.0, -3.0, 4.0)
    fill.rotation_euler = (math.radians(60), 0.0, math.radians(-40))
    fill_data.energy = 500
    fill_data.size = 5.0

    world = bpy.data.worlds.new("Preview World")
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    if background is not None:
        background.inputs[0].default_value = (0.025, 0.02, 0.032, 1.0)
        background.inputs[1].default_value = 0.35
    bpy.context.scene.world = world

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 1600
    scene.render.resolution_y = 900
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.render.render(write_still=True)


def _parse_args() -> argparse.Namespace:
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--only", action="append", choices=PIECE_KINDS, default=[])
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--preview-path", type=Path, default=DEFAULT_PREVIEW)
    return parser.parse_args(argv)


def main() -> int:
    args = _parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    kinds = args.only or list(PIECE_KINDS)
    for kind in kinds:
        for color in ("white", "black"):
            _clear_scene()
            output = _export_piece(kind, color, output_dir)
            print(f"generated {output.relative_to(REPO_ROOT)}")
    if args.preview:
        _preview(args.preview_path.resolve(), kinds)
        print(f"rendered {args.preview_path.resolve().relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

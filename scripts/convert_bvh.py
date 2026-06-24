# Copyright (c) 2026 Yuancheng Li
# SPDX-License-Identifier: Apache-2.0

"""Convert one BVH motion file to a GLB preview and WebP thumbnail.

Run with Blender, not the project Python interpreter:

    blender --background --python scripts/convert_bvh.py -- \
        --input data/source/cmu-mocap/data/001/01_01.bvh \
        --glb data/assets/previews/cmu_01_01.glb \
        --thumbnail data/assets/thumbnails/cmu_01_01.webp
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import bpy
from mathutils import Vector


DEFAULT_AXIS_FORWARD = "-Z"
DEFAULT_AXIS_UP = "Y"
DEFAULT_SCALE = 1.0
DEFAULT_RENDER_SIZE = 512
THUMBNAIL_STICK_OBJECT = "Thumbnail_Stick_Figure"


def blender_script_args() -> list[str]:
    """Return command-line arguments after Blender's ``--`` separator."""
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def parse_args() -> argparse.Namespace:
    """Parse conversion arguments."""
    parser = argparse.ArgumentParser(
        description="Convert one BVH file to GLB and render a WebP thumbnail."
    )
    parser.add_argument("--input", type=Path, required=True, help="Source BVH file.")
    parser.add_argument("--glb", type=Path, required=True, help="Output GLB file.")
    parser.add_argument("--thumbnail", type=Path, required=True, help="Output WebP thumbnail.")
    parser.add_argument(
        "--metadata",
        type=Path,
        help="Optional JSON metadata output with hashes, sizes, and conversion settings.",
    )
    parser.add_argument(
        "--frame-count",
        type=int,
        help="Expected BVH frame count. Defaults to Blender's imported scene range.",
    )
    parser.add_argument(
        "--frame-time",
        type=float,
        help="BVH frame time in seconds. Used to set scene FPS.",
    )
    parser.add_argument(
        "--frame-rate",
        type=float,
        help="BVH frame rate. Used when --frame-time is not provided.",
    )
    parser.add_argument(
        "--target-frame-rate",
        type=float,
        help="Optional output frame rate. Retimes animation while preserving duration.",
    )
    parser.add_argument(
        "--thumbnail-frame",
        type=int,
        help="Frame to render. Defaults to the middle of the active frame range.",
    )
    parser.add_argument(
        "--scale",
        type=float,
        default=DEFAULT_SCALE,
        help=f"BVH import scale (default: {DEFAULT_SCALE}).",
    )
    parser.add_argument(
        "--axis-forward",
        default=DEFAULT_AXIS_FORWARD,
        help=f"BVH import forward axis (default: {DEFAULT_AXIS_FORWARD}).",
    )
    parser.add_argument(
        "--axis-up",
        default=DEFAULT_AXIS_UP,
        help=f"BVH import up axis (default: {DEFAULT_AXIS_UP}).",
    )
    parser.add_argument(
        "--render-size",
        type=int,
        default=DEFAULT_RENDER_SIZE,
        help=f"Thumbnail width and height in pixels (default: {DEFAULT_RENDER_SIZE}).",
    )
    parser.add_argument(
        "--gltfpack",
        action="store_true",
        help="Optimize the exported GLB with gltfpack after Blender export.",
    )
    parser.add_argument(
        "--gltfpack-path",
        default="gltfpack",
        help="gltfpack executable path (default: gltfpack).",
    )
    parser.add_argument(
        "--gltfpack-arg",
        action="append",
        default=[],
        help="Extra gltfpack argument. Can be passed more than once.",
    )
    parser.add_argument(
        "--raw-glb",
        type=Path,
        help="Raw Blender GLB output path when --gltfpack is enabled.",
    )
    parser.add_argument(
        "--keep-raw-glb",
        action="store_true",
        help="Keep the raw Blender GLB after successful gltfpack optimization.",
    )
    args = parser.parse_args(blender_script_args())
    args.input = args.input.resolve()
    args.glb = args.glb.resolve()
    args.thumbnail = args.thumbnail.resolve()
    if args.metadata is not None:
        args.metadata = args.metadata.resolve()
    if args.raw_glb is not None:
        args.raw_glb = args.raw_glb.resolve()
    return args


def operator_kwargs(operator: Any, values: dict[str, Any]) -> dict[str, Any]:
    """Filter keyword arguments to properties supported by a Blender operator."""
    supported = {property.identifier for property in operator.get_rna_type().properties}
    return {key: value for key, value in values.items() if key in supported}


def enable_addon(module: str) -> None:
    """Enable a Blender add-on if this Blender build exposes it."""
    try:
        bpy.ops.preferences.addon_enable(module=module)
    except Exception:
        return


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clear_scene() -> None:
    """Remove all objects from the active scene."""
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()


def import_bvh(args: argparse.Namespace) -> bpy.types.Object:
    """Import a BVH file and return the imported armature."""
    before = set(bpy.data.objects)
    kwargs = operator_kwargs(
        bpy.ops.import_anim.bvh,
        {
            "filepath": str(args.input),
            "global_scale": args.scale,
            "axis_forward": args.axis_forward,
            "axis_up": args.axis_up,
            "frame_start": 1,
            "rotate_mode": "NATIVE",
            "update_scene_fps": False,
            "update_scene_duration": False,
            "use_fps_scale": False,
        },
    )
    result = bpy.ops.import_anim.bvh(**kwargs)
    if "FINISHED" not in result:
        raise RuntimeError(f"BVH import failed: {sorted(result)}")

    imported = [object_ for object_ in bpy.data.objects if object_ not in before]
    armatures = [object_ for object_ in imported if object_.type == "ARMATURE"]
    if not armatures:
        raise RuntimeError("BVH import did not create an armature")
    if len(armatures) > 1:
        raise RuntimeError(f"BVH import created multiple armatures: {len(armatures)}")

    armature = armatures[0]
    if armature.animation_data is None or armature.animation_data.action is None:
        raise RuntimeError("Imported armature has no animation action")
    return armature


def source_frame_rate(args: argparse.Namespace) -> float | None:
    """Return source frame rate from explicit timing arguments."""
    if args.frame_time is not None:
        if args.frame_time <= 0:
            raise ValueError("--frame-time must be positive")
        return 1.0 / args.frame_time
    if args.frame_rate is not None:
        if args.frame_rate <= 0:
            raise ValueError("--frame-rate must be positive")
        return args.frame_rate
    return None


def retime_action(
    armature: bpy.types.Object,
    *,
    source_fps: float,
    target_fps: float,
    frame_start: int,
) -> None:
    """Scale imported action keyframes to a new FPS while preserving duration."""
    if target_fps <= 0:
        raise ValueError("--target-frame-rate must be positive")

    action = armature.animation_data.action
    fcurves = list(action_fcurves(action))
    if not fcurves:
        raise RuntimeError("Imported action has no editable F-curves")

    ratio = target_fps / source_fps
    for fcurve in fcurves:
        for keyframe in fcurve.keyframe_points:
            for point in (keyframe.co, keyframe.handle_left, keyframe.handle_right):
                point.x = frame_start + ((point.x - frame_start) * ratio)
        fcurve.update()


def action_fcurves(action: Any) -> list[Any]:
    """Return F-curves from legacy or layered Blender action data."""
    fcurves: list[Any] = []
    seen: set[int] = set()
    stack = [action]

    while stack:
        value = stack.pop()
        pointer = value_pointer(value)
        if pointer in seen:
            continue
        seen.add(pointer)

        maybe_fcurves = optional_attr(value, "fcurves")
        if maybe_fcurves is not None:
            for fcurve in iterable_values(maybe_fcurves):
                if optional_attr(fcurve, "keyframe_points") is not None:
                    fcurves.append(fcurve)

        for attribute in ("layers", "strips", "channelbags", "channels", "groups", "slots"):
            child_values = optional_attr(value, attribute)
            if child_values is None:
                continue
            stack.extend(iterable_values(child_values))

    return fcurves


def optional_attr(value: Any, name: str) -> Any | None:
    """Read a Blender RNA attribute if it exists."""
    try:
        return getattr(value, name)
    except (AttributeError, TypeError, RuntimeError):
        return None


def iterable_values(value: Any) -> list[Any]:
    """Return a list for Blender RNA collections and skip scalar values."""
    try:
        return list(value)
    except TypeError:
        return []


def value_pointer(value: Any) -> int:
    """Return a stable-ish identity for Blender RNA values."""
    as_pointer = optional_attr(value, "as_pointer")
    if callable(as_pointer):
        try:
            return int(as_pointer())
        except RuntimeError:
            pass
    return id(value)


def configure_timing(args: argparse.Namespace, armature: bpy.types.Object) -> tuple[int, int, int]:
    """Set scene frame range and FPS, returning start, end, and thumbnail frames."""
    scene = bpy.context.scene
    scene.frame_start = 1
    fps = source_frame_rate(args)

    if args.frame_count is not None:
        if args.frame_count <= 0:
            raise ValueError("--frame-count must be positive")
        scene.frame_end = args.frame_count
    else:
        action = armature.animation_data.action
        scene.frame_end = max(1, int(round(action.frame_range[1])))

    if args.target_frame_rate is not None:
        if fps is None:
            raise ValueError("--target-frame-rate requires --frame-time or --frame-rate")
        retime_action(
            armature,
            source_fps=fps,
            target_fps=args.target_frame_rate,
            frame_start=scene.frame_start,
        )
        ratio = args.target_frame_rate / fps
        scene.frame_end = max(
            scene.frame_start,
            int(round(scene.frame_start + ((scene.frame_end - scene.frame_start) * ratio))),
        )
        scene.render.fps = max(1, int(round(args.target_frame_rate)))
    elif fps is not None:
        scene.render.fps = max(1, int(round(fps)))

    thumbnail_frame = args.thumbnail_frame
    if thumbnail_frame is None:
        thumbnail_frame = (scene.frame_start + scene.frame_end) // 2
    thumbnail_frame = max(scene.frame_start, min(scene.frame_end, thumbnail_frame))
    scene.frame_set(thumbnail_frame)
    return scene.frame_start, scene.frame_end, thumbnail_frame


def select_for_export(armature: bpy.types.Object) -> None:
    """Select the imported armature for GLB export."""
    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature


def export_glb(path: Path, armature: bpy.types.Object) -> None:
    """Export the selected armature and animation to GLB."""
    path.parent.mkdir(parents=True, exist_ok=True)
    select_for_export(armature)
    kwargs = operator_kwargs(
        bpy.ops.export_scene.gltf,
        {
            "filepath": str(path),
            "export_format": "GLB",
            "use_selection": True,
            "export_animations": True,
            "export_frame_range": True,
            "export_force_sampling": True,
            "export_skins": True,
            "export_def_bones": True,
            "export_yup": True,
        },
    )
    result = bpy.ops.export_scene.gltf(**kwargs)
    if "FINISHED" not in result:
        raise RuntimeError(f"GLB export failed: {sorted(result)}")


def raw_glb_path(args: argparse.Namespace) -> Path:
    """Return the raw Blender export path for optional gltfpack optimization."""
    if args.raw_glb is not None:
        return args.raw_glb
    return args.glb.with_name(f"{args.glb.stem}.raw{args.glb.suffix}")


def run_gltfpack(
    *,
    executable: str,
    input_path: Path,
    output_path: Path,
    extra_args: list[str],
) -> list[str]:
    """Optimize a GLB with gltfpack and return the command."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        executable,
        "-i",
        str(input_path),
        "-o",
        str(output_path),
        "-kn",
        *extra_args,
    ]
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as error:
        raise RuntimeError(
            f"gltfpack executable not found: {executable}. "
            "Install gltfpack or pass --gltfpack-path."
        ) from error

    if result.returncode != 0:
        output = "\n".join(part for part in (result.stdout, result.stderr) if part)
        raise RuntimeError(f"gltfpack failed with exit code {result.returncode}\n{output}")
    return command


def scene_bounds(
    objects: list[bpy.types.Object],
) -> tuple[float, float, float, float, float, float]:
    """Return min/max world-space bounds for visible scene objects."""
    coordinates: list[tuple[float, float, float]] = []
    for object_ in objects:
        if object_.type == "ARMATURE":
            for bone in object_.pose.bones:
                coordinates.append(tuple(object_.matrix_world @ bone.head))
                coordinates.append(tuple(object_.matrix_world @ bone.tail))
        elif hasattr(object_, "bound_box"):
            for corner in object_.bound_box:
                coordinates.append(tuple(object_.matrix_world @ Vector(corner)))

    if not coordinates:
        return (-1.0, 1.0, -1.0, 1.0, -1.0, 1.0)

    xs, ys, zs = zip(*coordinates)
    return (min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))


def configure_thumbnail_scene(size: int, armature: bpy.types.Object) -> None:
    """Set camera, lighting, and render settings for a thumbnail."""
    scene = bpy.context.scene
    scene.render.resolution_x = size
    scene.render.resolution_y = size
    scene.render.film_transparent = True
    scene.view_settings.view_transform = "Standard"

    image_settings = scene.render.image_settings
    image_settings.file_format = "WEBP"
    image_settings.color_mode = "RGBA"
    if hasattr(image_settings, "quality"):
        image_settings.quality = 90

    armature.show_in_front = True
    armature.data.display_type = "STICK"

    stick_figure = create_thumbnail_stick_figure(armature)
    bounds = scene_bounds([stick_figure])
    center_x = (bounds[0] + bounds[1]) / 2.0
    center_y = (bounds[2] + bounds[3]) / 2.0
    center_z = (bounds[4] + bounds[5]) / 2.0
    span = max(bounds[1] - bounds[0], bounds[3] - bounds[2], bounds[5] - bounds[4], 1.0)

    light_data = bpy.data.lights.new(name="Thumbnail_Key_Light", type="AREA")
    light = bpy.data.objects.new(name="Thumbnail_Key_Light", object_data=light_data)
    bpy.context.collection.objects.link(light)
    light.location = (center_x - span, center_y - span * 2.0, center_z + span * 1.8)
    light_data.energy = 500
    light_data.size = span

    camera_data = bpy.data.cameras.new(name="Thumbnail_Camera")
    camera = bpy.data.objects.new(name="Thumbnail_Camera", object_data=camera_data)
    bpy.context.collection.objects.link(camera)
    camera.location = (center_x, center_y - span * 2.8, center_z + span * 0.4)
    camera.rotation_euler = (1.35, 0.0, 0.0)
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = span * 1.25
    scene.camera = camera


def create_thumbnail_stick_figure(armature: bpy.types.Object) -> bpy.types.Object:
    """Create renderable stick geometry for the current armature pose."""
    existing = bpy.data.objects.get(THUMBNAIL_STICK_OBJECT)
    if existing is not None:
        bpy.data.objects.remove(existing, do_unlink=True)

    bounds = scene_bounds([armature])
    span = max(bounds[1] - bounds[0], bounds[3] - bounds[2], bounds[5] - bounds[4], 1.0)

    curve = bpy.data.curves.new(name=THUMBNAIL_STICK_OBJECT, type="CURVE")
    curve.dimensions = "3D"
    curve.resolution_u = 1
    curve.bevel_depth = max(span * 0.004, 0.01)
    curve.bevel_resolution = 2

    for bone in armature.pose.bones:
        head = armature.matrix_world @ bone.head
        tail = armature.matrix_world @ bone.tail
        if (tail - head).length == 0:
            continue
        spline = curve.splines.new("POLY")
        spline.points.add(1)
        spline.points[0].co = (head.x, head.y, head.z, 1.0)
        spline.points[1].co = (tail.x, tail.y, tail.z, 1.0)

    material = bpy.data.materials.new(name="Thumbnail_Stick_Material")
    material.diffuse_color = (0.05, 0.08, 0.12, 1.0)
    curve.materials.append(material)

    stick_figure = bpy.data.objects.new(THUMBNAIL_STICK_OBJECT, curve)
    bpy.context.collection.objects.link(stick_figure)
    return stick_figure


def render_thumbnail(path: Path, size: int, armature: bpy.types.Object) -> None:
    """Render a WebP thumbnail."""
    path.parent.mkdir(parents=True, exist_ok=True)
    configure_thumbnail_scene(size, armature)
    bpy.context.scene.render.filepath = str(path)
    result = bpy.ops.render.render(write_still=True)
    if "FINISHED" not in result:
        raise RuntimeError(f"Thumbnail render failed: {sorted(result)}")


def write_metadata(
    path: Path,
    args: argparse.Namespace,
    frame_start: int,
    frame_end: int,
    thumbnail_frame: int,
    raw_glb: Path | None = None,
    gltfpack_command: list[str] | None = None,
) -> None:
    """Write optional conversion metadata."""
    metadata = {
        "source_path": str(args.input),
        "glb_path": str(args.glb),
        "raw_glb_path": str(raw_glb) if raw_glb is not None else None,
        "thumbnail_path": str(args.thumbnail),
        "source_sha256": sha256_file(args.input),
        "glb_sha256": sha256_file(args.glb),
        "raw_glb_sha256": sha256_file(raw_glb) if raw_glb and raw_glb.exists() else None,
        "thumbnail_sha256": sha256_file(args.thumbnail),
        "glb_size_bytes": args.glb.stat().st_size,
        "raw_glb_size_bytes": raw_glb.stat().st_size if raw_glb and raw_glb.exists() else None,
        "thumbnail_size_bytes": args.thumbnail.stat().st_size,
        "frame_start": frame_start,
        "frame_end": frame_end,
        "thumbnail_frame": thumbnail_frame,
        "fps": bpy.context.scene.render.fps,
        "target_frame_rate": args.target_frame_rate,
        "gltfpack": args.gltfpack,
        "gltfpack_command": gltfpack_command,
        "scale": args.scale,
        "axis_forward": args.axis_forward,
        "axis_up": args.axis_up,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    """Convert the requested BVH file."""
    args = parse_args()
    if not args.input.is_file():
        raise FileNotFoundError(f"BVH file does not exist: {args.input}")

    enable_addon("io_anim_bvh")
    enable_addon("io_scene_gltf2")

    clear_scene()
    armature = import_bvh(args)
    frame_start, frame_end, thumbnail_frame = configure_timing(args, armature)

    raw_glb = raw_glb_path(args) if args.gltfpack else None
    export_path = raw_glb if raw_glb is not None else args.glb
    export_glb(export_path, armature)

    gltfpack_command = None
    if args.gltfpack:
        gltfpack_command = run_gltfpack(
            executable=args.gltfpack_path,
            input_path=export_path,
            output_path=args.glb,
            extra_args=args.gltfpack_arg,
        )

    render_thumbnail(args.thumbnail, args.render_size, armature)
    if args.metadata:
        write_metadata(
            args.metadata,
            args,
            frame_start,
            frame_end,
            thumbnail_frame,
            raw_glb=raw_glb,
            gltfpack_command=gltfpack_command,
        )
    if raw_glb is not None and not args.keep_raw_glb:
        raw_glb.unlink(missing_ok=True)

    print(f"Wrote GLB: {args.glb}")
    print(f"Wrote thumbnail: {args.thumbnail}")


if __name__ == "__main__":
    main()

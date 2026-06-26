# Copyright (c) 2026 Yuancheng Li
# SPDX-License-Identifier: Apache-2.0

"""Retarget one CMU BVH file onto the loaded X Bot template and export a GLB.

Run with Blender, not the project Python interpreter:

    blender --background xbot_template.blend \
        --python src/features/blender_conversion/blender_single.py -- \
        --input data/source/cmu-mocap/data/001/01_01.bvh \
        --glb data/assets/previews/cmu_01_01.glb \
        --in-place-glb data/assets/previews/cmu_01_01_in_place.glb
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SOURCE_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CMU_DATA_ROOT = REPOSITORY_ROOT / "data/source/cmu-mocap/data"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from core.files import sha256_file  # noqa: E402

import bpy

DEFAULT_SOURCE_FRAME_RATE = 120.0
DEFAULT_EXPORT_FRAME_RATE = 30.0
DEFAULT_TARGET_RIG_NAME = "Armature"
DEFAULT_CONVERSION_VERSION = "xbot-retarget-v1"
DEFAULT_ROTATE_MODE = "NATIVE"
DEFAULT_AXIS_FORWARD = "-Z"
DEFAULT_AXIS_UP = "Y"
DEFAULT_SCALE = 1.0
DEFAULT_GLTFPACK_ARGS = ["-kn", "-cc"]
DEFAULT_IN_PLACE_VERTICAL_AXIS = "Y"
DEFAULT_PREVIEW_BOUND_SAMPLE_COUNT = 24
DEFAULT_IN_PLACE_ROOT_BONES = (
    "mixamorig:Hips",
    "Hips",
    "mixamorig:Root",
    "Root",
)

IGNORED_HAND_BONES = {
    "LeftFingerBase",
    "LeftHandIndex1",
    "LThumb",
    "RightFingerBase",
    "RightHandIndex1",
    "RThumb",
    "mixamorig:LeftFingerBase",
    "mixamorig:LeftHandIndex1",
    "mixamorig:LThumb",
    "mixamorig:RightFingerBase",
    "mixamorig:RightHandIndex1",
    "mixamorig:RThumb",
}


@dataclass(frozen=True, slots=True)
class RetargetResult:
    """Frame and action details from one retargeting run."""

    action: bpy.types.Action
    source_frame_start: int
    source_frame_end: int
    export_frame_start: int
    export_frame_end: int


@dataclass(frozen=True, slots=True)
class InPlaceResult:
    """Details for an in-place action derived from a retargeted action."""

    action: bpy.types.Action
    root_bone: str
    vertical_axis: str
    neutralized_location_curves: int


def blender_script_args() -> list[str]:
    """Return command-line arguments after Blender's ``--`` separator."""
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def parse_args() -> argparse.Namespace:
    """Parse headless retargeting arguments."""
    parser = argparse.ArgumentParser(
        description="Retarget one BVH motion onto the loaded template rig and export GLB."
    )
    parser.add_argument("--input", type=Path, required=True, help="Source BVH file.")
    parser.add_argument(
        "--glb",
        type=Path,
        help="Output normal animation GLB file. Required for --variant normal/both.",
    )
    parser.add_argument(
        "--variant",
        choices=("normal", "in-place", "both"),
        help=(
            "Which GLB variant to export. Defaults to both when --in-place-glb is set, "
            "otherwise normal."
        ),
    )
    parser.add_argument(
        "--in-place-glb",
        type=Path,
        help="Optional second GLB with horizontal root motion removed.",
    )
    parser.add_argument(
        "--metadata",
        type=Path,
        help="Optional JSON metadata output for this source motion and its exported variants.",
    )
    parser.add_argument(
        "--source-id",
        help="Canonical motion source ID. Defaults to deriving from CMU BVH filename.",
    )
    parser.add_argument(
        "--source-relative-path",
        help="Canonical source BVH path, relative to the CMU data root.",
    )
    parser.add_argument(
        "--source-object-key",
        help="Optional uploaded source BVH object key.",
    )
    parser.add_argument(
        "--glb-object-key",
        help="Uploaded GLB object key. Defaults to a deterministic key from source_id.",
    )
    parser.add_argument(
        "--in-place-glb-object-key",
        help="Uploaded in-place GLB object key. Defaults to a deterministic key from source_id.",
    )
    parser.add_argument(
        "--thumbnail-object-key",
        help="Optional uploaded thumbnail object key.",
    )
    parser.add_argument(
        "--conversion-version",
        default=DEFAULT_CONVERSION_VERSION,
        help=f"Stable conversion version (default: {DEFAULT_CONVERSION_VERSION}).",
    )
    parser.add_argument(
        "--target-rig-name",
        default=DEFAULT_TARGET_RIG_NAME,
        help=f"Template target armature name (default: {DEFAULT_TARGET_RIG_NAME}).",
    )
    parser.add_argument(
        "--source-frame-rate",
        type=float,
        default=DEFAULT_SOURCE_FRAME_RATE,
        help=f"BVH source frame rate (default: {DEFAULT_SOURCE_FRAME_RATE}).",
    )
    parser.add_argument(
        "--export-frame-rate",
        type=float,
        default=DEFAULT_EXPORT_FRAME_RATE,
        help=f"Export frame rate after retiming (default: {DEFAULT_EXPORT_FRAME_RATE}).",
    )
    parser.add_argument(
        "--trim-start-frames",
        type=int,
        default=1,
        help="Number of exported frames to skip from the start (default: 1).",
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
        "--rotate-mode",
        default=DEFAULT_ROTATE_MODE,
        help=f"BVH import rotation mode (default: {DEFAULT_ROTATE_MODE}).",
    )
    parser.add_argument(
        "--rokoko-addon",
        help="Optional Rokoko add-on module name to enable before retargeting.",
    )
    parser.add_argument(
        "--in-place-root-bone",
        help="Root bone whose horizontal location curves are flattened for --in-place-glb.",
    )
    parser.add_argument(
        "--in-place-vertical-axis",
        choices=("X", "Y", "Z"),
        default=DEFAULT_IN_PLACE_VERTICAL_AXIS,
        help=(
            "Root location axis to preserve for --in-place-glb "
            f"(default: {DEFAULT_IN_PLACE_VERTICAL_AXIS})."
        ),
    )
    parser.add_argument(
        "--no-gltfpack",
        action="store_true",
        help="Skip gltfpack optimization and write Blender's GLB directly.",
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
        help="Raw Blender GLB output path when gltfpack is enabled.",
    )
    parser.add_argument(
        "--keep-raw-glb",
        action="store_true",
        help="Keep the raw Blender GLB after successful gltfpack optimization.",
    )
    args = parser.parse_args(blender_script_args())
    args.input = args.input.resolve()
    if args.glb is not None:
        args.glb = args.glb.resolve()
    if args.in_place_glb is not None:
        args.in_place_glb = args.in_place_glb.resolve()
    if args.variant is None:
        if args.glb is not None and args.in_place_glb is not None:
            args.variant = "both"
        elif args.in_place_glb is not None:
            args.variant = "in-place"
        else:
            args.variant = "normal"
    if args.variant in {"normal", "both"} and args.glb is None:
        parser.error("--variant normal/both requires --glb")
    if args.variant in {"in-place", "both"} and args.in_place_glb is None:
        parser.error("--variant in-place/both requires --in-place-glb")
    if args.variant == "normal" and args.in_place_glb is not None:
        parser.error("--in-place-glb is only used with --variant in-place or --variant both")
    if args.trim_start_frames < 0:
        parser.error("--trim-start-frames must be zero or greater")
    if args.metadata is not None:
        args.metadata = args.metadata.resolve()
    if args.glb_object_key and args.variant == "in-place":
        parser.error("--glb-object-key is only used with --variant normal or --variant both")
    if args.in_place_glb_object_key and args.in_place_glb is None:
        parser.error("--in-place-glb-object-key requires --in-place-glb")
    if args.in_place_glb_object_key and args.variant == "normal":
        parser.error(
            "--in-place-glb-object-key is only used with --variant in-place or --variant both"
        )
    if args.raw_glb is not None:
        args.raw_glb = args.raw_glb.resolve()
    return args


def operator_kwargs(operator: Any, values: dict[str, Any]) -> dict[str, Any]:
    """Filter keyword arguments to properties supported by a Blender operator."""
    supported = {prop.identifier for prop in operator.get_rna_type().properties}
    return {key: value for key, value in values.items() if key in supported}


def enable_addon(module: str) -> None:
    """Enable a Blender add-on if this Blender build exposes it."""
    try:
        bpy.ops.preferences.addon_enable(module=module)
    except Exception:
        return


def import_bvh(args: argparse.Namespace) -> bpy.types.Object:
    """Import a BVH file and return the newly created source armature."""
    before = set(bpy.data.objects)
    kwargs = operator_kwargs(
        bpy.ops.import_anim.bvh,
        {
            "filepath": str(args.input),
            "global_scale": args.scale,
            "axis_forward": args.axis_forward,
            "axis_up": args.axis_up,
            "rotate_mode": args.rotate_mode,
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
        names = ", ".join(object_.name for object_ in armatures)
        raise RuntimeError(f"BVH import created multiple armatures: {names}")

    source = armatures[0]
    if source.animation_data is None or source.animation_data.action is None:
        raise RuntimeError("Imported BVH armature has no animation action")
    return source


def target_armature(name: str) -> bpy.types.Object:
    """Return the loaded template target armature."""
    target = bpy.data.objects.get(name)
    if target is None:
        raise RuntimeError(
            f"Target armature not found: {name}. "
            "Load the X Bot template .blend before running this script."
        )
    if target.type != "ARMATURE":
        raise RuntimeError(f"Target object is not an armature: {name}")
    return target


def export_animation_glb(path: Path, armature: bpy.types.Object) -> None:
    """Export the selected retargeted armature animation to GLB."""
    path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature

    kwargs = operator_kwargs(
        bpy.ops.export_scene.gltf,
        {
            "filepath": str(path),
            "export_format": "GLB",
            "use_selection": True,
            "export_animations": True,
            "export_frame_range": True,
            "export_force_sampling": False,
            "export_optimize_animation_size": True,
            "export_skins": True,
            "export_def_bones": True,
            "export_materials": "NONE",
            "export_cameras": False,
            "export_lights": False,
            "export_morph": False,
            "export_extras": False,
        },
    )
    result = bpy.ops.export_scene.gltf(**kwargs)
    if "FINISHED" not in result:
        raise RuntimeError(f"GLB export failed: {sorted(result)}")


def raw_glb_path(args: argparse.Namespace) -> Path:
    """Return the raw Blender export path for optional gltfpack optimization."""
    if args.raw_glb is not None:
        return args.raw_glb
    return raw_glb_path_for(args.glb)


def raw_glb_path_for(path: Path) -> Path:
    """Return the default raw Blender export path for one optimized GLB."""
    return path.with_name(f"{path.stem}.raw{path.suffix}")


def source_id_from_filename(path: Path) -> str:
    """Derive the canonical CMU source ID from a BVH filename."""
    parts = path.stem.split("_", maxsplit=1)
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise ValueError(f"Cannot derive source_id from filename: {path.name}")
    return f"cmu:{parts[0]}:{parts[1]}"


def relative_path_or_none(path: Path, root: Path) -> str | None:
    """Return a POSIX relative path when path is under root."""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return None


def source_relative_path(args: argparse.Namespace) -> str | None:
    """Return the source BVH path used by catalog metadata."""
    if args.source_relative_path:
        return args.source_relative_path.replace("\\", "/")
    return (
        relative_path_or_none(args.input, CMU_DATA_ROOT)
        or relative_path_or_none(args.input, REPOSITORY_ROOT)
    )


def asset_slug(source_id: str) -> str:
    """Return the deterministic asset slug for one source ID."""
    return source_id.replace(":", "_")


def default_source_object_key(source_id: str, source_path: Path) -> str:
    """Return the deterministic source BVH object key."""
    return f"cmu/source/{asset_slug(source_id)}{source_path.suffix.lower()}"


def default_glb_object_key(source_id: str, animation_variant: str = "normal") -> str:
    """Return the deterministic GLB preview object key."""
    suffix = "" if animation_variant == "normal" else f"_{animation_variant}"
    return f"cmu/previews/{asset_slug(source_id)}{suffix}.glb"


def frame_count(frame_start: int, frame_end: int) -> int:
    """Return inclusive frame count."""
    return max(0, frame_end - frame_start + 1)


def duration_seconds(frame_start: int, frame_end: int, frame_rate: float) -> float | None:
    """Return animation duration in seconds for an inclusive frame range."""
    if frame_rate <= 0:
        return None
    return frame_count(frame_start, frame_end) / frame_rate


def retime_action(
    action: bpy.types.Action,
    source_fps: float,
    target_fps: float,
    frame_start: int,
) -> None:
    """Scale keyframes to the export FPS while preserving animation duration."""
    if target_fps <= 0:
        raise ValueError("--export-frame-rate must be positive")
    if source_fps <= 0:
        raise ValueError("--source-frame-rate must be positive")

    fcurves = action_fcurves(action)
    if not fcurves:
        raise RuntimeError("Target action has no editable F-curves")

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
            if child_values is not None:
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


def resolve_in_place_root_bone(
    target: bpy.types.Object,
    root_bone: str | None,
) -> str:
    """Return the target root bone used to remove horizontal root motion."""
    if root_bone:
        if root_bone not in target.pose.bones:
            raise RuntimeError(f"In-place root bone not found on target rig: {root_bone}")
        return root_bone

    for candidate in DEFAULT_IN_PLACE_ROOT_BONES:
        if candidate in target.pose.bones:
            return candidate

    root_bones = [bone.name for bone in target.pose.bones if bone.parent is None]
    if len(root_bones) == 1:
        return root_bones[0]

    raise RuntimeError(
        "Could not auto-detect in-place root bone. "
        "Pass --in-place-root-bone with the target rig root bone name."
    )


def create_in_place_action(
    action: bpy.types.Action,
    target: bpy.types.Object,
    *,
    root_bone: str | None,
    vertical_axis: str,
) -> InPlaceResult:
    """Copy an action and flatten horizontal root-bone location curves."""
    resolved_root_bone = resolve_in_place_root_bone(target, root_bone)
    vertical_axis = vertical_axis.upper()
    vertical_index = {"X": 0, "Y": 1, "Z": 2}[vertical_axis]
    root_location_path = target.pose.bones[resolved_root_bone].path_from_id("location")

    in_place_action = action.copy()
    in_place_action.name = f"{action.name}_in_place"
    neutralized = 0

    for fcurve in action_fcurves(in_place_action):
        if fcurve.data_path not in {root_location_path, "location"}:
            continue
        if fcurve.array_index == vertical_index:
            continue
        if len(fcurve.keyframe_points) == 0:
            continue

        value = fcurve.keyframe_points[0].co.y
        for keyframe in fcurve.keyframe_points:
            keyframe.co.y = value
            keyframe.handle_left.y = value
            keyframe.handle_right.y = value
        fcurve.update()
        neutralized += 1

    return InPlaceResult(
        action=in_place_action,
        root_bone=resolved_root_bone,
        vertical_axis=vertical_axis,
        neutralized_location_curves=neutralized,
    )


def sampled_frames(frame_start: int, frame_end: int, sample_count: int) -> list[int]:
    """Return stable inclusive frame samples across an animation range."""
    if frame_end < frame_start:
        return []

    frame_count = frame_end - frame_start + 1
    if frame_count <= sample_count:
        return list(range(frame_start, frame_end + 1))
    if sample_count <= 1:
        return [frame_start]

    return sorted(
        {
            round(frame_start + ((frame_end - frame_start) * index / (sample_count - 1)))
            for index in range(sample_count)
        }
    )


def pose_bone_bounds(target: bpy.types.Object) -> tuple[float, float, float, float, float, float]:
    """Return world-space bounds for the target armature pose bones."""
    coordinates = []
    target.update_from_editmode()
    bpy.context.view_layer.update()

    for bone in target.pose.bones:
        coordinates.append(target.matrix_world @ bone.head)
        coordinates.append(target.matrix_world @ bone.tail)

    if not coordinates:
        return (-1.0, 1.0, -1.0, 1.0, -1.0, 1.0)

    xs = [point.x for point in coordinates]
    ys = [point.y for point in coordinates]
    zs = [point.z for point in coordinates]
    return (min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))


def preview_bound_metadata(
    args: argparse.Namespace,
    result: RetargetResult,
    *,
    target: bpy.types.Object,
    vertical_axis: str,
    sample_count: int = DEFAULT_PREVIEW_BOUND_SAMPLE_COUNT,
) -> dict[str, Any]:
    """Sample animation bounds for frontend preview camera framing."""
    frame_start = export_frame_start(args, result)
    frame_end = result.export_frame_end
    frames = sampled_frames(frame_start, frame_end, sample_count)
    original_frame = bpy.context.scene.frame_current

    bounds: tuple[float, float, float, float, float, float] | None = None
    for frame in frames:
        bpy.context.scene.frame_set(frame)
        frame_bounds = pose_bone_bounds(target)
        if bounds is None:
            bounds = frame_bounds
            continue
        bounds = (
            min(bounds[0], frame_bounds[0]),
            max(bounds[1], frame_bounds[1]),
            min(bounds[2], frame_bounds[2]),
            max(bounds[3], frame_bounds[3]),
            min(bounds[4], frame_bounds[4]),
            max(bounds[5], frame_bounds[5]),
        )

    bpy.context.scene.frame_set(original_frame)
    if bounds is None:
        bounds = pose_bone_bounds(target)

    minimum = [bounds[0], bounds[2], bounds[4]]
    maximum = [bounds[1], bounds[3], bounds[5]]
    center = [(minimum[index] + maximum[index]) / 2.0 for index in range(3)]
    size = [maximum[index] - minimum[index] for index in range(3)]
    radius = max(size) / 2.0
    vertical_index = {"X": 0, "Y": 1, "Z": 2}[vertical_axis.upper()]

    return {
        "source": "target_pose_bones",
        "frame_start": frame_start,
        "frame_end": frame_end,
        "sampled_frame_count": len(frames),
        "min": minimum,
        "max": maximum,
        "center": center,
        "size": size,
        "radius": radius,
        "vertical_axis": vertical_axis.upper(),
        "height": size[vertical_index],
    }


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
        raise RuntimeError(f"gltfpack executable not found: {executable}") from error

    if result.returncode != 0:
        output = "\n".join(part for part in (result.stdout, result.stderr) if part)
        raise RuntimeError(f"gltfpack failed with exit code {result.returncode}\n{output}")
    return command


def export_frame_start(args: argparse.Namespace, result: RetargetResult) -> int:
    """Return the first frame included in exported GLB animations."""
    trim_start_frames = getattr(args, "trim_start_frames", 0)
    frame_start = result.export_frame_start + trim_start_frames
    if frame_start > result.export_frame_end:
        raise ValueError("--trim-start-frames removes every export frame")
    return frame_start


def configure_export_frame_range(args: argparse.Namespace, result: RetargetResult) -> None:
    """Set Blender's active export frame range."""
    scene = bpy.context.scene
    scene.frame_start = export_frame_start(args, result)
    scene.frame_end = result.export_frame_end
    scene.frame_set(scene.frame_start)


def export_glb_asset(
    *,
    args: argparse.Namespace,
    target: bpy.types.Object,
    glb_path: Path,
    result: RetargetResult | None = None,
    raw_glb: Path | None = None,
) -> Path | None:
    """Export one selected animation GLB and optionally optimize it."""
    if result is not None:
        configure_export_frame_range(args, result)

    if args.no_gltfpack:
        export_animation_glb(glb_path, target)
        return None

    raw_export_path = raw_glb or raw_glb_path_for(glb_path)
    export_animation_glb(raw_export_path, target)
    run_gltfpack(
        executable=args.gltfpack_path,
        input_path=raw_export_path,
        output_path=glb_path,
        extra_args=[*DEFAULT_GLTFPACK_ARGS, *args.gltfpack_arg],
    )
    if not args.keep_raw_glb:
        raw_export_path.unlink(missing_ok=True)
    return raw_export_path


def has_ignored_hand_bone(item: Any) -> bool:
    """Return true when a Rokoko bone-list item maps an unsupported hand bone."""
    for prop in item.bl_rna.properties:
        if prop.identifier == "rna_type":
            continue
        try:
            value = getattr(item, prop.identifier)
        except AttributeError:
            continue
        if isinstance(value, str) and value in IGNORED_HAND_BONES:
            return True
    return False


def remove_ignored_hand_bones() -> None:
    """Remove hand mappings known to fail for the CMU-to-X-Bot retarget."""
    bone_list = bpy.context.scene.rsl_retargeting_bone_list
    for index in range(len(bone_list) - 1, -1, -1):
        if has_ignored_hand_bone(bone_list[index]):
            bone_list.remove(index)


def retarget_animation(
    *,
    source: bpy.types.Object,
    target: bpy.types.Object,
    source_frame_rate: float,
    export_frame_rate: float,
) -> RetargetResult:
    """Retarget the source BVH action onto the loaded template target rig."""
    source_action = source.animation_data.action
    scene = bpy.context.scene
    scene.frame_start = int(source_action.frame_range[0])
    scene.frame_end = int(source_action.frame_range[1])
    source_frame_start = scene.frame_start
    source_frame_end = scene.frame_end
    scene.render.fps = int(round(source_frame_rate))

    scene.rsl_retargeting_armature_source = source
    scene.rsl_retargeting_armature_target = target

    # Use the template pose and imported BVH pose as Rokoko's reference pose.
    scene.rsl_retargeting_use_pose = "CURRENT"

    result = bpy.ops.rsl.build_bone_list()
    if "FINISHED" not in result:
        raise RuntimeError(f"Rokoko bone-list build failed: {sorted(result)}")

    remove_ignored_hand_bones()

    result = bpy.ops.rsl.retarget_animation()
    if "FINISHED" not in result:
        raise RuntimeError(f"Rokoko retarget failed: {sorted(result)}")

    if target.animation_data is None or target.animation_data.action is None:
        raise RuntimeError("Target armature has no retargeted action")

    target_action = target.animation_data.action
    ratio = export_frame_rate / source_frame_rate
    frame_start = scene.frame_start
    scene.frame_end = max(
        frame_start,
        int(round(frame_start + ((scene.frame_end - frame_start) * ratio))),
    )
    scene.render.fps = int(round(export_frame_rate))
    retime_action(
        target_action,
        source_fps=source_frame_rate,
        target_fps=export_frame_rate,
        frame_start=frame_start,
    )
    return RetargetResult(
        action=target_action,
        source_frame_start=source_frame_start,
        source_frame_end=source_frame_end,
        export_frame_start=frame_start,
        export_frame_end=scene.frame_end,
    )


def remove_source_data(source: bpy.types.Object, target_action: bpy.types.Action) -> None:
    """Remove imported source data so only the target action is exported."""
    bpy.data.objects.remove(source, do_unlink=True)
    for action in list(bpy.data.actions):
        if action != target_action:
            bpy.data.actions.remove(action)


def keep_only_action(action_to_keep: bpy.types.Action) -> None:
    """Remove other actions so GLB export contains only the selected clip."""
    for action in list(bpy.data.actions):
        if action != action_to_keep:
            bpy.data.actions.remove(action)


def write_metadata(
    path: Path,
    args: argparse.Namespace,
    result: RetargetResult,
    *,
    source_name: str,
    target: bpy.types.Object,
    variants: dict[str, dict[str, Any]] | None = None,
    raw_glb: Path | None = None,
) -> None:
    """Write source-level metadata with generated asset variants."""
    source_id = args.source_id or source_id_from_filename(args.input)
    gltfpack_args = [*DEFAULT_GLTFPACK_ARGS, *args.gltfpack_arg]
    if variants is None:
        variants = {
            "normal": variant_metadata(
                args,
                result,
                action=result.action,
                glb_path=args.glb,
                glb_object_key=args.glb_object_key,
                raw_glb=raw_glb,
                root_motion="preserved",
            )
        }

    metadata = {
        "source_id": source_id,
        "conversion_status": "converted",
        "conversion_version": args.conversion_version,
        "error_message": None,
        "source_sha256": sha256_file(args.input),
        "source_relative_path": source_relative_path(args),
        "source_object_key": args.source_object_key
        or default_source_object_key(source_id, args.input),
        "source_frame_start": result.source_frame_start,
        "source_frame_end": result.source_frame_end,
        "source_frame_count": frame_count(result.source_frame_start, result.source_frame_end),
        "source_frame_rate": args.source_frame_rate,
        "source_duration_seconds": duration_seconds(
            result.source_frame_start,
            result.source_frame_end,
            args.source_frame_rate,
        ),
        "retargeted": True,
        "source_rig": source_name,
        "target_rig": "mixamo_xbot",
        "target_rig_name": target.name,
        "scale": args.scale,
        "axis_forward": args.axis_forward,
        "axis_up": args.axis_up,
        "rotate_mode": args.rotate_mode,
        "trim_start_frames": getattr(args, "trim_start_frames", 0),
        "gltfpack": not args.no_gltfpack,
        "gltfpack_args": gltfpack_args if not args.no_gltfpack else [],
        "variants": variants,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


def variant_metadata(
    args: argparse.Namespace,
    result: RetargetResult,
    *,
    action: bpy.types.Action,
    glb_path: Path,
    root_motion: str,
    glb_object_key: str | None = None,
    raw_glb: Path | None = None,
    in_place_root_bone: str | None = None,
    in_place_vertical_axis: str | None = None,
    in_place_neutralized_location_curves: int | None = None,
    preview_bound: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return metadata for one exported GLB variant."""
    source_id = args.source_id or source_id_from_filename(args.input)
    animation_variant = "in_place" if root_motion == "horizontal_removed" else "normal"
    frame_start = export_frame_start(args, result)
    metadata = {
        "animation_variant": animation_variant,
        "root_motion": root_motion,
        "glb_relative_path": relative_path_or_none(glb_path, REPOSITORY_ROOT),
        "raw_glb_relative_path": (
            relative_path_or_none(raw_glb, REPOSITORY_ROOT)
            if raw_glb is not None and raw_glb.exists()
            else None
        ),
        "glb_object_key": glb_object_key
        or default_glb_object_key(source_id, animation_variant),
        "thumbnail_object_key": (
            args.thumbnail_object_key if animation_variant == "normal" else None
        ),
        "glb_sha256": sha256_file(glb_path),
        "raw_glb_sha256": sha256_file(raw_glb) if raw_glb and raw_glb.exists() else None,
        "thumbnail_sha256": None,
        "glb_size_bytes": glb_path.stat().st_size,
        "raw_glb_size_bytes": raw_glb.stat().st_size if raw_glb and raw_glb.exists() else None,
        "thumbnail_size_bytes": None,
        "export_frame_start": frame_start,
        "export_frame_end": result.export_frame_end,
        "export_frame_count": frame_count(frame_start, result.export_frame_end),
        "export_frame_rate": args.export_frame_rate,
        "export_duration_seconds": duration_seconds(
            frame_start,
            result.export_frame_end,
            args.export_frame_rate,
        ),
        "target_action_name": action.name,
        "in_place_root_bone": in_place_root_bone,
        "in_place_vertical_axis": in_place_vertical_axis,
        "in_place_neutralized_location_curves": in_place_neutralized_location_curves,
    }
    if preview_bound is not None:
        metadata["preview_bound"] = preview_bound
    return metadata


def main() -> None:
    """Run one headless BVH retarget and export."""
    args = parse_args()
    if not args.input.is_file():
        raise FileNotFoundError(f"BVH file does not exist: {args.input}")

    enable_addon("io_anim_bvh")
    enable_addon("io_scene_gltf2")
    if args.rokoko_addon:
        enable_addon(args.rokoko_addon)

    source = import_bvh(args)
    target = target_armature(args.target_rig_name)
    source_name = source.name
    result = retarget_animation(
        source=source,
        target=target,
        source_frame_rate=args.source_frame_rate,
        export_frame_rate=args.export_frame_rate,
    )
    remove_source_data(source, result.action)

    metadata_variants: dict[str, dict[str, Any]] = {}

    if args.variant in {"normal", "both"}:
        target.animation_data.action = result.action
        raw_export_path = export_glb_asset(
            args=args,
            target=target,
            glb_path=args.glb,
            result=result,
            raw_glb=raw_glb_path(args),
        )

        if args.metadata:
            metadata_variants["normal"] = variant_metadata(
                args,
                result,
                action=result.action,
                glb_path=args.glb,
                glb_object_key=args.glb_object_key,
                raw_glb=raw_export_path,
                root_motion="preserved",
            )

        print(f"SUCCESS: Exported {args.glb}")

    if args.variant in {"in-place", "both"}:
        in_place = create_in_place_action(
            result.action,
            target,
            root_bone=args.in_place_root_bone,
            vertical_axis=args.in_place_vertical_axis,
        )
        target.animation_data.action = in_place.action
        keep_only_action(in_place.action)
        in_place_raw_export_path = export_glb_asset(
            args=args,
            target=target,
            glb_path=args.in_place_glb,
            result=result,
        )

        if args.metadata:
            metadata_variants["in_place"] = variant_metadata(
                args,
                result,
                action=in_place.action,
                glb_path=args.in_place_glb,
                glb_object_key=args.in_place_glb_object_key,
                raw_glb=in_place_raw_export_path,
                root_motion="horizontal_removed",
                in_place_root_bone=in_place.root_bone,
                in_place_vertical_axis=in_place.vertical_axis,
                in_place_neutralized_location_curves=in_place.neutralized_location_curves,
                preview_bound=preview_bound_metadata(
                    args,
                    result,
                    target=target,
                    vertical_axis=in_place.vertical_axis,
                ),
            )

        print(f"SUCCESS: Exported in-place {args.in_place_glb}")

    if args.metadata:
        write_metadata(
            args.metadata,
            args,
            result,
            source_name=source_name,
            target=target,
            variants=metadata_variants,
        )
        print(f"SUCCESS: Wrote metadata {args.metadata}")


if __name__ == "__main__":
    main()

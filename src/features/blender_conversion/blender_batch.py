# Copyright (c) 2026 Yuancheng Li
# SPDX-License-Identifier: Apache-2.0

"""Retarget a small BVH batch in one headless Blender process.

Run with Blender, not the project Python interpreter:

    blender --background data/assets/templates/xbot_template.blend \
        --python src/features/blender_conversion/blender_batch.py -- \
        --limit 10 --no-gltfpack
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SOURCE_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MANIFEST = REPOSITORY_ROOT / "data/manifests/motions.json"
DEFAULT_INPUT_ROOT = REPOSITORY_ROOT / "data/source/cmu-mocap/data"
DEFAULT_OUTPUT_DIR = REPOSITORY_ROOT / "data/assets/previews"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

import bpy  # noqa: E402

from features.blender_conversion import blender_single as single  # noqa: E402


@dataclass(frozen=True, slots=True)
class TargetState:
    """Reusable target rig state captured from the template scene."""

    pose_matrices: dict[str, Any]
    frame_current: int


def blender_script_args() -> list[str]:
    """Return command-line arguments after Blender's ``--`` separator."""
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def parse_args() -> argparse.Namespace:
    """Parse batch conversion arguments."""
    parser = argparse.ArgumentParser(
        description="Retarget a limited BVH manifest batch in one Blender process."
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help=f"Joined motion manifest (default: {DEFAULT_MANIFEST}).",
    )
    parser.add_argument(
        "--input-root",
        type=Path,
        default=DEFAULT_INPUT_ROOT,
        help=f"CMU BVH data root (default: {DEFAULT_INPUT_ROOT}).",
    )
    parser.add_argument(
        "--glb-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output GLB directory (default: {DEFAULT_OUTPUT_DIR}).",
    )
    parser.add_argument(
        "--in-place-glb-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output in-place GLB directory (default: {DEFAULT_OUTPUT_DIR}).",
    )
    parser.add_argument(
        "--metadata-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output metadata directory (default: {DEFAULT_OUTPUT_DIR}).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Number of valid records to process (default: 10).",
    )
    parser.add_argument(
        "--variant",
        choices=("normal", "in-place", "both"),
        default="both",
        help="Which GLB variant to export (default: both).",
    )
    parser.add_argument(
        "--target-rig-name",
        default=single.DEFAULT_TARGET_RIG_NAME,
        help=f"Template target armature name (default: {single.DEFAULT_TARGET_RIG_NAME}).",
    )
    parser.add_argument(
        "--export-frame-rate",
        type=float,
        default=single.DEFAULT_EXPORT_FRAME_RATE,
        help=f"Export frame rate after retiming (default: {single.DEFAULT_EXPORT_FRAME_RATE}).",
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
        default=single.DEFAULT_SCALE,
        help=f"BVH import scale (default: {single.DEFAULT_SCALE}).",
    )
    parser.add_argument(
        "--axis-forward",
        default=single.DEFAULT_AXIS_FORWARD,
        help=f"BVH import forward axis (default: {single.DEFAULT_AXIS_FORWARD}).",
    )
    parser.add_argument(
        "--axis-up",
        default=single.DEFAULT_AXIS_UP,
        help=f"BVH import up axis (default: {single.DEFAULT_AXIS_UP}).",
    )
    parser.add_argument(
        "--rotate-mode",
        default=single.DEFAULT_ROTATE_MODE,
        help=f"BVH import rotation mode (default: {single.DEFAULT_ROTATE_MODE}).",
    )
    parser.add_argument(
        "--conversion-version",
        default=single.DEFAULT_CONVERSION_VERSION,
        help=f"Stable conversion version (default: {single.DEFAULT_CONVERSION_VERSION}).",
    )
    parser.add_argument(
        "--rokoko-addon",
        help="Optional Rokoko add-on module name to enable before retargeting.",
    )
    parser.add_argument(
        "--in-place-root-bone",
        help="Root bone whose horizontal location curves are flattened for in-place GLBs.",
    )
    parser.add_argument(
        "--in-place-vertical-axis",
        choices=("X", "Y", "Z"),
        default=single.DEFAULT_IN_PLACE_VERTICAL_AXIS,
        help=(
            "Root location axis to preserve for in-place GLBs "
            f"(default: {single.DEFAULT_IN_PLACE_VERTICAL_AXIS})."
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
        "--keep-raw-glb",
        action="store_true",
        help="Keep raw Blender GLBs after successful gltfpack optimization.",
    )
    args = parser.parse_args(blender_script_args())
    if args.trim_start_frames < 0:
        parser.error("--trim-start-frames must be zero or greater")
    args.manifest = args.manifest.resolve()
    args.input_root = args.input_root.resolve()
    args.glb_dir = args.glb_dir.resolve()
    args.in_place_glb_dir = args.in_place_glb_dir.resolve()
    args.metadata_dir = args.metadata_dir.resolve()
    return args


def read_motion_records(path: Path, limit: int) -> list[dict[str, Any]]:
    """Read the first valid manifest records up to limit."""
    if limit <= 0:
        raise ValueError("--limit must be positive")

    records = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError(f"Manifest is not a JSON array: {path}")

    selected = []
    for record in records:
        if record.get("validation_status") != "valid":
            continue
        selected.append(record)
        if len(selected) == limit:
            break
    return selected


def capture_target_state(target: bpy.types.Object) -> TargetState:
    """Capture the template target pose before batch retargeting mutates it."""
    return TargetState(
        pose_matrices={bone.name: bone.matrix_basis.copy() for bone in target.pose.bones},
        frame_current=bpy.context.scene.frame_current,
    )


def restore_target_state(target: bpy.types.Object, state: TargetState) -> None:
    """Restore the target rig pose and clear any previous retarget action."""
    if target.animation_data is not None:
        target.animation_data_clear()

    for bone in target.pose.bones:
        matrix = state.pose_matrices.get(bone.name)
        if matrix is not None:
            bone.matrix_basis = matrix.copy()

    bpy.context.scene.frame_set(state.frame_current)
    bpy.context.view_layer.update()


def remove_new_actions(persistent_actions: set[bpy.types.Action]) -> None:
    """Remove batch-created actions after one record finishes."""
    for action in list(bpy.data.actions):
        if action not in persistent_actions:
            bpy.data.actions.remove(action)


def keep_only_action(action_to_keep: bpy.types.Action) -> None:
    """Remove stale actions so GLB export contains only this record's retarget."""
    for action in list(bpy.data.actions):
        if action != action_to_keep:
            bpy.data.actions.remove(action)


def output_paths(args: argparse.Namespace, record: dict[str, Any]) -> tuple[Path, Path, Path]:
    """Return GLB and metadata paths for one manifest record."""
    slug = single.asset_slug(record["source_id"])
    return (
        args.glb_dir / f"{slug}.glb",
        args.in_place_glb_dir / f"{slug}_in_place.glb",
        args.metadata_dir / f"{slug}.json",
    )


def record_args(args: argparse.Namespace, record: dict[str, Any]) -> argparse.Namespace:
    """Build the single-file helper argument namespace for one record."""
    glb_path, in_place_glb_path, metadata_path = output_paths(args, record)
    return argparse.Namespace(
        input=(args.input_root / record["relative_path"]).resolve(),
        glb=glb_path.resolve(),
        in_place_glb=in_place_glb_path.resolve(),
        variant=args.variant,
        metadata=metadata_path.resolve(),
        source_id=record["source_id"],
        source_relative_path=record["relative_path"],
        source_object_key=None,
        glb_object_key=None,
        in_place_glb_object_key=None,
        thumbnail_object_key=None,
        conversion_version=args.conversion_version,
        target_rig_name=args.target_rig_name,
        source_frame_rate=record.get("frame_rate") or single.DEFAULT_SOURCE_FRAME_RATE,
        export_frame_rate=args.export_frame_rate,
        trim_start_frames=args.trim_start_frames,
        scale=args.scale,
        axis_forward=args.axis_forward,
        axis_up=args.axis_up,
        rotate_mode=args.rotate_mode,
        rokoko_addon=args.rokoko_addon,
        in_place_root_bone=args.in_place_root_bone,
        in_place_vertical_axis=args.in_place_vertical_axis,
        no_gltfpack=args.no_gltfpack,
        gltfpack_path=args.gltfpack_path,
        gltfpack_arg=args.gltfpack_arg,
        raw_glb=None,
        keep_raw_glb=args.keep_raw_glb,
    )


def remove_source_object(source: bpy.types.Object | None) -> None:
    """Remove an imported source object if it is still linked."""
    if source is not None and source.name in bpy.data.objects:
        bpy.data.objects.remove(source, do_unlink=True)


def write_failure_metadata(path: Path, single_args: argparse.Namespace, error: Exception) -> None:
    """Write minimal failure metadata for resumable batch runs."""
    source_id = single_args.source_id or single.source_id_from_filename(single_args.input)
    metadata = {
        "source_id": source_id,
        "conversion_status": "conversion_failed",
        "conversion_version": single_args.conversion_version,
        "error_message": str(error),
        "source_sha256": (
            single.sha256_file(single_args.input) if single_args.input.exists() else None
        ),
        "source_relative_path": single_args.source_relative_path,
        "source_object_key": single.default_source_object_key(source_id, single_args.input),
        "glb_object_key": single.default_glb_object_key(source_id),
        "thumbnail_object_key": single_args.thumbnail_object_key,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


def process_record(
    args: argparse.Namespace,
    record: dict[str, Any],
    target: bpy.types.Object,
    target_state: TargetState,
    persistent_actions: set[bpy.types.Action],
) -> bool:
    """Process one motion record and return true on success."""
    single_args = record_args(args, record)
    source = None

    try:
        restore_target_state(target, target_state)
        if not single_args.input.is_file():
            raise FileNotFoundError(f"BVH file does not exist: {single_args.input}")

        source = single.import_bvh(single_args)
        source_name = source.name
        result = single.retarget_animation(
            source=source,
            target=target,
            source_frame_rate=single_args.source_frame_rate,
            export_frame_rate=single_args.export_frame_rate,
        )
        remove_source_object(source)
        source = None
        metadata_variants = {}

        if single_args.variant in {"normal", "both"}:
            target.animation_data.action = result.action
            keep_only_action(result.action)
            raw_export_path = single.export_glb_asset(
                args=single_args,
                target=target,
                glb_path=single_args.glb,
                result=result,
                raw_glb=single.raw_glb_path(single_args),
            )
            metadata_variants["normal"] = single.variant_metadata(
                single_args,
                result,
                action=result.action,
                glb_path=single_args.glb,
                glb_object_key=single_args.glb_object_key,
                raw_glb=raw_export_path,
                root_motion="preserved",
            )
            print(f"SUCCESS: {record['source_id']} -> {single_args.glb}")

        if single_args.variant in {"in-place", "both"}:
            in_place = single.create_in_place_action(
                result.action,
                target,
                root_bone=single_args.in_place_root_bone,
                vertical_axis=single_args.in_place_vertical_axis,
            )
            target.animation_data.action = in_place.action
            keep_only_action(in_place.action)
            raw_export_path = single.export_glb_asset(
                args=single_args,
                target=target,
                glb_path=single_args.in_place_glb,
                result=result,
            )
            metadata_variants["in_place"] = single.variant_metadata(
                single_args,
                result,
                action=in_place.action,
                glb_path=single_args.in_place_glb,
                glb_object_key=single_args.in_place_glb_object_key,
                raw_glb=raw_export_path,
                root_motion="horizontal_removed",
                in_place_root_bone=in_place.root_bone,
                in_place_vertical_axis=in_place.vertical_axis,
                in_place_neutralized_location_curves=in_place.neutralized_location_curves,
                preview_bound=single.preview_bound_metadata(
                    single_args,
                    result,
                    target=target,
                    vertical_axis=in_place.vertical_axis,
                ),
            )
            print(f"SUCCESS: {record['source_id']} -> {single_args.in_place_glb}")

        single.write_metadata(
            single_args.metadata,
            single_args,
            result,
            source_name=source_name,
            target=target,
            variants=metadata_variants,
        )
        return True
    except Exception as error:
        print(f"ERROR: {record.get('source_id', '<unknown>')}: {error}")
        write_failure_metadata(single_args.metadata, single_args, error)
        return False
    finally:
        remove_source_object(source)
        restore_target_state(target, target_state)
        remove_new_actions(persistent_actions)


def main() -> None:
    """Run a limited one-process Blender retarget batch."""
    args = parse_args()
    records = read_motion_records(args.manifest, args.limit)
    if not records:
        raise SystemExit("No valid records selected")

    single.enable_addon("io_anim_bvh")
    single.enable_addon("io_scene_gltf2")
    if args.rokoko_addon:
        single.enable_addon(args.rokoko_addon)

    target = single.target_armature(args.target_rig_name)
    target_state = capture_target_state(target)
    persistent_actions = set(bpy.data.actions)

    success_count = 0
    for index, record in enumerate(records, start=1):
        print(f"[{index}/{len(records)}] Processing {record['source_id']}")
        if process_record(args, record, target, target_state, persistent_actions):
            success_count += 1

    failure_count = len(records) - success_count
    print(f"Batch complete: {success_count} succeeded, {failure_count} failed")
    if failure_count:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

# Copyright (c) 2026 Yuancheng Li
# SPDX-License-Identifier: Apache-2.0

"""Launch multiple isolated Blender batch conversion workers.

Run with the project Python interpreter, not Blender:

    python -m features.blender_conversion.blender_multi_batch \
        --template-blend data/assets/templates/xbot_template.blend \
        --workers 2 --variant both --limit 10
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path
from threading import Thread
from typing import Any, Callable, Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MANIFEST = REPOSITORY_ROOT / "data/manifests/motions.json"
DEFAULT_INPUT_ROOT = REPOSITORY_ROOT / "data/source/cmu-mocap/data"
DEFAULT_OUTPUT_DIR = REPOSITORY_ROOT / "data/assets/previews"
DEFAULT_BATCH_SCRIPT = Path(__file__).with_name("blender_batch.py")
DEFAULT_WORKERS = max(1, (os.cpu_count() or 2) // 2)

PopenFactory = Callable[..., subprocess.Popen[str]]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse multi-worker batch conversion arguments."""
    parser = argparse.ArgumentParser(
        description="Run multiple headless Blender batch conversion workers."
    )
    parser.add_argument(
        "--blender-path",
        default="blender",
        help="Blender executable path (default: blender).",
    )
    parser.add_argument(
        "--template-blend",
        type=Path,
        required=True,
        help="Template .blend containing the prepared target rig.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Number of Blender worker processes (default: {DEFAULT_WORKERS}).",
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
        default="Armature",
        help="Template target armature name (default: Armature).",
    )
    parser.add_argument(
        "--export-frame-rate",
        type=float,
        default=30.0,
        help="Export frame rate after retiming (default: 30.0).",
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
        default=1.0,
        help="BVH import scale (default: 1.0).",
    )
    parser.add_argument(
        "--axis-forward",
        default="-Z",
        help="BVH import forward axis (default: -Z).",
    )
    parser.add_argument(
        "--axis-up",
        default="Y",
        help="BVH import up axis (default: Y).",
    )
    parser.add_argument(
        "--rotate-mode",
        default="NATIVE",
        help="BVH import rotation mode (default: NATIVE).",
    )
    parser.add_argument(
        "--conversion-version",
        default="xbot-retarget-v1",
        help="Stable conversion version (default: xbot-retarget-v1).",
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
        default="Y",
        help="Root location axis to preserve for in-place GLBs (default: Y).",
    )
    parser.add_argument(
        "--skip-existing-metadata",
        action="store_true",
        help='Skip records with existing metadata marked "conversion_status": "converted".',
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

    args = parser.parse_args(argv)
    if args.workers <= 0:
        parser.error("--workers must be positive")
    if args.limit <= 0:
        parser.error("--limit must be positive")
    if args.trim_start_frames < 0:
        parser.error("--trim-start-frames must be zero or greater")

    args.template_blend = args.template_blend.resolve()
    args.manifest = args.manifest.resolve()
    args.input_root = args.input_root.resolve()
    args.glb_dir = args.glb_dir.resolve()
    args.in_place_glb_dir = args.in_place_glb_dir.resolve()
    args.metadata_dir = args.metadata_dir.resolve()
    return args


def asset_slug(source_id: str) -> str:
    """Return the deterministic asset slug for one source ID."""
    return source_id.replace(":", "_")


def metadata_path(args: argparse.Namespace, record: dict[str, Any]) -> Path:
    """Return the metadata path produced by blender_batch for one record."""
    return args.metadata_dir / f"{asset_slug(record['source_id'])}.json"


def is_converted_metadata(path: Path) -> bool:
    """Return true when metadata marks a record as successfully converted."""
    if not path.is_file():
        return False
    try:
        metadata = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(metadata, dict) and metadata.get("conversion_status") == "converted"


def select_records(args: argparse.Namespace) -> list[dict[str, Any]]:
    """Read valid manifest records and apply limit/resume filtering."""
    records = json.loads(args.manifest.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError(f"Manifest is not a JSON array: {args.manifest}")

    selected = []
    for record in records:
        if not isinstance(record, dict):
            raise ValueError(f"Manifest contains a non-object record: {args.manifest}")
        if record.get("validation_status") != "valid":
            continue
        if args.skip_existing_metadata and is_converted_metadata(metadata_path(args, record)):
            continue
        selected.append(record)
        if len(selected) == args.limit:
            break

    if not selected:
        raise ValueError("No valid records selected")
    return selected


def partition_records(records: Sequence[dict[str, Any]], worker_count: int) -> list[list[dict[str, Any]]]:
    """Split records into balanced contiguous worker shards."""
    if worker_count <= 0:
        raise ValueError("worker_count must be positive")
    shard_count = min(worker_count, len(records))
    base_size, extra = divmod(len(records), shard_count)

    shards = []
    offset = 0
    for index in range(shard_count):
        size = base_size + (1 if index < extra else 0)
        shards.append(list(records[offset : offset + size]))
        offset += size
    return shards


def write_shard_manifests(shards: Sequence[Sequence[dict[str, Any]]], directory: Path) -> list[Path]:
    """Write temporary JSON manifest shards and return their paths."""
    paths = []
    for index, shard in enumerate(shards, start=1):
        path = directory / f"shard_{index:03d}.json"
        path.write_text(json.dumps(list(shard), indent=2) + "\n", encoding="utf-8")
        paths.append(path)
    return paths


def worker_script_args(args: argparse.Namespace, shard_path: Path, shard_size: int) -> list[str]:
    """Return arguments passed after Blender's -- separator."""
    script_args = [
        "--manifest",
        str(shard_path),
        "--input-root",
        str(args.input_root),
        "--glb-dir",
        str(args.glb_dir),
        "--in-place-glb-dir",
        str(args.in_place_glb_dir),
        "--metadata-dir",
        str(args.metadata_dir),
        "--limit",
        str(shard_size),
        "--variant",
        args.variant,
        "--target-rig-name",
        args.target_rig_name,
        "--export-frame-rate",
        str(args.export_frame_rate),
        "--trim-start-frames",
        str(args.trim_start_frames),
        "--scale",
        str(args.scale),
        f"--axis-forward={args.axis_forward}",
        "--axis-up",
        args.axis_up,
        "--rotate-mode",
        args.rotate_mode,
        "--conversion-version",
        args.conversion_version,
        "--in-place-vertical-axis",
        args.in_place_vertical_axis,
        "--gltfpack-path",
        args.gltfpack_path,
    ]

    for gltfpack_arg in args.gltfpack_arg:
        script_args.extend(["--gltfpack-arg", gltfpack_arg])
    if args.rokoko_addon:
        script_args.extend(["--rokoko-addon", args.rokoko_addon])
    if args.in_place_root_bone:
        script_args.extend(["--in-place-root-bone", args.in_place_root_bone])
    if args.no_gltfpack:
        script_args.append("--no-gltfpack")
    if args.keep_raw_glb:
        script_args.append("--keep-raw-glb")

    return script_args


def worker_command(args: argparse.Namespace, shard_path: Path, shard_size: int) -> list[str]:
    """Return one complete Blender worker command."""
    return [
        args.blender_path,
        "--background",
        str(args.template_blend),
        "--python",
        str(DEFAULT_BATCH_SCRIPT),
        "--",
        *worker_script_args(args, shard_path, shard_size),
    ]


def stream_worker_output(worker_id: int, process: subprocess.Popen[str]) -> None:
    """Prefix and stream one worker's combined stdout/stderr."""
    if process.stdout is None:
        return
    for line in process.stdout:
        print(f"[worker {worker_id}] {line}", end="", flush=True)


def run_worker_commands(
    commands: Sequence[Sequence[str]],
    popen_factory: PopenFactory = subprocess.Popen,
) -> list[int]:
    """Start worker commands and return their exit codes."""
    processes: list[subprocess.Popen[str]] = []
    threads: list[Thread] = []

    for worker_id, command in enumerate(commands, start=1):
        print(f"[worker {worker_id}] starting: {' '.join(command)}", flush=True)
        process = popen_factory(
            list(command),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        processes.append(process)
        thread = Thread(target=stream_worker_output, args=(worker_id, process), daemon=True)
        thread.start()
        threads.append(thread)

    exit_codes = [process.wait() for process in processes]
    for thread in threads:
        thread.join()
    return exit_codes


def run(args: argparse.Namespace, popen_factory: PopenFactory = subprocess.Popen) -> int:
    """Run selected records across multiple Blender worker processes."""
    records = select_records(args)
    shards = partition_records(records, args.workers)

    with tempfile.TemporaryDirectory(prefix="cmu_mocap_blender_shards_") as temp_dir:
        shard_paths = write_shard_manifests(shards, Path(temp_dir))
        commands = [
            worker_command(args, shard_path, len(shard))
            for shard_path, shard in zip(shard_paths, shards, strict=True)
        ]
        exit_codes = run_worker_commands(commands, popen_factory=popen_factory)

    success_count = sum(1 for code in exit_codes if code == 0)
    failure_count = len(exit_codes) - success_count
    print(
        f"Multi-worker batch complete: {success_count} succeeded, {failure_count} failed",
        flush=True,
    )
    return 1 if failure_count else 0


def main() -> None:
    """CLI entrypoint."""
    try:
        raise SystemExit(run(parse_args()))
    except ValueError as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()

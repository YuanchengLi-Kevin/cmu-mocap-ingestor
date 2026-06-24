# Copyright (c) 2026 Yuancheng Li
# SPDX-License-Identifier: Apache-2.0

"""Extract structural and motion metadata from CMU BVH files."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from core.files import sha256_file
from core.json_io import write_json_array


FILENAME_PATTERN = re.compile(r"^(\d+)_(\d+)\.bvh$", re.IGNORECASE)
ROOT_PATTERN = re.compile(r"^ROOT\s+\S+")
JOINT_PATTERN = re.compile(r"^JOINT\s+\S+")
CHANNEL_PATTERN = re.compile(r"^CHANNELS\s+(\d+)(?:\s+.*)?$")
FRAMES_PATTERN = re.compile(r"^Frames:\s*(\d+)\s*$")
FRAME_TIME_PATTERN = re.compile(
    r"^Frame Time:\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*$"
)


def parse_bvh(path: Path, input_root: Path) -> dict[str, Any]:
    """Extract and validate metadata from one BVH file."""
    filename_match = FILENAME_PATTERN.fullmatch(path.name)
    if filename_match is None:
        raise ValueError(f"Unexpected BVH filename: {path.name}")

    subject_text, trial_text = filename_match.groups()
    hierarchy_seen = False
    motion_seen = False
    frame_count: int | None = None
    frame_time: float | None = None
    joint_count = 0
    channel_count = 0
    motion_row_count = 0
    motion_rows_valid = True
    errors: list[str] = []

    with path.open("r", encoding="utf-8-sig") as file_handle:
        for line_number, raw_line in enumerate(file_handle, start=1):
            line = raw_line.strip()
            if not line:
                continue

            if not motion_seen:
                if line == "HIERARCHY":
                    hierarchy_seen = True
                    continue
                if ROOT_PATTERN.fullmatch(line):
                    joint_count += 1
                    continue
                if JOINT_PATTERN.fullmatch(line):
                    joint_count += 1
                    continue
                channel_match = CHANNEL_PATTERN.fullmatch(line)
                if channel_match:
                    channel_count += int(channel_match.group(1))
                    continue
                if line == "MOTION":
                    motion_seen = True
                continue

            if frame_count is None:
                frames_match = FRAMES_PATTERN.fullmatch(line)
                if frames_match:
                    frame_count = int(frames_match.group(1))
                else:
                    errors.append(f"Invalid Frames declaration on line {line_number}")
                continue

            if frame_time is None:
                frame_time_match = FRAME_TIME_PATTERN.fullmatch(line)
                if frame_time_match:
                    frame_time = float(frame_time_match.group(1))
                else:
                    errors.append(f"Invalid Frame Time declaration on line {line_number}")
                continue

            values = line.split()
            motion_row_count += 1
            if len(values) != channel_count:
                motion_rows_valid = False
                continue
            try:
                for value in values:
                    float(value)
            except ValueError:
                motion_rows_valid = False

    if not hierarchy_seen:
        errors.append("Missing HIERARCHY declaration")
    if not motion_seen:
        errors.append("Missing MOTION declaration")
    if joint_count == 0:
        errors.append("No ROOT or JOINT declarations")
    if channel_count == 0:
        errors.append("No CHANNELS declarations")
    if frame_count is None:
        errors.append("Missing valid Frames declaration")
    elif frame_count != motion_row_count:
        errors.append(
            f"Declared {frame_count} frames but found {motion_row_count} motion rows"
        )
    if frame_time is None or frame_time <= 0:
        errors.append("Frame Time must be positive")
    if not motion_rows_valid:
        errors.append("Motion rows contain invalid values or channel counts")

    frame_rate = 1.0 / frame_time if frame_time is not None and frame_time > 0 else None
    duration_seconds = (
        frame_count * frame_time
        if frame_count is not None and frame_time is not None and frame_time > 0
        else None
    )

    return {
        "filename": path.name,
        "relative_path": path.relative_to(input_root).as_posix(),
        "subject_id": int(subject_text),
        "trial_id": int(trial_text),
        "sha256": sha256_file(path),
        "frame_count": frame_count,
        "frame_time": frame_time,
        "frame_rate": frame_rate,
        "duration_seconds": duration_seconds,
        "joint_count": joint_count,
        "channel_count": channel_count,
        "validation_status": "valid" if not errors else "invalid",
    }


def build_bvh_metadata(input_root: Path) -> list[dict[str, Any]]:
    """Parse every BVH beneath the input root in stable path order."""
    input_root = input_root.resolve()
    bvh_paths = sorted(input_root.rglob("*.bvh"))
    if not bvh_paths:
        raise ValueError(f"No BVH files found beneath {input_root}")

    records: list[dict[str, Any]] = []
    filenames: set[str] = set()
    for path in bvh_paths:
        if path.name in filenames:
            raise ValueError(f"Duplicate filename prevents an unambiguous join: {path.name}")
        filenames.add(path.name)
        records.append(parse_bvh(path, input_root))
    return records


def write_bvh_metadata_manifest(input_root: Path, output_path: Path) -> tuple[int, int]:
    """Write the BVH metadata manifest and return total and valid record counts."""
    records = build_bvh_metadata(input_root)
    write_json_array(output_path, records)
    valid_count = sum(record["validation_status"] == "valid" for record in records)
    return len(records), valid_count

# Copyright (c) 2026 Yuancheng Li
# SPDX-License-Identifier: Apache-2.0

"""Join CMU motion-index records with parsed BVH metadata."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.json_io import read_json_object_array, write_json_array_atomic


FILENAME_PATTERN = re.compile(r"^(\d+)_(\d+)\.bvh$")
INDEX_FIELDS = (
    "source_id",
    "subject_id",
    "trial_id",
    "filename",
    "subject_description",
    "description",
)
BVH_FIELDS = (
    "filename",
    "relative_path",
    "subject_id",
    "trial_id",
    "sha256",
    "frame_count",
    "frame_time",
    "frame_rate",
    "duration_seconds",
    "joint_count",
    "channel_count",
    "validation_status",
)


@dataclass(frozen=True, slots=True)
class JoinSummary:
    """Counts produced while joining the two source manifests."""

    total: int
    matched: int
    unmatched_bvh: int
    omitted_index: int


def _require_fields(record: dict[str, Any], fields: tuple[str, ...], source: Path) -> None:
    """Require a record to contain every field needed by the join."""
    missing = [field for field in fields if field not in record]
    if missing:
        raise ValueError(f"Record in {source} is missing fields: {', '.join(missing)}")


def _index_by_filename(
    records: list[dict[str, Any]], fields: tuple[str, ...], source: Path
) -> dict[str, dict[str, Any]]:
    """Validate records and create a case-sensitive filename lookup."""
    indexed: dict[str, dict[str, Any]] = {}
    for record in records:
        _require_fields(record, fields, source)
        filename = record["filename"]
        if not isinstance(filename, str) or not filename:
            raise ValueError(f"Record in {source} has an invalid filename")
        if filename in indexed:
            raise ValueError(f"Duplicate filename in {source}: {filename}")
        indexed[filename] = record
    return indexed


def _derive_identity(filename: str) -> tuple[str, int, int]:
    """Derive source, subject, and trial identifiers from a BVH filename."""
    match = FILENAME_PATTERN.fullmatch(filename)
    if match is None:
        raise ValueError(f"Cannot derive identifiers from filename: {filename}")
    subject_text, trial_text = match.groups()
    return f"cmu:{subject_text}:{trial_text}", int(subject_text), int(trial_text)


def _join_record(
    bvh_record: dict[str, Any], index_record: dict[str, Any] | None
) -> dict[str, Any]:
    """Create one final manifest record."""
    filename = bvh_record["filename"]
    derived_source_id, derived_subject_id, derived_trial_id = _derive_identity(filename)

    if bvh_record["subject_id"] != derived_subject_id:
        raise ValueError(f"BVH subject_id conflicts with filename: {filename}")
    if bvh_record["trial_id"] != derived_trial_id:
        raise ValueError(f"BVH trial_id conflicts with filename: {filename}")

    if index_record is None:
        source_id = derived_source_id
        subject_description = None
        description = None
    else:
        if index_record["subject_id"] != bvh_record["subject_id"]:
            raise ValueError(f"Conflicting subject_id for {filename}")
        if index_record["trial_id"] != bvh_record["trial_id"]:
            raise ValueError(f"Conflicting trial_id for {filename}")
        source_id = index_record["source_id"]
        subject_description = index_record["subject_description"]
        description = index_record["description"]

    return {
        "source_id": source_id,
        "subject_id": bvh_record["subject_id"],
        "trial_id": bvh_record["trial_id"],
        "filename": filename,
        "subject_description": subject_description,
        "description": description,
        "frame_count": bvh_record["frame_count"],
        "frame_time": bvh_record["frame_time"],
        "frame_rate": bvh_record["frame_rate"],
        "duration_seconds": bvh_record["duration_seconds"],
        "joint_count": bvh_record["joint_count"],
        "channel_count": bvh_record["channel_count"],
        "sha256": bvh_record["sha256"],
        "validation_status": bvh_record["validation_status"],
        "relative_path": bvh_record["relative_path"],
    }


def join_records(
    motion_index_records: list[dict[str, Any]],
    bvh_metadata_records: list[dict[str, Any]],
    *,
    motion_index_source: Path = Path("motion_index.json"),
    bvh_metadata_source: Path = Path("bvh_metadata.json"),
) -> tuple[list[dict[str, Any]], JoinSummary]:
    """BVH-left join two validated record collections by exact filename."""
    index_by_filename = _index_by_filename(
        motion_index_records, INDEX_FIELDS, motion_index_source
    )
    _index_by_filename(bvh_metadata_records, BVH_FIELDS, bvh_metadata_source)

    joined: list[dict[str, Any]] = []
    matched_filenames: set[str] = set()
    source_ids: set[str] = set()
    for bvh_record in bvh_metadata_records:
        filename = bvh_record["filename"]
        index_record = index_by_filename.get(filename)
        if index_record is not None:
            matched_filenames.add(filename)
        joined_record = _join_record(bvh_record, index_record)
        source_id = joined_record["source_id"]
        if source_id in source_ids:
            raise ValueError(f"Duplicate source_id in joined manifest: {source_id}")
        source_ids.add(source_id)
        joined.append(joined_record)

    matched = len(matched_filenames)
    summary = JoinSummary(
        total=len(joined),
        matched=matched,
        unmatched_bvh=len(joined) - matched,
        omitted_index=len(index_by_filename) - matched,
    )
    return joined, summary


def build_joined_manifest(
    motion_index_path: Path,
    bvh_metadata_path: Path,
    output_path: Path,
) -> JoinSummary:
    """Join source manifests, atomically write the result, and return counts."""
    motion_index_records = read_json_object_array(motion_index_path)
    bvh_metadata_records = read_json_object_array(bvh_metadata_path)
    joined, summary = join_records(
        motion_index_records,
        bvh_metadata_records,
        motion_index_source=motion_index_path,
        bvh_metadata_source=bvh_metadata_path,
    )
    write_json_array_atomic(output_path, joined)
    return summary

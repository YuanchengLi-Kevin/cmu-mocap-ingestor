# Copyright (c) 2026 Yuancheng Li
# SPDX-License-Identifier: Apache-2.0

"""Tests for joining motion-index and BVH metadata records."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from features.motion_manifest import build_joined_manifest, join_records


def index_record(filename: str = "01_01.bvh") -> dict[str, object]:
    """Return one complete motion-index record."""
    return {
        "source_id": "cmu:01:01",
        "subject_id": 1,
        "trial_id": 1,
        "filename": filename,
        "subject_description": "playground",
        "description": "forward jumps",
    }


def bvh_record(
    filename: str = "01_01.bvh", subject_id: int = 1, trial_id: int = 1
) -> dict[str, object]:
    """Return one complete BVH metadata record."""
    return {
        "filename": filename,
        "relative_path": f"001/{filename}",
        "subject_id": subject_id,
        "trial_id": trial_id,
        "sha256": "a" * 64,
        "frame_count": 438,
        "frame_time": 0.008333,
        "frame_rate": 120.0048,
        "duration_seconds": 3.649854,
        "joint_count": 31,
        "channel_count": 96,
        "validation_status": "valid",
    }


def write_json(path: Path, value: object) -> None:
    """Write a compact test JSON document."""
    path.write_text(json.dumps(value), encoding="utf-8")


def test_join_includes_matches_and_bvh_only_records() -> None:
    """A BVH-left join retains unmatched files with nullable descriptions."""
    unmatched = bvh_record("63_02.bvh", 63, 2)
    records, summary = join_records([index_record()], [bvh_record(), unmatched])

    assert summary.total == 2
    assert summary.matched == 1
    assert summary.unmatched_bvh == 1
    assert summary.omitted_index == 0
    assert records[0]["description"] == "forward jumps"
    assert records[1]["source_id"] == "cmu:63:02"
    assert records[1]["subject_description"] is None
    assert records[1]["description"] is None


def test_join_counts_index_only_records() -> None:
    """Index entries without BVHs are omitted and counted."""
    records, summary = join_records([index_record()], [])

    assert records == []
    assert summary.omitted_index == 1


def test_join_rejects_duplicate_filenames() -> None:
    """Duplicate join keys are rejected instead of silently overwritten."""
    with pytest.raises(ValueError, match="Duplicate filename"):
        join_records([index_record(), index_record()], [bvh_record()])


def test_join_rejects_conflicting_identifiers() -> None:
    """Matching filenames cannot conceal conflicting subject or trial IDs."""
    conflicting = index_record()
    conflicting["subject_id"] = 2

    with pytest.raises(ValueError, match="Conflicting subject_id"):
        join_records([conflicting], [bvh_record()])


def test_build_manifest_writes_deterministic_json(tmp_path: Path) -> None:
    """The file API preserves BVH order and emits a JSON array."""
    index_path = tmp_path / "motion_index.json"
    bvh_path = tmp_path / "bvh_metadata.json"
    output_path = tmp_path / "motions.json"
    write_json(index_path, [index_record()])
    write_json(
        bvh_path,
        [bvh_record("63_02.bvh", 63, 2), bvh_record()],
    )

    summary = build_joined_manifest(index_path, bvh_path, output_path)
    output = json.loads(output_path.read_text(encoding="utf-8"))

    assert summary.total == 2
    assert [record["filename"] for record in output] == ["63_02.bvh", "01_01.bvh"]


@pytest.mark.parametrize("value", [{"filename": "01_01.bvh"}, ["not an object"]])
def test_build_manifest_rejects_invalid_json_shape(tmp_path: Path, value: object) -> None:
    """Manifest roots and elements must use the documented JSON shape."""
    index_path = tmp_path / "motion_index.json"
    bvh_path = tmp_path / "bvh_metadata.json"
    write_json(index_path, value)
    write_json(bvh_path, [])

    with pytest.raises(ValueError):
        build_joined_manifest(index_path, bvh_path, tmp_path / "motions.json")

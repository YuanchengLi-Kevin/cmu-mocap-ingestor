# Copyright (c) 2026 Yuancheng Li
# SPDX-License-Identifier: Apache-2.0

"""Tests for BVH structural and motion metadata."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from features.bvh_metadata import (
    build_bvh_metadata,
    parse_bvh,
    write_bvh_metadata_manifest,
)


def bvh_text(*, frames: int = 2, frame_time: str = "0.5", rows: str | None = None) -> str:
    """Return a minimal BVH with one root and six channels."""
    motion_rows = rows if rows is not None else "0 0 0 0 0 0\n1 2 3 4 5 6"
    return (
        "HIERARCHY\n"
        "ROOT Hips\n"
        "{\n"
        "  CHANNELS 6 Xposition Yposition Zposition Zrotation Xrotation Yrotation\n"
        "}\n"
        "MOTION\n"
        f"Frames: {frames}\n"
        f"Frame Time: {frame_time}\n"
        f"{motion_rows}\n"
    )


def write_bvh(path: Path, **kwargs: object) -> None:
    """Create a parent directory and write a minimal BVH."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(bvh_text(**kwargs), encoding="utf-8")


def test_parse_bvh_returns_valid_structural_and_timing_metadata(tmp_path: Path) -> None:
    """A valid BVH produces identity, integrity, hierarchy, and timing fields."""
    root = tmp_path / "data"
    path = root / "001" / "01_02.bvh"
    write_bvh(path)

    record = parse_bvh(path, root)

    assert record["filename"] == "01_02.bvh"
    assert record["relative_path"] == "001/01_02.bvh"
    assert (record["subject_id"], record["trial_id"]) == (1, 2)
    assert record["frame_count"] == 2
    assert record["frame_rate"] == 2.0
    assert record["duration_seconds"] == 1.0
    assert record["joint_count"] == 1
    assert record["channel_count"] == 6
    assert record["source_size_bytes"] == path.stat().st_size
    assert len(record["sha256"]) == 64
    assert record["validation_status"] == "valid"


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"frames": 3}, {"frame_count": 3}),
        ({"frame_time": "0"}, {"frame_rate": None, "duration_seconds": None}),
        ({"rows": "0 0\nnot numeric data here"}, {}),
    ],
)
def test_parse_bvh_marks_malformed_motion_invalid(
    tmp_path: Path,
    kwargs: dict[str, object],
    expected: dict[str, object],
) -> None:
    """Frame counts, positive timing, channel widths, and numeric values are validated."""
    root = tmp_path / "data"
    path = root / "01_01.bvh"
    write_bvh(path, **kwargs)

    record = parse_bvh(path, root)

    assert record["validation_status"] == "invalid"
    for key, value in expected.items():
        assert record[key] == value


def test_parse_bvh_rejects_unexpected_filename(tmp_path: Path) -> None:
    """Only subject_trial filenames can supply stable identities."""
    path = tmp_path / "walk.bvh"
    path.write_text(bvh_text(), encoding="utf-8")

    with pytest.raises(ValueError, match="Unexpected BVH filename"):
        parse_bvh(path, tmp_path)


def test_build_bvh_metadata_is_recursive_and_stably_sorted(tmp_path: Path) -> None:
    """Recursive discovery returns records in stable path order."""
    write_bvh(tmp_path / "002" / "02_01.bvh")
    write_bvh(tmp_path / "001" / "01_01.bvh")

    records = build_bvh_metadata(tmp_path)

    assert [record["relative_path"] for record in records] == [
        "001/01_01.bvh",
        "002/02_01.bvh",
    ]


def test_build_bvh_metadata_rejects_duplicate_basenames(tmp_path: Path) -> None:
    """Duplicate filenames cannot be joined unambiguously later."""
    write_bvh(tmp_path / "a" / "01_01.bvh")
    write_bvh(tmp_path / "b" / "01_01.bvh")

    with pytest.raises(ValueError, match="Duplicate filename"):
        build_bvh_metadata(tmp_path)


def test_build_bvh_metadata_rejects_empty_tree(tmp_path: Path) -> None:
    """An empty source tree is reported instead of producing an empty snapshot."""
    with pytest.raises(ValueError, match="No BVH files"):
        build_bvh_metadata(tmp_path)


def test_write_bvh_metadata_manifest_reports_valid_count(tmp_path: Path) -> None:
    """The file API writes all records and separately counts valid inputs."""
    write_bvh(tmp_path / "source" / "01_01.bvh")
    write_bvh(tmp_path / "source" / "01_02.bvh", frames=3)
    output = tmp_path / "manifest.json"

    total, valid = write_bvh_metadata_manifest(tmp_path / "source", output)

    assert (total, valid) == (2, 1)
    assert len(json.loads(output.read_text(encoding="utf-8"))) == 2

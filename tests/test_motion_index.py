# Copyright (c) 2026 Yuancheng Li
# SPDX-License-Identifier: Apache-2.0

"""Tests for parsing the CMU motion index."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from features.motion_index import parse_index, write_motion_index_manifest


def write_index(path: Path, text: str) -> None:
    """Write a test motion index."""
    path.write_text(text, encoding="utf-8")


def test_parse_index_extracts_subjects_and_ignores_other_lines(tmp_path: Path) -> None:
    """Subject headings provide descriptions for their animation records."""
    path = tmp_path / "index.txt"
    write_index(
        path,
        "\ufeffCMU Motion Capture Database\n"
        "Subject #1 (walking and jumping)\n"
        "1_1 walk forward\n"
        "unrelated text\n"
        "1_02 jump in place\n",
    )

    records = parse_index(path)

    assert records == [
        {
            "source_id": "cmu:1:1",
            "subject_id": 1,
            "trial_id": 1,
            "filename": "1_1.bvh",
            "subject_description": "walking and jumping",
            "description": "walk forward",
        },
        {
            "source_id": "cmu:1:02",
            "subject_id": 1,
            "trial_id": 2,
            "filename": "1_02.bvh",
            "subject_description": "walking and jumping",
            "description": "jump in place",
        },
    ]


def test_parse_index_rejects_animation_before_subject(tmp_path: Path) -> None:
    """Animations cannot silently lose their subject description."""
    path = tmp_path / "index.txt"
    write_index(path, "1_1 walk forward\n")

    with pytest.raises(ValueError, match="before a subject heading"):
        parse_index(path)


def test_parse_index_rejects_heading_subject_mismatch(tmp_path: Path) -> None:
    """Animation identifiers must agree with the active subject heading."""
    path = tmp_path / "index.txt"
    write_index(path, "Subject #1 (walk)\n2_1 walk forward\n")

    with pytest.raises(ValueError, match="does not match subject heading"):
        parse_index(path)


def test_parse_index_rejects_input_without_animations(tmp_path: Path) -> None:
    """A heading-only input is not a useful manifest."""
    path = tmp_path / "index.txt"
    write_index(path, "Subject #1 (walk)\n")

    with pytest.raises(ValueError, match="No animation records"):
        parse_index(path)


def test_write_motion_index_manifest_returns_count(tmp_path: Path) -> None:
    """The file API writes parsed records and reports their count."""
    source = tmp_path / "index.txt"
    output = tmp_path / "nested" / "motion_index.json"
    write_index(source, "Subject #1 (walk)\n1_1 walk forward\n")

    count = write_motion_index_manifest(source, output)

    assert count == 1
    assert json.loads(output.read_text(encoding="utf-8"))[0]["source_id"] == "cmu:1:1"

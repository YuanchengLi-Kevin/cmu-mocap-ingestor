# Copyright (c) 2026 Yuancheng Li
# SPDX-License-Identifier: Apache-2.0

"""Parse the CMU motion index and write its JSON manifest."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from core.json_io import write_json_array


SUBJECT_PATTERN = re.compile(r"^Subject #(\d+) \((.+)\)$")
ANIMATION_PATTERN = re.compile(r"^(\d+)_(\d+)\s+(.+)$")


def parse_index(index_path: Path) -> list[dict[str, Any]]:
    """Parse animation records from a CMU motion index file."""
    records: list[dict[str, Any]] = []
    current_subject_id: int | None = None
    current_subject_description: str | None = None

    for line_number, raw_line in enumerate(
        index_path.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        line = raw_line.strip()

        subject_match = SUBJECT_PATTERN.fullmatch(line)
        if subject_match:
            current_subject_id = int(subject_match.group(1))
            current_subject_description = subject_match.group(2)
            continue

        animation_match = ANIMATION_PATTERN.fullmatch(line)
        if not animation_match:
            continue

        subject_text, trial_text, description = animation_match.groups()
        subject_id = int(subject_text)
        trial_id = int(trial_text)

        if current_subject_id is None or current_subject_description is None:
            raise ValueError(f"Animation appears before a subject heading on line {line_number}")
        if subject_id != current_subject_id:
            raise ValueError(
                f"Animation subject {subject_id} does not match subject heading "
                f"{current_subject_id} on line {line_number}"
            )

        animation_name = f"{subject_text}_{trial_text}"
        records.append(
            {
                "source_id": f"cmu:{subject_text}:{trial_text}",
                "subject_id": subject_id,
                "trial_id": trial_id,
                "filename": f"{animation_name}.bvh",
                "subject_description": current_subject_description,
                "description": description,
            }
        )

    if not records:
        raise ValueError(f"No animation records found in {index_path}")

    return records


def write_motion_index_manifest(index_path: Path, output_path: Path) -> int:
    """Parse a CMU index, write its JSON manifest, and return the record count."""
    records = parse_index(index_path)
    write_json_array(output_path, records)
    return len(records)

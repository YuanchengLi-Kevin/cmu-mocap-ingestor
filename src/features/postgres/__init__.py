# Copyright (c) 2026 Yuancheng Li
# SPDX-License-Identifier: Apache-2.0

"""Import the joined CMU motion manifest into PostgreSQL."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import psycopg

from core.json_io import read_json_object_array


MOTION_FIELDS = (
    "source_id",
    "subject_id",
    "trial_id",
    "filename",
    "subject_description",
    "description",
    "frame_count",
    "frame_time",
    "frame_rate",
    "duration_seconds",
    "joint_count",
    "channel_count",
    "sha256",
    "validation_status",
    "relative_path",
)

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS public.motions (
    source_id TEXT PRIMARY KEY,
    subject_id INTEGER NOT NULL,
    trial_id INTEGER NOT NULL,
    filename TEXT NOT NULL UNIQUE,
    subject_description TEXT,
    description TEXT,
    frame_count INTEGER,
    frame_time DOUBLE PRECISION,
    frame_rate DOUBLE PRECISION,
    duration_seconds DOUBLE PRECISION,
    joint_count INTEGER,
    channel_count INTEGER,
    sha256 TEXT NOT NULL,
    validation_status TEXT NOT NULL
        CHECK (validation_status IN ('valid', 'invalid')),
    relative_path TEXT NOT NULL
)
"""

UPSERT_SQL = """
INSERT INTO public.motions (
    source_id,
    subject_id,
    trial_id,
    filename,
    subject_description,
    description,
    frame_count,
    frame_time,
    frame_rate,
    duration_seconds,
    joint_count,
    channel_count,
    sha256,
    validation_status,
    relative_path
) VALUES (
    %s, %s, %s, %s, %s,
    %s, %s, %s, %s, %s,
    %s, %s, %s, %s, %s
)
ON CONFLICT (source_id) DO UPDATE SET
    subject_id = EXCLUDED.subject_id,
    trial_id = EXCLUDED.trial_id,
    filename = EXCLUDED.filename,
    subject_description = EXCLUDED.subject_description,
    description = EXCLUDED.description,
    frame_count = EXCLUDED.frame_count,
    frame_time = EXCLUDED.frame_time,
    frame_rate = EXCLUDED.frame_rate,
    duration_seconds = EXCLUDED.duration_seconds,
    joint_count = EXCLUDED.joint_count,
    channel_count = EXCLUDED.channel_count,
    sha256 = EXCLUDED.sha256,
    validation_status = EXCLUDED.validation_status,
    relative_path = EXCLUDED.relative_path
"""


def _read_motion_manifest(path: Path) -> list[dict[str, Any]]:
    """Read and validate the joined manifest shape."""
    value = read_json_object_array(path)
    records: list[dict[str, Any]] = []
    for record in value:
        missing = [field for field in MOTION_FIELDS if field not in record]
        if missing:
            raise ValueError(f"Record in {path} is missing fields: {', '.join(missing)}")
        if record["validation_status"] not in {"valid", "invalid"}:
            raise ValueError(
                f"Invalid validation_status for {record.get('filename', '<unknown>')}"
            )
        records.append(record)
    return records


def _record_values(record: dict[str, Any]) -> tuple[Any, ...]:
    """Convert one manifest record to SQL parameter order."""
    return tuple(record[field] for field in MOTION_FIELDS)


def import_motion_manifest(database_url: str, manifest_path: Path) -> int:
    """Create the motions table and atomically upsert every manifest record."""
    if not database_url.strip():
        raise ValueError("database_url must not be empty")

    records = _read_motion_manifest(manifest_path)
    connection = psycopg.connect(database_url)
    try:
        with connection.cursor() as cursor:
            cursor.execute(CREATE_TABLE_SQL)
            if records:
                cursor.executemany(UPSERT_SQL, [_record_values(record) for record in records])
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return len(records)

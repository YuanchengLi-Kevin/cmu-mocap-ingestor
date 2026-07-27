# Copyright (c) 2026 Yuancheng Li
# SPDX-License-Identifier: Apache-2.0

"""Import the joined CMU motion manifest into PostgreSQL."""

from __future__ import annotations

import math
import re
from datetime import datetime
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

ASSET_INPUT_FIELDS = (
    "source_id",
    "source_sha256",
    "conversion_version",
    "playback_glb_object_key",
    "playback_glb_sha256",
    "playback_glb_size_bytes",
    "preview_glb_object_key",
    "preview_glb_sha256",
    "preview_glb_size_bytes",
    "preview_floor_y",
    "preview_ceiling_y",
    "uploaded_at",
)

ASSET_FIELDS = tuple(field for field in ASSET_INPUT_FIELDS if field != "source_sha256")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")

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

CREATE_ASSET_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS public.motion_assets (
    source_id TEXT PRIMARY KEY
        REFERENCES public.motions(source_id) ON DELETE CASCADE,
    conversion_version TEXT NOT NULL,
    playback_glb_object_key TEXT NOT NULL UNIQUE,
    playback_glb_sha256 TEXT NOT NULL,
    playback_glb_size_bytes BIGINT NOT NULL,
    preview_glb_object_key TEXT NOT NULL UNIQUE,
    preview_glb_sha256 TEXT NOT NULL,
    preview_glb_size_bytes BIGINT NOT NULL,
    preview_floor_y DOUBLE PRECISION,
    preview_ceiling_y DOUBLE PRECISION,
    uploaded_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
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

UPSERT_ASSET_SQL = """
INSERT INTO public.motion_assets (
    source_id,
    conversion_version,
    playback_glb_object_key,
    playback_glb_sha256,
    playback_glb_size_bytes,
    preview_glb_object_key,
    preview_glb_sha256,
    preview_glb_size_bytes,
    preview_floor_y,
    preview_ceiling_y,
    uploaded_at
) VALUES (
    %s, %s, %s, %s, %s, %s,
    %s, %s, %s, %s, %s
)
ON CONFLICT (source_id) DO UPDATE SET
    conversion_version = EXCLUDED.conversion_version,
    playback_glb_object_key = EXCLUDED.playback_glb_object_key,
    playback_glb_sha256 = EXCLUDED.playback_glb_sha256,
    playback_glb_size_bytes = EXCLUDED.playback_glb_size_bytes,
    preview_glb_object_key = EXCLUDED.preview_glb_object_key,
    preview_glb_sha256 = EXCLUDED.preview_glb_sha256,
    preview_glb_size_bytes = EXCLUDED.preview_glb_size_bytes,
    preview_floor_y = EXCLUDED.preview_floor_y,
    preview_ceiling_y = EXCLUDED.preview_ceiling_y,
    uploaded_at = EXCLUDED.uploaded_at,
    updated_at = now()
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


def _require_string(value: Any, field: str, source_id: str) -> str:
    """Return a required non-empty string."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{source_id} has invalid {field}")
    return value


def _require_sha256(value: Any, field: str, source_id: str) -> str:
    """Return a lowercase SHA-256 digest."""
    digest = _require_string(value, field, source_id)
    if SHA256_PATTERN.fullmatch(digest) is None:
        raise ValueError(f"{source_id} has invalid {field}")
    return digest


def _require_positive_int(value: Any, field: str, source_id: str) -> int:
    """Return a positive integer value."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{source_id} has invalid {field}")
    return value


def _optional_finite_number(value: Any, field: str, source_id: str) -> int | float | None:
    """Return an optional finite numeric value."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{source_id} has invalid {field}")
    return value


def _require_timestamp(value: Any, source_id: str) -> datetime:
    """Return a timezone-aware upload timestamp."""
    text = _require_string(value, "uploaded_at", source_id)
    try:
        timestamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{source_id} has invalid uploaded_at") from error
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError(f"{source_id} has invalid uploaded_at")
    return timestamp


def _read_asset_manifest(
    path: Path,
    motions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Read and validate the verified R2 asset manifest."""
    motion_by_id: dict[str, dict[str, Any]] = {}
    for motion in motions:
        source_id = motion["source_id"]
        if source_id in motion_by_id:
            raise ValueError(f"Duplicate motion source_id: {source_id}")
        motion_by_id[source_id] = motion

    records = read_json_object_array(path)
    validated: list[dict[str, Any]] = []
    source_ids: set[str] = set()
    object_keys: set[str] = set()
    for record in records:
        missing = [field for field in ASSET_INPUT_FIELDS if field not in record]
        if missing:
            raise ValueError(f"Record in {path} is missing fields: {', '.join(missing)}")

        source_id = _require_string(record["source_id"], "source_id", path.name)
        if source_id in source_ids:
            raise ValueError(f"Duplicate asset source_id: {source_id}")
        source_ids.add(source_id)

        motion = motion_by_id.get(source_id)
        if motion is None:
            raise ValueError(f"Asset has unknown source_id: {source_id}")
        if motion["validation_status"] != "valid":
            raise ValueError(f"Asset belongs to an invalid motion: {source_id}")

        source_sha256 = _require_sha256(
            record["source_sha256"], "source_sha256", source_id
        )
        if source_sha256 != motion["sha256"]:
            raise ValueError(f"{source_id} source SHA-256 does not match motions manifest")

        converted = dict(record)
        converted["conversion_version"] = _require_string(
            record["conversion_version"], "conversion_version", source_id
        )
        for role in ("playback", "preview"):
            key_field = f"{role}_glb_object_key"
            object_key = _require_string(record[key_field], key_field, source_id)
            if object_key in object_keys:
                raise ValueError(f"Duplicate GLB object key: {object_key}")
            object_keys.add(object_key)
            converted[key_field] = object_key

            sha_field = f"{role}_glb_sha256"
            converted[sha_field] = _require_sha256(record[sha_field], sha_field, source_id)
            size_field = f"{role}_glb_size_bytes"
            converted[size_field] = _require_positive_int(
                record[size_field], size_field, source_id
            )

        for field in ("preview_floor_y", "preview_ceiling_y"):
            converted[field] = _optional_finite_number(record[field], field, source_id)
        converted["uploaded_at"] = _require_timestamp(record["uploaded_at"], source_id)
        validated.append(converted)
    return validated


def _record_values(record: dict[str, Any]) -> tuple[Any, ...]:
    """Convert one manifest record to SQL parameter order."""
    return tuple(record[field] for field in MOTION_FIELDS)


def _asset_values(record: dict[str, Any]) -> tuple[Any, ...]:
    """Convert one asset record to SQL parameter order."""
    return tuple(record[field] for field in ASSET_FIELDS)


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


def import_catalog(
    database_url: str,
    motion_manifest_path: Path,
    asset_manifest_path: Path,
) -> tuple[int, int]:
    """Create catalog tables and atomically upsert motions and verified assets."""
    if not database_url.strip():
        raise ValueError("database_url must not be empty")

    motions = _read_motion_manifest(motion_manifest_path)
    assets = _read_asset_manifest(asset_manifest_path, motions)
    connection = psycopg.connect(database_url)
    try:
        with connection.cursor() as cursor:
            cursor.execute(CREATE_TABLE_SQL)
            cursor.execute(CREATE_ASSET_TABLE_SQL)
            if motions:
                cursor.executemany(UPSERT_SQL, [_record_values(record) for record in motions])
            if assets:
                cursor.executemany(
                    UPSERT_ASSET_SQL,
                    [_asset_values(record) for record in assets],
                )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return len(motions), len(assets)

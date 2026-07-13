# Copyright (c) 2026 Yuancheng Li
# SPDX-License-Identifier: Apache-2.0

"""Upload converted GLBs to R2 and emit a verified asset manifest."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.files import sha256_file
from core.json_io import read_json_object_array, write_json_array_atomic


SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class PreparedUpload:
    """Validated local files and their future manifest record."""

    record: dict[str, Any]
    playback_path: Path
    preview_path: Path


def _read_json_object(path: Path) -> dict[str, Any]:
    """Read one JSON object from a file."""
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid JSON in {path}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def _require_string(value: Any, field: str, source_id: str) -> str:
    """Return a required non-empty string field."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{source_id} has invalid {field}")
    return value


def _require_sha256(value: Any, field: str, source_id: str) -> str:
    """Return a required lowercase SHA-256 value."""
    digest = _require_string(value, field, source_id)
    if SHA256_PATTERN.fullmatch(digest) is None:
        raise ValueError(f"{source_id} has invalid {field}")
    return digest


def _require_positive_int(value: Any, field: str, source_id: str) -> int:
    """Return a required positive integer field."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{source_id} has invalid {field}")
    return value


def _local_glb(
    repository_root: Path,
    variant: dict[str, Any],
    source_id: str,
) -> tuple[Path, str, str, int]:
    """Validate one local GLB and return its upload fields."""
    relative_path = _require_string(
        variant.get("glb_relative_path"), "glb_relative_path", source_id
    )
    path = (repository_root / relative_path).resolve()
    if not path.is_relative_to(repository_root):
        raise ValueError(f"{source_id} GLB path escapes the repository: {relative_path}")
    if not path.is_file():
        raise ValueError(f"{source_id} GLB does not exist: {relative_path}")

    object_key = _require_string(variant.get("glb_object_key"), "glb_object_key", source_id)
    expected_sha256 = _require_sha256(variant.get("glb_sha256"), "glb_sha256", source_id)
    expected_size = _require_positive_int(
        variant.get("glb_size_bytes"), "glb_size_bytes", source_id
    )
    if path.stat().st_size != expected_size:
        raise ValueError(f"{source_id} GLB size does not match metadata: {relative_path}")
    if sha256_file(path) != expected_sha256:
        raise ValueError(f"{source_id} GLB SHA-256 does not match metadata: {relative_path}")
    return path, object_key, expected_sha256, expected_size


def prepare_uploads(
    repository_root: Path,
    motions_path: Path,
    metadata_dir: Path,
    limit: int | None = None,
) -> list[PreparedUpload]:
    """Validate selected conversion outputs before any R2 request is made."""
    repository_root = repository_root.resolve()
    motions = read_json_object_array(motions_path)
    motion_by_id: dict[str, dict[str, Any]] = {}
    for motion in motions:
        source_id = _require_string(motion.get("source_id"), "source_id", "motion record")
        if source_id in motion_by_id:
            raise ValueError(f"Duplicate motion source_id: {source_id}")
        motion_by_id[source_id] = motion

    metadata_paths = sorted(metadata_dir.glob("*.json"))
    if not metadata_paths:
        raise ValueError(f"No preview metadata found in {metadata_dir}")
    converted: list[tuple[Path, dict[str, Any]]] = []
    for path in metadata_paths:
        metadata = _read_json_object(path)
        if metadata.get("conversion_status") == "converted":
            converted.append((path, metadata))
    if limit is not None:
        if limit <= 0:
            raise ValueError("limit must be positive")
        converted = converted[:limit]
    if not converted:
        raise ValueError(f"No converted preview metadata found in {metadata_dir}")

    prepared: list[PreparedUpload] = []
    source_ids: set[str] = set()
    object_keys: set[str] = set()
    for metadata_path, metadata in converted:
        source_id = _require_string(metadata.get("source_id"), "source_id", metadata_path.name)
        if source_id in source_ids:
            raise ValueError(f"Duplicate converted source_id: {source_id}")
        source_ids.add(source_id)

        motion = motion_by_id.get(source_id)
        if motion is None:
            raise ValueError(f"Converted metadata has unknown source_id: {source_id}")
        if motion.get("validation_status") != "valid":
            raise ValueError(f"Converted metadata belongs to an invalid motion: {source_id}")
        source_sha256 = _require_sha256(
            metadata.get("source_sha256"), "source_sha256", source_id
        )
        if source_sha256 != motion.get("sha256"):
            raise ValueError(f"{source_id} source SHA-256 does not match motions manifest")
        if metadata.get("metadata_schema_version") != 2:
            raise ValueError(f"{source_id} must use preview metadata schema version 2")
        conversion_version = _require_string(
            metadata.get("conversion_version"), "conversion_version", source_id
        )

        variants = metadata.get("variants")
        if not isinstance(variants, dict):
            raise ValueError(f"{source_id} is missing variants")
        normal = variants.get("normal")
        in_place = variants.get("in_place")
        if not isinstance(normal, dict) or not isinstance(in_place, dict):
            raise ValueError(f"{source_id} is missing normal or in_place metadata")

        playback_path, playback_key, playback_sha256, playback_size = _local_glb(
            repository_root, normal, source_id
        )
        preview_path, preview_key, preview_sha256, preview_size = _local_glb(
            repository_root, in_place, source_id
        )
        for object_key in (playback_key, preview_key):
            if object_key in object_keys:
                raise ValueError(f"Duplicate GLB object key: {object_key}")
            object_keys.add(object_key)

        preview_frame = in_place.get("preview_frame")
        if preview_frame is not None and not isinstance(preview_frame, dict):
            raise ValueError(f"{source_id} has invalid preview_frame")
        preview_frame = preview_frame or {}
        record = {
            "source_id": source_id,
            "source_sha256": source_sha256,
            "conversion_version": conversion_version,
            "playback_glb_object_key": playback_key,
            "playback_glb_sha256": playback_sha256,
            "playback_glb_size_bytes": playback_size,
            "preview_glb_object_key": preview_key,
            "preview_glb_sha256": preview_sha256,
            "preview_glb_size_bytes": preview_size,
            "preview_floor_y": preview_frame.get("floor_y"),
            "preview_ceiling_y": preview_frame.get("ceiling_y"),
        }
        prepared.append(PreparedUpload(record, playback_path, preview_path))
    return prepared


def _upload_and_verify(
    client: Any,
    bucket: str,
    path: Path,
    object_key: str,
    sha256: str,
    size: int,
    *,
    source_id: str,
    source_sha256: str,
    asset_role: str,
    conversion_version: str,
) -> None:
    """Upload one GLB and verify its size and recorded digest through HEAD."""
    object_metadata = {
        "source_id": source_id,
        "source_sha256": source_sha256,
        "asset_role": asset_role,
        "conversion_version": conversion_version,
        "glb_sha256": sha256,
    }
    client.upload_file(
        str(path),
        bucket,
        object_key,
        ExtraArgs={"ContentType": "model/gltf-binary", "Metadata": object_metadata},
    )
    response = client.head_object(Bucket=bucket, Key=object_key)
    remote_metadata = response.get("Metadata", {})
    if response.get("ContentLength") != size or remote_metadata.get("glb_sha256") != sha256:
        raise RuntimeError(f"R2 verification failed for {object_key}")


def upload_prepared_assets(
    client: Any,
    bucket: str,
    prepared: list[PreparedUpload],
    output_path: Path,
) -> int:
    """Upload every prepared asset pair and atomically write the manifest."""
    records: list[dict[str, Any]] = []
    total = len(prepared)
    for index, upload in enumerate(prepared, start=1):
        record = upload.record
        shared = {
            "source_id": record["source_id"],
            "source_sha256": record["source_sha256"],
            "conversion_version": record["conversion_version"],
        }
        _upload_and_verify(
            client,
            bucket,
            upload.playback_path,
            record["playback_glb_object_key"],
            record["playback_glb_sha256"],
            record["playback_glb_size_bytes"],
            asset_role="playback",
            **shared,
        )
        _upload_and_verify(
            client,
            bucket,
            upload.preview_path,
            record["preview_glb_object_key"],
            record["preview_glb_sha256"],
            record["preview_glb_size_bytes"],
            asset_role="preview",
            **shared,
        )
        verified = dict(record)
        verified["uploaded_at"] = (
            datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        )
        records.append(verified)
        print(f"Uploaded {index}/{total}: {record['source_id']}", flush=True)

    write_json_array_atomic(output_path, records)
    return len(records)

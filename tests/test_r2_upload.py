# Copyright (c) 2026 Yuancheng Li
# SPDX-License-Identifier: Apache-2.0

"""Tests for validating, uploading, and verifying R2 motion assets."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from features.r2_upload import PreparedUpload, prepare_uploads, upload_prepared_assets


def write_json(path: Path, value: object) -> None:
    """Write JSON after creating its parent directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def create_upload_inputs(root: Path) -> tuple[Path, Path, dict[str, Any]]:
    """Create one valid motion, metadata object, and pair of local GLBs."""
    motions_path = root / "data/manifests/motions.json"
    metadata_dir = root / "data/assets/previews"
    normal_path = metadata_dir / "cmu_01_01.glb"
    preview_path = metadata_dir / "cmu_01_01_in_place.glb"
    metadata_dir.mkdir(parents=True)
    normal_path.write_bytes(b"normal-glb")
    preview_path.write_bytes(b"preview-glb")
    source_sha = "a" * 64
    write_json(
        motions_path,
        [
            {
                "source_id": "cmu:01:01",
                "sha256": source_sha,
                "validation_status": "valid",
            }
        ],
    )
    metadata = {
        "metadata_schema_version": 2,
        "source_id": "cmu:01:01",
        "conversion_status": "converted",
        "conversion_version": "xbot-retarget-v1",
        "source_sha256": source_sha,
        "variants": {
            "normal": {
                "glb_relative_path": normal_path.relative_to(root).as_posix(),
                "glb_object_key": "cmu/previews/cmu_01_01.glb",
                "glb_sha256": hashlib.sha256(normal_path.read_bytes()).hexdigest(),
                "glb_size_bytes": normal_path.stat().st_size,
            },
            "in_place": {
                "glb_relative_path": preview_path.relative_to(root).as_posix(),
                "glb_object_key": "cmu/previews/cmu_01_01_in_place.glb",
                "glb_sha256": hashlib.sha256(preview_path.read_bytes()).hexdigest(),
                "glb_size_bytes": preview_path.stat().st_size,
                "preview_frame": {"floor_y": 0.0, "ceiling_y": 1.8},
            },
        },
    }
    write_json(metadata_dir / "cmu_01_01.json", metadata)
    return motions_path, metadata_dir, metadata


def test_prepare_uploads_validates_and_projects_manifest_record(tmp_path: Path) -> None:
    """Valid conversion output becomes one prepared playback/preview pair."""
    motions, metadata_dir, _ = create_upload_inputs(tmp_path)

    prepared = prepare_uploads(tmp_path, motions, metadata_dir)

    assert len(prepared) == 1
    assert prepared[0].playback_path.name == "cmu_01_01.glb"
    assert prepared[0].preview_path.name == "cmu_01_01_in_place.glb"
    assert prepared[0].record["preview_floor_y"] == 0.0
    assert prepared[0].record["preview_ceiling_y"] == 1.8


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda metadata: metadata.update(metadata_schema_version=1), "schema version 2"),
        (lambda metadata: metadata.update(source_sha256="b" * 64), "source SHA-256"),
        (
            lambda metadata: metadata["variants"]["normal"].update(glb_size_bytes=999),
            "size does not match",
        ),
        (
            lambda metadata: metadata["variants"]["normal"].update(glb_sha256="b" * 64),
            "SHA-256 does not match",
        ),
        (
            lambda metadata: metadata["variants"]["in_place"].update(
                glb_object_key="cmu/previews/cmu_01_01.glb"
            ),
            "Duplicate GLB object key",
        ),
    ],
)
def test_prepare_uploads_rejects_stale_or_ambiguous_assets(
    tmp_path: Path,
    change: Any,
    message: str,
) -> None:
    """Schema, source, local integrity, and object-key invariants are enforced."""
    motions, metadata_dir, metadata = create_upload_inputs(tmp_path)
    change(metadata)
    write_json(metadata_dir / "cmu_01_01.json", metadata)

    with pytest.raises(ValueError, match=message):
        prepare_uploads(tmp_path, motions, metadata_dir)


def test_prepare_uploads_rejects_repository_escape(tmp_path: Path) -> None:
    """Metadata cannot upload a local file outside the repository root."""
    motions, metadata_dir, metadata = create_upload_inputs(tmp_path)
    metadata["variants"]["normal"]["glb_relative_path"] = "../outside.glb"
    write_json(metadata_dir / "cmu_01_01.json", metadata)

    with pytest.raises(ValueError, match="escapes the repository"):
        prepare_uploads(tmp_path, motions, metadata_dir)


def test_prepare_uploads_rejects_nonpositive_limit(tmp_path: Path) -> None:
    """A limited upload must select at least one record."""
    motions, metadata_dir, _ = create_upload_inputs(tmp_path)

    with pytest.raises(ValueError, match="limit must be positive"):
        prepare_uploads(tmp_path, motions, metadata_dir, limit=0)


class FakeS3Client:
    """Capture uploads and return configurable HEAD verification data."""

    def __init__(self, *, bad_key: str | None = None) -> None:
        self.bad_key = bad_key
        self.uploaded: dict[str, dict[str, Any]] = {}

    def upload_file(
        self,
        path: str,
        bucket: str,
        key: str,
        ExtraArgs: dict[str, Any],
    ) -> None:
        self.uploaded[key] = {
            "path": Path(path),
            "bucket": bucket,
            "extra": ExtraArgs,
        }

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        upload = self.uploaded[Key]
        size = upload["path"].stat().st_size
        metadata = dict(upload["extra"]["Metadata"])
        if Key == self.bad_key:
            size += 1
        return {"ContentLength": size, "Metadata": metadata}


def prepared_pair(tmp_path: Path) -> PreparedUpload:
    """Return one upload pair with matching local integrity fields."""
    playback = tmp_path / "playback.glb"
    preview = tmp_path / "preview.glb"
    playback.write_bytes(b"playback")
    preview.write_bytes(b"preview")
    return PreparedUpload(
        {
            "source_id": "cmu:01:01",
            "source_sha256": "a" * 64,
            "conversion_version": "xbot-retarget-v1",
            "playback_glb_object_key": "cmu/previews/playback.glb",
            "playback_glb_sha256": hashlib.sha256(playback.read_bytes()).hexdigest(),
            "playback_glb_size_bytes": playback.stat().st_size,
            "preview_glb_object_key": "cmu/previews/preview.glb",
            "preview_glb_sha256": hashlib.sha256(preview.read_bytes()).hexdigest(),
            "preview_glb_size_bytes": preview.stat().st_size,
            "preview_floor_y": 0.0,
            "preview_ceiling_y": 1.8,
        },
        playback,
        preview,
    )


def test_upload_prepared_assets_sets_metadata_verifies_and_writes_manifest(
    tmp_path: Path,
) -> None:
    """Both roles carry integrity metadata and produce a verified snapshot."""
    client = FakeS3Client()
    output = tmp_path / "r2_assets.json"

    count = upload_prepared_assets(client, "bucket", [prepared_pair(tmp_path)], output)

    assert count == 1
    assert set(client.uploaded) == {
        "cmu/previews/playback.glb",
        "cmu/previews/preview.glb",
    }
    playback_args = client.uploaded["cmu/previews/playback.glb"]["extra"]
    assert playback_args["ContentType"] == "model/gltf-binary"
    assert playback_args["Metadata"]["asset_role"] == "playback"
    records = json.loads(output.read_text(encoding="utf-8"))
    assert records[0]["uploaded_at"].endswith("Z")
    assert records[0]["source_id"] == "cmu:01:01"


def test_upload_failure_preserves_existing_manifest(tmp_path: Path) -> None:
    """Failed remote verification cannot replace the authoritative manifest."""
    upload = prepared_pair(tmp_path)
    client = FakeS3Client(bad_key=upload.record["preview_glb_object_key"])
    output = tmp_path / "r2_assets.json"
    output.write_text("previous\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="R2 verification failed"):
        upload_prepared_assets(client, "bucket", [upload], output)

    assert output.read_text(encoding="utf-8") == "previous\n"

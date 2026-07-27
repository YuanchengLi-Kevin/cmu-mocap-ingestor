# Copyright (c) 2026 Yuancheng Li
# SPDX-License-Identifier: Apache-2.0

"""Tests for conversion profiles and metadata schema migration."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import pytest

from features.blender_conversion import conversion_metadata


def profile_args(**overrides: object) -> Namespace:
    """Return arguments matching the checked-in conversion profile."""
    values = {
        "conversion_version": "xbot-retarget-v1",
        "target_rig_name": "Armature",
        "scale": 1.0,
        "axis_forward": "-Z",
        "axis_up": "Y",
        "rotate_mode": "NATIVE",
        "trim_start_frames": 1,
        "export_frame_rate": 30.0,
        "no_gltfpack": False,
        "gltfpack_arg": [],
        "in_place_vertical_axis": "Y",
        "in_place_root_bone": None,
    }
    values.update(overrides)
    return Namespace(**values)


def legacy_metadata(*, status: str = "converted") -> dict[str, object]:
    """Return legacy metadata matching the checked-in conversion profile."""
    profile = conversion_metadata.conversion_profile("xbot-retarget-v1")
    metadata: dict[str, object] = {
        "source_id": "cmu:01:01",
        "conversion_status": status,
        "conversion_version": "xbot-retarget-v1",
        "error_message": None,
        "source_sha256": "a" * 64,
    }
    if status != "converted":
        return metadata
    metadata.update(
        {
            key: profile[key]
            for key in (
                "target_rig",
                "target_rig_name",
                "scale",
                "axis_forward",
                "axis_up",
                "rotate_mode",
                "trim_start_frames",
                "export_frame_rate",
                "gltfpack",
                "gltfpack_args",
            )
        }
    )
    metadata.update(
        {
            "source_frame_start": 1,
            "source_frame_end": 10,
            "export_frame_start": 1,
            "export_frame_end": 3,
            "export_frame_count": 3,
            "export_frame_rate": 30.0,
            "export_duration_seconds": 0.1,
            "variants": {
                "normal": {
                    "animation_variant": "normal",
                    "root_motion": profile["normal"]["root_motion"],
                    "glb_relative_path": "data/assets/previews/cmu_01_01.glb",
                    "glb_object_key": "cmu/previews/cmu_01_01.glb",
                    "glb_sha256": "b" * 64,
                    "glb_size_bytes": 10,
                },
                "in_place": {
                    "animation_variant": "in_place",
                    "root_motion": profile["in_place"]["root_motion"],
                    "in_place_root_bone": profile["in_place"]["root_bone"],
                    "in_place_vertical_axis": profile["in_place"]["vertical_axis"],
                    "in_place_neutralized_location_curves": 2,
                    "preview_frame": {"floor_y": 0.0, "ceiling_y": 1.8},
                    "glb_relative_path": "data/assets/previews/cmu_01_01_in_place.glb",
                    "glb_object_key": "cmu/previews/cmu_01_01_in_place.glb",
                    "glb_sha256": "c" * 64,
                    "glb_size_bytes": 9,
                },
            },
        }
    )
    return metadata


def test_load_profiles_validates_document_shape(tmp_path: Path) -> None:
    """Profiles must be a mapping from string versions to objects."""
    path = tmp_path / "profiles.json"
    path.write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="must be a JSON object"):
        conversion_metadata.load_profiles(path)


def test_conversion_profile_rejects_unknown_version() -> None:
    """Unknown conversion versions fail with a useful error."""
    with pytest.raises(ValueError, match="Unknown conversion profile"):
        conversion_metadata.conversion_profile("missing")


def test_validate_args_accepts_checked_in_profile() -> None:
    """Metadata-producing arguments can be checked against the shared profile."""
    conversion_metadata.validate_args_against_profile(
        profile_args(),
        target_rig="mixamo_xbot",
        default_gltfpack_args=["-kn", "-cc"],
        in_place_root_bone="mixamorig:Hips",
        retarget_frame_rate=30.0,
        preview_frame_sample_interval_seconds=0.5,
        preview_frame_humanoid_floor_y=0.0,
        preview_frame_y_margin=0.1,
    )


def test_validate_args_reports_profile_mismatches() -> None:
    """Divergent export settings name the profile fields that disagree."""
    with pytest.raises(ValueError, match="export_frame_rate"):
        conversion_metadata.validate_args_against_profile(
            profile_args(export_frame_rate=24.0),
            target_rig="mixamo_xbot",
            default_gltfpack_args=["-kn", "-cc"],
            in_place_root_bone="mixamorig:Hips",
            retarget_frame_rate=30.0,
            preview_frame_sample_interval_seconds=0.5,
            preview_frame_humanoid_floor_y=0.0,
            preview_frame_y_margin=0.1,
        )


def test_migrate_metadata_reduces_legacy_converted_record() -> None:
    """Legacy profile fields are replaced by schema-v2 asset-specific data."""
    migrated, changed = conversion_metadata.migrate_metadata(legacy_metadata())

    assert changed
    assert migrated["metadata_schema_version"] == 2
    assert "target_rig" not in migrated
    assert set(migrated["variants"]["normal"]) == {
        "glb_relative_path",
        "glb_object_key",
        "glb_sha256",
        "glb_size_bytes",
    }
    assert migrated["variants"]["in_place"]["preview_frame"]["ceiling_y"] == 1.8


def test_migrate_metadata_reduces_failed_record_without_variants() -> None:
    """Failed conversions retain identity and error fields without asset data."""
    migrated, changed = conversion_metadata.migrate_metadata(
        legacy_metadata(status="conversion_failed")
    )

    assert changed
    assert migrated["conversion_status"] == "conversion_failed"
    assert "variants" not in migrated


def test_migrate_metadata_validates_current_records_without_rewriting() -> None:
    """Already-current records are returned unchanged after validation."""
    current, _ = conversion_metadata.migrate_metadata(legacy_metadata())

    migrated, changed = conversion_metadata.migrate_metadata(current)

    assert migrated is current
    assert not changed


def test_migrate_metadata_rejects_unsupported_schema() -> None:
    """Unknown schemas are not guessed or silently rewritten."""
    with pytest.raises(ValueError, match="Unsupported metadata schema version"):
        conversion_metadata.migrate_metadata({"metadata_schema_version": 99})


def test_migrate_metadata_rejects_legacy_profile_drift() -> None:
    """Legacy metadata must match its declared shared conversion profile."""
    metadata = legacy_metadata()
    metadata["scale"] = 2.0

    with pytest.raises(ValueError, match="metadata does not match"):
        conversion_metadata.migrate_metadata(metadata)

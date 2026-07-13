# Copyright (c) 2026 Yuancheng Li
# SPDX-License-Identifier: Apache-2.0

"""Shared conversion profiles and preview metadata schema migration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


METADATA_SCHEMA_VERSION = 2
PROFILE_PATH = Path(__file__).with_name("conversion_profiles.json")


def load_profiles(path: Path = PROFILE_PATH) -> dict[str, dict[str, Any]]:
    """Load conversion profiles keyed by conversion version."""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and isinstance(profile, dict)
        for key, profile in value.items()
    ):
        raise ValueError(f"Conversion profiles must be a JSON object: {path}")
    return value


def conversion_profile(version: str) -> dict[str, Any]:
    """Return the profile for one conversion version."""
    profiles = load_profiles()
    try:
        return profiles[version]
    except KeyError as error:
        raise ValueError(f"Unknown conversion profile: {version}") from error


def validate_args_against_profile(
    args: Any,
    *,
    target_rig: str,
    default_gltfpack_args: list[str],
    in_place_root_bone: str,
    preview_frame_sample_count: int,
    preview_frame_humanoid_floor_y: float,
    preview_frame_y_margin: float,
) -> None:
    """Require metadata-producing conversion arguments to match their profile."""
    profile = conversion_profile(args.conversion_version)
    actual = {
        "target_rig": target_rig,
        "target_rig_name": args.target_rig_name,
        "scale": args.scale,
        "axis_forward": args.axis_forward,
        "axis_up": args.axis_up,
        "rotate_mode": args.rotate_mode,
        "trim_start_frames": args.trim_start_frames,
        "export_frame_rate": args.export_frame_rate,
        "gltfpack": not args.no_gltfpack,
        "gltfpack_args": [*default_gltfpack_args, *args.gltfpack_arg]
        if not args.no_gltfpack
        else [],
        "preview_frame_sample_count": preview_frame_sample_count,
        "preview_frame_humanoid_floor_y": preview_frame_humanoid_floor_y,
        "preview_frame_y_margin": preview_frame_y_margin,
    }
    mismatches = [
        key for key, value in actual.items() if profile.get(key) != value
    ]
    if args.in_place_vertical_axis != profile["in_place"]["vertical_axis"]:
        mismatches.append("in_place.vertical_axis")
    selected_root_bone = args.in_place_root_bone or in_place_root_bone
    if selected_root_bone != profile["in_place"]["root_bone"]:
        mismatches.append("in_place.root_bone")
    if mismatches:
        raise ValueError(
            f"Conversion arguments do not match {args.conversion_version}: "
            + ", ".join(mismatches)
        )


def _require_equal(metadata: dict[str, Any], profile: dict[str, Any]) -> None:
    """Require legacy per-motion profile fields to match the shared profile."""
    comparisons = {
        "target_rig": profile["target_rig"],
        "target_rig_name": profile["target_rig_name"],
        "scale": profile["scale"],
        "axis_forward": profile["axis_forward"],
        "axis_up": profile["axis_up"],
        "rotate_mode": profile["rotate_mode"],
        "trim_start_frames": profile["trim_start_frames"],
        "export_frame_rate": profile["export_frame_rate"],
        "gltfpack": profile["gltfpack"],
        "gltfpack_args": profile["gltfpack_args"],
    }
    mismatches = [
        key for key, expected in comparisons.items() if metadata.get(key) != expected
    ]
    variants = metadata.get("variants")
    if not isinstance(variants, dict):
        raise ValueError("converted metadata must contain a variants object")
    normal = variants.get("normal")
    in_place = variants.get("in_place")
    if not isinstance(normal, dict) or not isinstance(in_place, dict):
        raise ValueError("converted metadata must contain normal and in_place variants")
    variant_comparisons = {
        "normal.animation_variant": (normal.get("animation_variant"), "normal"),
        "normal.root_motion": (normal.get("root_motion"), profile["normal"]["root_motion"]),
        "in_place.animation_variant": (
            in_place.get("animation_variant"),
            "in_place",
        ),
        "in_place.root_motion": (
            in_place.get("root_motion"),
            profile["in_place"]["root_motion"],
        ),
        "in_place.root_bone": (
            in_place.get("in_place_root_bone"),
            profile["in_place"]["root_bone"],
        ),
        "in_place.vertical_axis": (
            in_place.get("in_place_vertical_axis"),
            profile["in_place"]["vertical_axis"],
        ),
    }
    mismatches.extend(
        key for key, (actual, expected) in variant_comparisons.items() if actual != expected
    )
    if mismatches:
        raise ValueError("metadata does not match its conversion profile: " + ", ".join(mismatches))


def _reduced_variant(variant: dict[str, Any], *, in_place: bool) -> dict[str, Any]:
    """Select per-asset fields from one legacy variant."""
    required = (
        "glb_relative_path",
        "glb_object_key",
        "glb_sha256",
        "glb_size_bytes",
    )
    missing = [key for key in required if key not in variant]
    if missing:
        raise ValueError("variant is missing fields: " + ", ".join(missing))
    reduced = {key: variant[key] for key in required}
    if in_place:
        reduced["in_place_neutralized_location_curves"] = variant.get(
            "in_place_neutralized_location_curves"
        )
        if "preview_frame" in variant:
            reduced["preview_frame"] = variant["preview_frame"]
    return reduced


def _validate_current_metadata(metadata: dict[str, Any]) -> None:
    """Validate metadata that already declares the current schema."""
    required = (
        "source_id",
        "conversion_status",
        "conversion_version",
        "error_message",
        "source_sha256",
    )
    missing = [key for key in required if key not in metadata]
    if missing:
        raise ValueError("current metadata is missing fields: " + ", ".join(missing))
    conversion_profile(metadata["conversion_version"])
    if metadata["conversion_status"] != "converted":
        return
    for key in (
        "source_frame_start",
        "source_frame_end",
        "export_frame_start",
        "export_frame_end",
        "export_frame_count",
        "export_frame_rate",
        "export_duration_seconds",
    ):
        if key not in metadata:
            raise ValueError(f"current converted metadata is missing field: {key}")
    variants = metadata.get("variants")
    if not isinstance(variants, dict):
        raise ValueError("current converted metadata must contain a variants object")
    normal = variants.get("normal")
    in_place = variants.get("in_place")
    if not isinstance(normal, dict) or not isinstance(in_place, dict):
        raise ValueError("current metadata must contain normal and in_place variants")
    _reduced_variant(normal, in_place=False)
    _reduced_variant(in_place, in_place=True)


def migrate_metadata(metadata: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Return schema-v2 metadata and whether the input was legacy metadata."""
    if metadata.get("metadata_schema_version") == METADATA_SCHEMA_VERSION:
        _validate_current_metadata(metadata)
        return metadata, False
    if "metadata_schema_version" in metadata:
        raise ValueError(
            f"Unsupported metadata schema version: {metadata['metadata_schema_version']}"
        )

    required = ("source_id", "conversion_status", "conversion_version")
    missing = [key for key in required if key not in metadata]
    if missing:
        raise ValueError("metadata is missing fields: " + ", ".join(missing))

    reduced: dict[str, Any] = {
        "metadata_schema_version": METADATA_SCHEMA_VERSION,
        "source_id": metadata["source_id"],
        "conversion_status": metadata["conversion_status"],
        "conversion_version": metadata["conversion_version"],
        "error_message": metadata.get("error_message"),
        "source_sha256": metadata.get("source_sha256"),
    }
    conversion_profile(metadata["conversion_version"])
    if metadata["conversion_status"] != "converted":
        return reduced, True

    profile = conversion_profile(metadata["conversion_version"])
    _require_equal(metadata, profile)
    for key in (
        "source_frame_start",
        "source_frame_end",
        "export_frame_start",
        "export_frame_end",
        "export_frame_count",
        "export_frame_rate",
        "export_duration_seconds",
    ):
        if key not in metadata:
            raise ValueError(f"converted metadata is missing field: {key}")
        reduced[key] = metadata[key]
    variants = metadata["variants"]
    reduced["variants"] = {
        "normal": _reduced_variant(variants["normal"], in_place=False),
        "in_place": _reduced_variant(variants["in_place"], in_place=True),
    }
    return reduced, True

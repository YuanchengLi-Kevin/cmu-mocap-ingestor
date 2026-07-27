# Copyright (c) 2026 Yuancheng Li
# SPDX-License-Identifier: Apache-2.0

"""Tests for Blender preview frame metadata."""

from __future__ import annotations

import importlib
import sys
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace


def import_blender_single(monkeypatch):
    """Import blender_single with a minimal bpy stub."""
    bpy_stub = SimpleNamespace(types=SimpleNamespace(Action=object, Object=object))
    monkeypatch.setitem(sys.modules, "bpy", bpy_stub)
    return importlib.import_module("features.blender_conversion.blender_single")


def test_pose_bone_z_bounds_uses_bone_origin_translations(monkeypatch) -> None:
    """Pose Z bounds use glTF-like bone origins instead of Blender heads and tails."""
    blender_single = import_blender_single(monkeypatch)

    class FakeWorldMatrix:
        def __matmul__(self, matrix):
            return matrix

    target = SimpleNamespace(
        matrix_world=FakeWorldMatrix(),
        pose=SimpleNamespace(
            bones=[
                SimpleNamespace(matrix=SimpleNamespace(translation=SimpleNamespace(x=1, y=2, z=3))),
                SimpleNamespace(matrix=SimpleNamespace(translation=SimpleNamespace(x=-4, y=5, z=-6))),
            ]
        ),
        update_from_editmode=lambda: None,
    )

    assert blender_single.pose_bone_z_bounds(target) == (-6, 3)


def test_preview_frame_from_bounds_normalizes_floor(monkeypatch) -> None:
    """Preview frame height is normalized to the reference floor."""
    blender_single = import_blender_single(monkeypatch)

    preview_frame = blender_single.preview_frame_from_bounds(
        floor_world_z=-3.24,
        max_world_z=2.06,
    )

    assert preview_frame == {
        "floor_y": 0.0,
        "ceiling_y": 5.300000000000001,
    }


def test_variant_metadata_emits_preview_frame_not_preview_bound(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """In-place variant metadata uses the new preview_frame key."""
    blender_single = import_blender_single(monkeypatch)
    glb_path = tmp_path / "cmu_01_01_in_place.glb"
    glb_path.write_bytes(b"glb")
    args = Namespace(
        source_id="cmu:01:01",
        input=tmp_path / "01_01.bvh",
        thumbnail_object_key=None,
        export_frame_rate=30.0,
    )
    preview_frame = {
        "floor_y": 0.0,
        "ceiling_y": 5.3,
    }

    metadata = blender_single.variant_metadata(
        args,
        glb_path=glb_path,
        animation_variant="in_place",
        preview_frame=preview_frame,
    )

    assert metadata["preview_frame"] == preview_frame
    assert set(metadata["preview_frame"]) == {"floor_y", "ceiling_y"}
    assert "preview_bound" not in metadata

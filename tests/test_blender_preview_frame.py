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


def test_pose_bone_bounds_uses_bone_origin_translations(monkeypatch) -> None:
    """Pose bounds use glTF-like bone origins instead of Blender heads and tails."""
    blender_single = import_blender_single(monkeypatch)
    blender_single.bpy.context = SimpleNamespace(
        view_layer=SimpleNamespace(update=lambda: None)
    )

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

    assert blender_single.pose_bone_bounds(target) == (-4, 1, 2, 5, -6, 3)


def test_preview_frame_from_bounds_uses_world_axes(monkeypatch) -> None:
    """Preview frame values come directly from sampled world-space bounds."""
    blender_single = import_blender_single(monkeypatch)

    preview_frame = blender_single.preview_frame_from_bounds(
        (-0.72, 0.64, -3.24, -2.24, -0.10, 2.06)
    )

    assert preview_frame == {
        "floor_y": -3.24,
        "ceiling_y": -2.24,
        "center_x": -0.03999999999999998,
        "center_z": 0.98,
        "width": 1.3599999999999999,
        "depth": 2.16,
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
    result = blender_single.RetargetResult(
        action=object(),
        source_frame_start=1,
        source_frame_end=10,
        export_frame_start=1,
        export_frame_end=10,
    )
    preview_frame = {
        "floor_y": -3.24,
        "ceiling_y": -2.24,
        "center_x": -0.04,
        "center_z": 0.98,
        "width": 1.36,
        "depth": 2.16,
    }

    metadata = blender_single.variant_metadata(
        args,
        result,
        action=SimpleNamespace(name="in_place_action"),
        glb_path=glb_path,
        root_motion="horizontal_removed",
        preview_frame=preview_frame,
    )

    assert metadata["preview_frame"] == preview_frame
    assert set(metadata["preview_frame"]) == {
        "floor_y",
        "ceiling_y",
        "center_x",
        "center_z",
        "width",
        "depth",
    }
    assert "preview_bound" not in metadata

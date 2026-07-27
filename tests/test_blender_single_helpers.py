# Copyright (c) 2026 Yuancheng Li
# SPDX-License-Identifier: Apache-2.0

"""Isolated tests for Blender single-conversion helpers."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def import_blender_single(monkeypatch: pytest.MonkeyPatch):
    """Import blender_single with a minimal bpy module."""
    bpy = SimpleNamespace(types=SimpleNamespace(Action=object, Object=object))
    monkeypatch.setitem(sys.modules, "bpy", bpy)
    module = importlib.import_module("features.blender_conversion.blender_single")
    monkeypatch.setattr(module, "bpy", bpy)
    return module


def test_asset_identity_and_timing_helpers(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Filenames and source IDs produce deterministic keys, paths, and timing."""
    single = import_blender_single(monkeypatch)

    assert single.source_id_from_filename(tmp_path / "01_02.bvh") == "cmu:01:02"
    assert single.default_glb_object_key("cmu:01:02") == "cmu/previews/cmu_01_02.glb"
    assert (
        single.default_glb_object_key("cmu:01:02", "in_place")
        == "cmu/previews/cmu_01_02_in_place.glb"
    )
    assert single.raw_glb_path_for(tmp_path / "motion.glb").name == "motion.raw.glb"
    assert single.frame_count(2, 4) == 3
    assert single.frame_count(4, 2) == 0
    assert single.duration_seconds(2, 4, 30.0) == 0.1
    assert single.duration_seconds(2, 4, 0) is None


def test_source_id_rejects_non_cmu_filename(monkeypatch: pytest.MonkeyPatch) -> None:
    """Source IDs are not guessed from malformed filenames."""
    single = import_blender_single(monkeypatch)

    with pytest.raises(ValueError, match="Cannot derive source_id"):
        single.source_id_from_filename(Path("walk.bvh"))


def test_sampled_frames_covers_range_without_exceeding_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preview sampling includes stable endpoints and handles empty ranges."""
    single = import_blender_single(monkeypatch)

    assert single.sampled_frames(1, 10, 3) == [1, 6, 10]
    assert single.sampled_frames(1, 3, 10) == [1, 2, 3]
    assert single.sampled_frames(3, 1, 2) == []
    assert single.sampled_frames(1, 10, 1) == [1]


def test_retime_action_scales_keyframe_and_handles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retiming scales every editable X coordinate around the start frame."""
    single = import_blender_single(monkeypatch)
    points = [
        SimpleNamespace(
            co=SimpleNamespace(x=1.0),
            handle_left=SimpleNamespace(x=0.5),
            handle_right=SimpleNamespace(x=1.5),
        ),
        SimpleNamespace(
            co=SimpleNamespace(x=3.0),
            handle_left=SimpleNamespace(x=2.5),
            handle_right=SimpleNamespace(x=3.5),
        ),
    ]
    fcurve = SimpleNamespace(keyframe_points=points, update=lambda: None)
    action = SimpleNamespace(fcurves=[fcurve])

    single.retime_action(action, source_fps=60.0, target_fps=30.0, frame_start=1)

    assert [point.co.x for point in points] == [1.0, 2.0]
    assert points[1].handle_left.x == 1.75


@pytest.mark.parametrize(("source_fps", "target_fps"), [(0, 30), (30, 0)])
def test_retime_action_rejects_nonpositive_rates(
    monkeypatch: pytest.MonkeyPatch,
    source_fps: float,
    target_fps: float,
) -> None:
    """Both source and target rates must be positive."""
    single = import_blender_single(monkeypatch)

    with pytest.raises(ValueError, match="positive"):
        single.retime_action(SimpleNamespace(), source_fps, target_fps, 1)


def test_resolve_in_place_root_bone_handles_explicit_and_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Root selection honors an explicit bone and otherwise finds a unique root."""
    single = import_blender_single(monkeypatch)
    hips = SimpleNamespace(name="Hips", parent=None)
    target = SimpleNamespace(pose=SimpleNamespace(bones={"Hips": hips}))

    assert single.resolve_in_place_root_bone(target, "Hips") == "Hips"
    assert single.resolve_in_place_root_bone(target, None) == "Hips"

    with pytest.raises(RuntimeError, match="not found"):
        single.resolve_in_place_root_bone(target, "Missing")


def test_run_gltfpack_returns_command_and_reports_failures(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The optimizer boundary forwards arguments and exposes process failures."""
    single = import_blender_single(monkeypatch)
    success = SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(single.subprocess, "run", lambda *args, **kwargs: success)

    command = single.run_gltfpack(
        executable="gltfpack",
        input_path=tmp_path / "raw.glb",
        output_path=tmp_path / "nested" / "motion.glb",
        extra_args=["-kn"],
    )

    assert command[-1] == "-kn"
    assert (tmp_path / "nested").is_dir()

    failure = SimpleNamespace(returncode=2, stdout="bad", stderr="worse")
    monkeypatch.setattr(single.subprocess, "run", lambda *args, **kwargs: failure)
    with pytest.raises(RuntimeError, match=r"exit code 2\s+bad"):
        single.run_gltfpack(
            executable="gltfpack",
            input_path=tmp_path / "raw.glb",
            output_path=tmp_path / "motion.glb",
            extra_args=[],
        )

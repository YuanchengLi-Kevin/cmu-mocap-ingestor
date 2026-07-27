# Copyright (c) 2026 Yuancheng Li
# SPDX-License-Identifier: Apache-2.0

"""Isolated tests for single-process Blender batch orchestration."""

from __future__ import annotations

import importlib
import json
import sys
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest


def import_batch(monkeypatch: pytest.MonkeyPatch):
    """Import batch modules with a controllable bpy stub."""
    bpy = SimpleNamespace(
        types=SimpleNamespace(Action=object, Object=object),
        data=SimpleNamespace(actions=[], objects={}),
        context=SimpleNamespace(
            scene=SimpleNamespace(frame_current=1, frame_set=lambda frame: None),
            view_layer=SimpleNamespace(update=lambda: None),
        ),
    )
    monkeypatch.setitem(sys.modules, "bpy", bpy)
    single = importlib.import_module("features.blender_conversion.blender_single")
    batch = importlib.import_module("features.blender_conversion.blender_batch")
    monkeypatch.setattr(single, "bpy", bpy)
    monkeypatch.setattr(batch, "bpy", bpy)
    return batch, single


def batch_args(tmp_path: Path) -> Namespace:
    """Return the batch options consumed by record_args."""
    return Namespace(
        input_root=tmp_path / "source",
        glb_dir=tmp_path / "previews",
        in_place_glb_dir=tmp_path / "previews",
        metadata_dir=tmp_path / "previews",
        variant="both",
        conversion_version="xbot-retarget-v1",
        target_rig_name="Armature",
        export_frame_rate=30.0,
        trim_start_frames=1,
        scale=1.0,
        axis_forward="-Z",
        axis_up="Y",
        rotate_mode="NATIVE",
        rokoko_addon="rokoko",
        in_place_root_bone="mixamorig:Hips",
        in_place_vertical_axis="Y",
        no_gltfpack=False,
        gltfpack_path="gltfpack",
        gltfpack_arg=[],
        keep_raw_glb=False,
    )


def record() -> dict[str, object]:
    """Return one selected manifest record."""
    return {
        "source_id": "cmu:01:01",
        "relative_path": "001/01_01.bvh",
        "frame_rate": 120.0,
        "validation_status": "valid",
    }


def test_read_motion_records_filters_invalid_and_applies_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Batch selection preserves manifest order and keeps only valid records."""
    batch, _ = import_batch(monkeypatch)
    path = tmp_path / "motions.json"
    records = [
        record(),
        {**record(), "source_id": "cmu:01:02", "validation_status": "invalid"},
        {**record(), "source_id": "cmu:01:03"},
    ]
    path.write_text(json.dumps(records), encoding="utf-8")

    selected = batch.read_motion_records(path, 1)

    assert [item["source_id"] for item in selected] == ["cmu:01:01"]
    with pytest.raises(ValueError, match="limit must be positive"):
        batch.read_motion_records(path, 0)


def test_record_args_builds_deterministic_paths_and_rate_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Each manifest record maps to the expected local asset paths and defaults."""
    batch, single = import_batch(monkeypatch)
    args = batch_args(tmp_path)
    item = record()
    item["frame_rate"] = None

    converted = batch.record_args(args, item)

    assert converted.input == (tmp_path / "source/001/01_01.bvh").resolve()
    assert converted.glb.name == "cmu_01_01.glb"
    assert converted.in_place_glb.name == "cmu_01_01_in_place.glb"
    assert converted.metadata.name == "cmu_01_01.json"
    assert converted.source_frame_rate == single.DEFAULT_SOURCE_FRAME_RATE


def test_process_record_runs_both_variants_and_writes_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Successful orchestration exports normal and in-place roles before metadata."""
    batch, single = import_batch(monkeypatch)
    args = batch_args(tmp_path)
    input_path = args.input_root / "001/01_01.bvh"
    input_path.parent.mkdir(parents=True)
    input_path.write_text("BVH", encoding="utf-8")
    normal_action = object()
    in_place_action = object()
    result = SimpleNamespace(action=normal_action)
    exported: list[Path] = []
    written: dict[str, object] = {}
    monkeypatch.setattr(batch, "restore_target_state", lambda *args: None)
    monkeypatch.setattr(batch, "remove_source_object", lambda *args: None)
    monkeypatch.setattr(batch, "remove_new_actions", lambda *args: None)
    monkeypatch.setattr(batch, "keep_only_action", lambda *args: None)
    monkeypatch.setattr(single, "import_bvh", lambda args: object())
    monkeypatch.setattr(single, "retarget_animation", lambda **kwargs: result)
    monkeypatch.setattr(
        single,
        "create_in_place_action",
        lambda *args, **kwargs: SimpleNamespace(
            action=in_place_action,
            neutralized_location_curves=2,
        ),
    )
    monkeypatch.setattr(
        single,
        "export_glb_asset",
        lambda **kwargs: exported.append(kwargs["glb_path"]),
    )
    monkeypatch.setattr(
        single,
        "variant_metadata",
        lambda args, **kwargs: {"role": kwargs["animation_variant"]},
    )
    monkeypatch.setattr(
        single,
        "preview_frame_metadata",
        lambda *args, **kwargs: {"floor_y": 0.0, "ceiling_y": 1.8},
    )
    monkeypatch.setattr(
        single,
        "write_metadata",
        lambda path, args, result, **kwargs: written.update(kwargs),
    )
    target = SimpleNamespace(animation_data=SimpleNamespace(action=None))

    succeeded = batch.process_record(
        args,
        record(),
        target,
        SimpleNamespace(),
        set(),
    )

    assert succeeded
    assert [path.name for path in exported] == [
        "cmu_01_01.glb",
        "cmu_01_01_in_place.glb",
    ]
    assert written["variants"] == {
        "normal": {"role": "normal"},
        "in_place": {"role": "in_place"},
    }


def test_process_record_writes_failure_metadata_and_returns_false(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A missing BVH becomes resumable failure metadata and still runs cleanup."""
    batch, _ = import_batch(monkeypatch)
    args = batch_args(tmp_path)
    cleanup: list[str] = []
    monkeypatch.setattr(batch, "restore_target_state", lambda *args: cleanup.append("restore"))
    monkeypatch.setattr(batch, "remove_source_object", lambda *args: cleanup.append("source"))
    monkeypatch.setattr(batch, "remove_new_actions", lambda *args: cleanup.append("actions"))

    succeeded = batch.process_record(
        args,
        record(),
        SimpleNamespace(),
        SimpleNamespace(),
        set(),
    )

    assert not succeeded
    metadata = json.loads((args.metadata_dir / "cmu_01_01.json").read_text(encoding="utf-8"))
    assert metadata["conversion_status"] == "conversion_failed"
    assert "does not exist" in metadata["error_message"]
    assert cleanup[-3:] == ["source", "restore", "actions"]

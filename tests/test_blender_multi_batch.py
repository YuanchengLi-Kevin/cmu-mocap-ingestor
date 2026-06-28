# Copyright (c) 2026 Yuancheng Li
# SPDX-License-Identifier: Apache-2.0

"""Tests for the multi-worker Blender batch launcher."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from features.blender_conversion import blender_multi_batch as multi_batch


def manifest_record(
    source_id: str,
    *,
    validation_status: str = "valid",
) -> dict[str, object]:
    """Return one minimal joined manifest record."""
    subject_id, trial_id = source_id.split(":")[1:]
    return {
        "source_id": source_id,
        "relative_path": f"{int(subject_id):03d}/{subject_id}_{trial_id}.bvh",
        "frame_rate": 120.0,
        "validation_status": validation_status,
    }


def write_json(path: Path, value: object) -> None:
    """Write a compact test JSON document."""
    path.write_text(json.dumps(value), encoding="utf-8")


def parse_args(tmp_path: Path, *extra_args: str) -> object:
    """Return parsed launcher args with test-local paths."""
    manifest = tmp_path / "motions.json"
    template = tmp_path / "xbot_template.blend"
    input_root = tmp_path / "data"
    output_root = tmp_path / "previews"
    template.write_text("", encoding="utf-8")
    input_root.mkdir()
    output_root.mkdir()

    return multi_batch.parse_args(
        [
            "--template-blend",
            str(template),
            "--manifest",
            str(manifest),
            "--input-root",
            str(input_root),
            "--glb-dir",
            str(output_root),
            "--in-place-glb-dir",
            str(output_root),
            "--metadata-dir",
            str(output_root),
            *extra_args,
        ]
    )


def test_select_records_filters_valid_records_and_respects_limit(tmp_path: Path) -> None:
    """Record selection keeps valid records in manifest order up to the limit."""
    args = parse_args(tmp_path, "--limit", "2")
    write_json(
        args.manifest,
        [
            manifest_record("cmu:01:01"),
            manifest_record("cmu:01:02", validation_status="invalid"),
            manifest_record("cmu:01:03"),
            manifest_record("cmu:01:04"),
        ],
    )

    selected = multi_batch.select_records(args)

    assert [record["source_id"] for record in selected] == ["cmu:01:01", "cmu:01:03"]


def test_select_records_can_skip_converted_metadata(tmp_path: Path) -> None:
    """Resume filtering skips records already marked converted."""
    args = parse_args(tmp_path, "--limit", "2", "--skip-existing-metadata")
    write_json(args.manifest, [manifest_record("cmu:01:01"), manifest_record("cmu:01:02")])
    write_json(args.metadata_dir / "cmu_01_01.json", {"conversion_status": "converted"})

    selected = multi_batch.select_records(args)

    assert [record["source_id"] for record in selected] == ["cmu:01:02"]


def test_select_records_rejects_empty_selection(tmp_path: Path) -> None:
    """The launcher fails clearly when no valid records are selected."""
    args = parse_args(tmp_path)
    write_json(args.manifest, [manifest_record("cmu:01:01", validation_status="invalid")])

    with pytest.raises(ValueError, match="No valid records selected"):
        multi_batch.select_records(args)


def test_partition_records_balances_without_duplication() -> None:
    """Shards are balanced, contiguous, and cover each record once."""
    records = [manifest_record(f"cmu:01:{index:02d}") for index in range(1, 6)]

    shards = multi_batch.partition_records(records, 2)

    assert [len(shard) for shard in shards] == [3, 2]
    assert [record["source_id"] for shard in shards for record in shard] == [
        "cmu:01:01",
        "cmu:01:02",
        "cmu:01:03",
        "cmu:01:04",
        "cmu:01:05",
    ]


def test_worker_command_uses_batch_script_and_forwards_options(tmp_path: Path) -> None:
    """Worker commands call Blender with the batch script and forwarded flags."""
    args = parse_args(
        tmp_path,
        "--blender-path",
        "C:/Blender/blender.exe",
        "--workers",
        "2",
        "--variant",
        "both",
        "--export-frame-rate",
        "24",
        "--trim-start-frames",
        "3",
        "--gltfpack-path",
        "C:/tools/gltfpack.exe",
        "--gltfpack-arg=-si=0.5",
        "--no-gltfpack",
        "--keep-raw-glb",
    )
    shard = tmp_path / "shard.json"

    command = multi_batch.worker_command(args, shard, 7)

    assert command[:3] == ["C:/Blender/blender.exe", "--background", str(args.template_blend)]
    assert "--python" in command
    assert str(multi_batch.DEFAULT_BATCH_SCRIPT) in command
    separator_index = command.index("--")
    script_args = command[separator_index + 1 :]
    assert script_args[script_args.index("--manifest") + 1] == str(shard)
    assert script_args[script_args.index("--limit") + 1] == "7"
    assert script_args[script_args.index("--variant") + 1] == "both"
    assert script_args[script_args.index("--export-frame-rate") + 1] == "24.0"
    assert script_args[script_args.index("--trim-start-frames") + 1] == "3"
    assert "--axis-forward=-Z" in script_args
    assert "--axis-forward" not in script_args
    assert script_args[script_args.index("--gltfpack-path") + 1] == "C:/tools/gltfpack.exe"
    assert ["--gltfpack-arg", "-si=0.5"] == script_args[
        script_args.index("--gltfpack-arg") : script_args.index("--gltfpack-arg") + 2
    ]
    assert "--no-gltfpack" in script_args
    assert "--keep-raw-glb" in script_args


def test_run_worker_commands_uses_injected_process_factory() -> None:
    """Worker execution can be tested without starting Blender."""
    launched = []

    class FakeProcess:
        stdout = ["worker output\n"]

        def wait(self) -> int:
            return 0

    def fake_popen(command: list[str], **kwargs: object) -> FakeProcess:
        launched.append((command, kwargs))
        return FakeProcess()

    exit_codes = multi_batch.run_worker_commands(
        [["blender", "--background", "template.blend"]],
        popen_factory=fake_popen,
    )

    assert exit_codes == [0]
    assert launched[0][0] == ["blender", "--background", "template.blend"]
    assert launched[0][1]["text"] is True

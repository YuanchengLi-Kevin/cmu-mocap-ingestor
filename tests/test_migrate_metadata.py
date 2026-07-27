# Copyright (c) 2026 Yuancheng Li
# SPDX-License-Identifier: Apache-2.0

"""Tests for the preview metadata migration command."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest

from features.blender_conversion import migrate_metadata as command


def test_read_object_rejects_non_object_json(tmp_path: Path) -> None:
    """Each preview metadata file must contain one object."""
    path = tmp_path / "metadata.json"
    path.write_text("[]", encoding="utf-8")

    with pytest.raises(TypeError, match="must be a JSON object"):
        command.read_object(path)


def test_write_object_atomic_replaces_json(tmp_path: Path) -> None:
    """The migration writer emits indented JSON with a trailing newline."""
    path = tmp_path / "metadata.json"
    path.write_text('{"old": true}', encoding="utf-8")

    command.write_object_atomic(path, {"schema": 2})

    assert path.read_text(encoding="utf-8") == '{\n  "schema": 2\n}\n'
    assert list(tmp_path.glob(".metadata.json.*.tmp")) == []


def test_main_dry_run_validates_without_writing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Dry-run reports migrations while preserving every source file."""
    path = tmp_path / "record.json"
    path.write_text('{"legacy": true}', encoding="utf-8")
    monkeypatch.setattr(
        command,
        "parse_args",
        lambda: Namespace(metadata_dir=tmp_path, dry_run=True, write=False),
    )
    monkeypatch.setattr(command, "migrate_metadata", lambda value: ({"current": True}, True))

    command.main()

    assert json.loads(path.read_text(encoding="utf-8")) == {"legacy": True}
    assert "Would migrate 1 files" in capsys.readouterr().out


def test_main_validates_all_files_before_writing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """One invalid input prevents otherwise valid migrations from being written."""
    valid = tmp_path / "a.json"
    invalid = tmp_path / "b.json"
    valid.write_text('{"legacy": true}', encoding="utf-8")
    invalid.write_text("{", encoding="utf-8")
    monkeypatch.setattr(
        command,
        "parse_args",
        lambda: Namespace(metadata_dir=tmp_path, dry_run=False, write=True),
    )
    monkeypatch.setattr(command, "migrate_metadata", lambda value: ({"current": True}, True))

    with pytest.raises(SystemExit) as error:
        command.main()

    assert error.value.code == 1
    assert json.loads(valid.read_text(encoding="utf-8")) == {"legacy": True}


def test_main_rejects_empty_metadata_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The command does not report success when there is no work to validate."""
    monkeypatch.setattr(
        command,
        "parse_args",
        lambda: Namespace(metadata_dir=tmp_path, dry_run=True, write=False),
    )

    with pytest.raises(SystemExit, match="No JSON metadata"):
        command.main()
